"""Validate the specific standard-cell latch contract used by older arrays."""
import re

def validate_ckln_model(model):
    if set(model)!={'pins','states'}:return False
    pins=model['pins']
    if set(pins)!={'CP','E','Q','QD','TE'}:return False
    if pins['CP']!={'clock':'true','direction':'input'}:return False
    if pins['E']!={'direction':'input'} or pins['TE']!={'direction':'input'}:return False
    if pins['QD']!={'direction':'internal'}:return False
    if pins['Q']!={'direction':'output','state_function':'"CP*QD"'}:return False
    if len(model['states'])!=1:return False
    kind,arguments,fields=model['states'][0]
    if kind!='statetable' or set(fields)!={'table'}:return False
    arguments=re.findall(r'"([^"]*)"',arguments)
    if len(arguments)!=2 or arguments[0].split()!=['CP','TE','E'] or arguments[1].split()!=['QD']:return False
    table=fields['table']
    if len(table)<2 or table[0]!='"' or table[-1]!='"':return False
    table=table[1:-1].replace(chr(92)+'\n','')
    rows=[]
    for raw in table.split(','):
        parts=raw.split(':')
        if len(parts)!=3:return False
        rows.append(tuple(tuple(part.split()) for part in parts))
    expected=[(('L','L','L'),('-',),('L',)),(('L','L','H'),('-',),('H',)),(('L','H','L'),('-',),('H',)),(('L','H','H'),('-',),('H',)),(('H','-','-'),('-',),('N',))]
    return len(rows)==5 and set(rows)==set(expected)
