"""Plan local noninverting branches and a bounded-fanout upper buffer tree."""
import argparse
import math
from pathlib import Path


def plan_buffers(rows, *, leaf_loads=32, branch_fanout=4):
    if type(leaf_loads) is not int or type(branch_fanout) is not int or leaf_loads < 1 or branch_fanout < 2:
        raise ValueError('Positive leaf capacity and shrinking upper branches required')
    points, names = [], set()
    for row in rows:
        try:
            pin, x, y = row
            x, y = float(x), float(y)
        except (ValueError, TypeError) as error:
            raise ValueError('Malformed physical sink') from error
        if not isinstance(pin, str) or not pin or not pin.isprintable() or any(char.isspace() for char in pin) or pin in names or not math.isfinite(x) or not math.isfinite(y):
            raise ValueError('Unique serializable sinks and finite geometry required')
        names.add(pin)
        points.append((pin, x, y))
    if not points:
        raise ValueError('An empty tree cannot repair a net')

    def partition(items, groups):
        if groups == 1:
            return [sorted(items)]
        spans = [max(row[axis] for row in items)-min(row[axis] for row in items) for axis in [1, 2]]
        axis = 1 if spans[0] >= spans[1] else 2
        ordered = sorted(items, key=lambda row: (row[axis], row[3-axis], row[0]))
        left_groups = groups//2
        cut = len(items)*left_groups//groups
        return partition(ordered[:cut], left_groups)+partition(ordered[cut:], groups-left_groups)

    nodes = []
    for group in partition(points, (len(points)+leaf_loads-1)//leaf_loads):
        nodes.append(dict(id=len(nodes), level=0, master='BUFFD4BWP12T40P140', x=math.fsum(row[1] for row in group)/len(group), y=math.fsum(row[2] for row in group)/len(group), load_count=len(group), pins=[row[0] for row in group], children=[]))
    current = list(range(len(nodes)))
    while len(current) > 1:
        parents = []
        for start in range(0, len(current), branch_fanout):
            children = current[start:start+branch_fanout]
            count = sum(nodes[index]['load_count'] for index in children)
            node = dict(id=len(nodes), level=1+max(nodes[index]['level'] for index in children), master='BUFFD8BWP12T40P140', x=math.fsum(nodes[index]['x']*nodes[index]['load_count'] for index in children)/count, y=math.fsum(nodes[index]['y']*nodes[index]['load_count'] for index in children)/count, load_count=count, pins=[], children=children)
            nodes.append(node)
            parents.append(node['id'])
        current = parents
    nodes[-1]['master'] = 'BUFFD16BWP12T40P140'
    return nodes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sinks', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    assert not args.output.exists()
    rows = []
    with args.sinks.open() as stream:
        if stream.readline() != 'pin\tlocation\n':
            raise ValueError('Unexpected native sink inventory header')
        for line in stream:
            pin, location = line.rstrip('\n').split('\t')
            x, y = location.strip('{}').split()
            rows.append((pin, float(x), float(y)))
    nodes = plan_buffers(rows)
    with args.output.open('w') as stream:
        stream.write('id\tlevel\tmaster\tx\ty\tkind\ttargets\n')
        for node in nodes:
            kind = 'leaf' if node['pins'] else 'parent'
            targets = node['pins'] if node['pins'] else list(map(str, node['children']))
            stream.write(f"{node['id']}\t{node['level']}\t{node['master']}\t{node['x']:.6f}\t{node['y']:.6f}\t{kind}\t{' '.join(targets)}\n")


if __name__ == '__main__':
    main()
