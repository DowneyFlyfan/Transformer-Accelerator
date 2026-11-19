"""Inventory fully parsed module bodies and count reachable instance multiplicity."""
from collections import Counter
from pathlib import Path
import re,sys
sys.path.insert(0,str(Path.cwd()/'syn'))
from prove_tri_oracle_command_admission import parse_admission_module

def inventory(definitions,read_body,leaf_masters,top,guard=lambda:None):
 assert top in definitions,'Missing logical top'
 modules={}
 for name in sorted(definitions):
  guard();raw=read_body(name)
  assert re.match(rb'\s*module\s+'+re.escape(name.encode())+rb'\s*\(',raw),('Module name differs',name)
  parsed=parse_admission_module(raw)
  project={instance:master for instance,(master,_) in parsed.cells.items() if master in definitions}
  leaves=Counter(master for master,_ in parsed.cells.values() if master not in definitions)
  modules[name]=dict(module_sha256=parsed.sha256,project_instances=project,leaf_instances=dict(sorted(leaves.items())),cell_instances=len(parsed.cells),port_directions=parsed.directions)
 order=[];active=set();visited=set()
 def visit(name):
  assert name not in active,('Recursive module hierarchy',name)
  if name in visited:return
  active.add(name)
  for child in set(modules[name]['project_instances'].values()):visit(child)
  unknown=modules[name]['leaf_instances'].keys()-leaf_masters
  assert not unknown,('Unknown reachable leaf master',name,sorted(unknown))
  active.remove(name);visited.add(name);order.append(name)
 visit(top)
 occurrences=Counter({top:1});leaves=Counter()
 for name in reversed(order):
  count=occurrences[name]
  for child in modules[name]['project_instances'].values():occurrences[child]+=count
  for leaf,local in modules[name]['leaf_instances'].items():leaves[leaf]+=count*local
 return dict(top=top,modules=modules,module_occurrences=dict(sorted(occurrences.items())),leaf_occurrences=dict(sorted(leaves.items())),unreachable_modules=sorted(definitions-visited))
