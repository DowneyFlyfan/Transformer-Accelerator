"""Compare complete cell token streams with only specify blocks disabled."""
import re

TOKEN=re.compile(r'(?P<space>\s+)|(?P<line>//[^\n]*)|(?P<block>/\*[\s\S]*?\*/)|(?P<string>"(?:\\[\s\S]|[^"\\\n])*")|(?P<escaped>\\[^\s]+)|(?P<identifier>[A-Za-z_$][A-Za-z0-9_$]*)|(?P<number>[0-9]+(?:\'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ?_]+)?(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)|(?P<punct>[^\s])')

def tokens(text):
 result=[];position=0
 while position<len(text):
  assert not text.startswith('/*',position) or re.match(r'/\*[\s\S]*?\*/',text[position:]),'Unterminated Verilog comment'
  match=TOKEN.match(text,position);assert match is not None,('Unrecognized model token',position)
  assert not (match.lastgroup=='punct' and match[0]=='"'),'Unterminated Verilog string'
  if match.lastgroup not in ('space','line','block'):result.append(match[0])
  position=match.end()
 return result

def functional_models(text,names):
 stream=tokens(text);result={};index=0
 while index<len(stream):
  if stream[index]!='module':index+=1;continue
  assert index+2<len(stream),'Missing model header'
  name=stream[index+1];end=index+2
  while end<len(stream) and stream[end]!='endmodule':
   assert stream[end]!='module','Nested model declaration';end+=1
  assert end<len(stream),('Unterminated model',name)
  if name in names:
   assert name not in result,('Duplicate model',name)
   body=['module','@cell'];position=index+2;timing=False
   while position<end:
    token=stream[position]
    if token=='specify':
     assert not timing,'Nested specify block';timing=True
    elif token=='endspecify':
     assert timing,'Unmatched endspecify';timing=False
    elif not timing:body.append(token)
    position+=1
   assert not timing,'Unterminated specify block'
   body.append('endmodule');result[name]=tuple(body)
  index=end+1
 assert result.keys()==names,('Missing selected cell models',sorted(names-result.keys()))
 return result
