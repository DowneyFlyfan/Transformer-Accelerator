"""Deterministic best-fit row-interval packing, without moving retained cells."""
from bisect import bisect_left, insort
from collections import Counter
import heapq
import re

MODULE = re.compile(r'(?ms)^module\s+(\w+)\s*\(.*?\);(.*?)^endmodule\b')
INSTANCE = re.compile(r'(?m)^[ \t]*([A-Za-z_$][\w$]*)\s+(\\\S+|[A-Za-z_$][\w$]*)\s*\(\s*\.')

def enumerate_leaves(text, top, known_cells):
    modules = {}
    for match in MODULE.finditer(text):
        if match[1] in modules:
            raise ValueError('Duplicate module')
        children = [(master, instance.removeprefix('\\')) for master,instance in INSTANCE.findall(match[2])]
        if len({name for _,name in children}) != len(children):
            raise ValueError('Duplicate instance')
        modules[match[1]] = children
    def visit(master, prefix, active):
        if master in active:
            raise ValueError('Recursive hierarchy')
        if master not in modules:
            if master not in known_cells:
                raise ValueError('Unknown leaf cell')
            yield prefix, master
            return
        for cell,name in modules[master]:
            if '/' in name or re.search(r'\s',name):
                raise ValueError('Unsupported instance name')
            yield from visit(cell, prefix + '/' + name if prefix else name, active | {master})
    if top not in modules:
        raise ValueError('Missing top module')
    return list(visit(top,'',set()))

def pack(cells, holes, target, pitch, height):
    """cells=(name,master,width), holes=(row,column,width), all in site units."""
    keys, bins = [], {}
    target_x, target_y = target
    def push(row,column,width):
        if width <= 0:
            return
        distance = abs((column + width/2)*pitch - target_x) + abs((row+.5)*height-target_y)
        if width not in bins:
            bins[width] = []
            insort(keys,width)
        heapq.heappush(bins[width],(distance,row,column))
    for row,column,width in holes:
        push(row,column,width)
    if len({name for name,_,_ in cells}) != len(cells):
        raise ValueError('Duplicate physical instance')
    result = []
    for name,master,width in sorted(cells,key=lambda item:(-item[2],item[0])):
        if width <= 0:
            raise ValueError('Nonpositive cell width')
        index = bisect_left(keys,width)
        if index == len(keys):
            raise ValueError('No free interval fits '+name)
        length = keys[index]
        _,row,column = heapq.heappop(bins[length])
        if not bins[length]:
            del bins[length]
            keys.pop(index)
        if abs(column*pitch-target_x) <= abs((column+length-width)*pitch-target_x):
            chosen = column
            push(row,column+width,length-width)
        else:
            chosen = column+length-width
            push(row,column,length-width)
        result.append((name,master,row,chosen,width))
    return result
