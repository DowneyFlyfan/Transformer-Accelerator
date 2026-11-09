"""Generate complete explicit named connections for the frozen controller interfaces."""
import re
from pathlib import Path


def controller_adapter(original_path, imported_netlist, imported_module, *, explicit=True):
    original=Path(original_path).read_text()
    name=Path(original_path).stem
    start=original.index('module '+name+' (')
    end=original.index('\n);',start)+4
    header=original[start:end]
    payload=header[header.index('(')+1:header.rindex(')')]
    payload=re.sub(r'\[[^\]]*\]','',payload)
    tokens=re.findall(r'\b[A-Za-z_]\w*\b',payload)
    ports=[token for token in tokens if token not in {'input','output','inout','wire','reg','logic','signed','unsigned'}]
    assert ports and len(ports)==len(set(ports))
    netlist=Path(imported_netlist).read_text()
    match=re.search(r'\bmodule\s+'+re.escape(imported_module)+r'\s*\((.*?)\);',netlist,re.S)
    assert match
    imported_ports=re.findall(r'\b[A-Za-z_]\w*\b',match.group(1))
    assert len(imported_ports)==len(set(imported_ports)) and set(imported_ports)==set(ports)
    connections=',\n        '.join('.'+port+'('+port+')' for port in ports) if explicit else '.*'
    return ('`timescale 1ns/1ps\n'+header+'\n    '+imported_module+' implementation (\n        '+connections+'\n    );\nendmodule\n',ports)
