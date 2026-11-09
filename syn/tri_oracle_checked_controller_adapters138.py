"""Validate every controller port direction/width before emitting named adapters."""
import re
from pathlib import Path

from tri_oracle_named_controller_adapters137 import controller_adapter


def declarations(text):
    result={};direction=None;width=1
    for segment in text.split(','):
        found=re.search(r'\b(input|output|inout)\b',segment)
        if found:
            direction=found.group(1);width=1
        bits=re.search(r'\[(\d+)\s*:\s*(\d+)\]',segment)
        if bits:width=abs(int(bits.group(1))-int(bits.group(2)))+1
        segment=re.sub(r'\[[^\]]*\]','',segment)
        names=[x for x in re.findall(r'\b[A-Za-z_]\w*\b',segment) if x not in {'input','output','inout','wire','reg','logic','signed','unsigned'}]
        assert len(names)==1 and direction is not None,segment
        assert names[0] not in result
        result[names[0]]={'direction':direction,'width_bits':width}
    return result


def checked_controller_adapter(original_path, imported_netlist, imported_module, *, explicit=True):
    adapter,ports=controller_adapter(original_path,imported_netlist,imported_module,explicit=explicit)
    first=adapter.index('(');last=adapter.index('\n);',first)
    expected=declarations(adapter[first+1:last])
    mapped=Path(imported_netlist).read_text()
    actual={}
    for match in re.finditer(r'^\s*(input|output|inout)\s+([^;]+);',mapped,re.M):
        for name,shape in declarations(match.group(1)+' '+match.group(2)).items():
            assert name not in actual
            actual[name]=shape
    assert actual==expected,'Controller interface direction/width mismatch'
    assert set(ports)==set(expected)
    return adapter,expected
