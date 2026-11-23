"""Portable source-preparation controls; no simulator or vendor files required."""
from pathlib import Path
import copy,hashlib,importlib.util,json,tempfile,unittest
from unittest.mock import patch
P=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('row_replay',P/'prepare_tri_oracle_row_replay.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def digest(raw):return hashlib.sha256(raw).hexdigest()
def sequence(events):
 return digest(json.dumps([dict(kind=e['kind'],**({'name':e['name']} if e['kind']=='define' else {'sha256':e['sha256']})) for e in events],sort_keys=True,separators=(',',':')).encode())

class SourceReplayTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='row_replay_test_',dir=P.parent/'.cache');self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);(self.root/'verilog').mkdir();(self.root/'.cache').mkdir();(self.root/'models').mkdir()
  self.events=[dict(kind='define',name='UNIT_DELAY'),dict(kind='define',name='TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC')]
  self.memories=[]
  for i in range(73):
   path=self.root/'verilog'/f'unit_{i}.sv';path.write_text(f'module unit_{i}; endmodule\n')
   self.events.append(dict(kind='source',path='verilog/'+path.name,sha256=digest(path.read_bytes())))
   if i<6:
    v=self.root/'models'/f'memory_{i}.v';v.write_text(f'module memory_{i}; endmodule\n');self.memories.append(v)
    self.events.append(dict(kind='memory',path=v.name,sha256=digest(v.read_bytes())))
  self.frozen=sequence(self.events);self.manifest=self.root/'manifest.json';self.output=self.root/'.cache/replay'
  self.config=dict(version=1,ordered_events=self.events,source_sequence_sha256=self.frozen)
  self.patches=[patch.object(m,'ROOT',self.root),patch.dict(m.FROZEN_SEQUENCES,learned=self.frozen)]
  for obj in self.patches:obj.start();self.addCleanup(obj.stop)
 def prepare(self,config=None,memories=None,output=None):
  self.manifest.write_text(json.dumps(self.config if config is None else config))
  return m.prepare('learned',self.manifest,self.memories if memories is None else memories,self.output if output is None else output)
 def invalid(self,config=None,memories=None,output=None):
  with self.assertRaises((ValueError,OSError,KeyError,TypeError)):self.prepare(config,memories,output)
  self.assertFalse(self.output.exists())
 def test_valid_order_and_external_models(self):
  r=self.prepare();lines=(self.output/'bundle.sv').read_text().splitlines()
  self.assertEqual(lines[:2],['`define UNIT_DELAY','`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC'])
  self.assertIn(str(self.memories[0]),lines[3]);self.assertEqual(len(lines),81)
  self.assertEqual(r['repository_sources'],73);self.assertEqual(r['external_memory_models'],6)
  self.assertEqual(set(p.name for p in self.output.iterdir()),{'bundle.sv','receipt.json'})
  self.assertFalse(r['vendor_memory_contents_copied']);self.assertFalse(r['native_execution_verified']);self.assertFalse(r['paper_matching'])
 def test_bad_version(self):
  c=copy.deepcopy(self.config);c['version']=99;self.invalid(c)
 def test_missing_memory(self):self.invalid(memories=self.memories[:-1])
 def test_extra_memory(self):
  v=self.root/'models/extra.v';v.write_text('extra');self.invalid(memories=self.memories+[v])
 def test_duplicate_memory(self):self.invalid(memories=self.memories+[self.memories[0]])
 def test_changed_source_bytes(self):
  (self.root/'verilog/unit_0.sv').write_text('altered');self.invalid()
 def test_changed_memory_bytes(self):self.memories[0].write_text('altered');self.invalid()
 def test_reordered_sources_with_recomputed_manifest_root(self):
  c=copy.deepcopy(self.config);c['ordered_events'][2],c['ordered_events'][4]=c['ordered_events'][4],c['ordered_events'][2];c['source_sequence_sha256']=sequence(c['ordered_events']);self.invalid(c)
 def test_reordered_definitions(self):
  c=copy.deepcopy(self.config);c['ordered_events'][0],c['ordered_events'][1]=c['ordered_events'][1],c['ordered_events'][0];self.invalid(c)
 def test_definition_after_source(self):
  c=copy.deepcopy(self.config);c['ordered_events'].append(c['ordered_events'][0]);self.invalid(c)
 def test_definition_injection(self):
  c=copy.deepcopy(self.config);c['ordered_events'][0]['name']='UNIT_DELAY\n`include "bad.sv"';self.invalid(c)
 def test_absolute_source_path(self):
  c=copy.deepcopy(self.config);c['ordered_events'][2]['path']=str(self.root/'verilog/unit_0.sv');self.invalid(c)
 def test_source_path_escape(self):
  c=copy.deepcopy(self.config);c['ordered_events'][2]['path']='verilog/../models/memory_0.v';self.invalid(c)
 def test_source_symlink_escape(self):
  q=self.root/'verilog/unit_0.sv';raw=q.read_bytes();q.unlink();outside=self.root/'outside.sv';outside.write_bytes(raw);q.symlink_to(outside);self.invalid()
 def test_memory_path_injection(self):
  c=copy.deepcopy(self.config);c['ordered_events'][3]['path']='../memory_0.v';self.invalid(c)
 def test_unknown_event_kind(self):
  c=copy.deepcopy(self.config);c['ordered_events'][2]['kind']='unknown';self.invalid(c)
 def test_unknown_event_fields(self):
  c=copy.deepcopy(self.config);c['ordered_events'][2]['extra']='hidden';self.invalid(c)
 def test_bad_digest(self):
  c=copy.deepcopy(self.config);c['ordered_events'][2]['sha256']='invalid';self.invalid(c)
 def test_duplicate_source(self):
  c=copy.deepcopy(self.config);c['ordered_events'][4]=copy.deepcopy(c['ordered_events'][2]);self.invalid(c)
 def test_output_outside_cache(self):self.invalid(output=self.root/'outside')
 def test_cache_root_output(self):self.invalid(output=self.root/'.cache')
 def test_preserve_existing_output(self):
  self.output.mkdir();sentinel=self.output/'preserve';sentinel.write_text('original')
  with self.assertRaises(ValueError):self.prepare()
  self.assertEqual(sentinel.read_text(),'original');self.assertEqual(len(list(self.output.iterdir())),1)
 def test_literal_uses_distinct_frozen_sequence(self):
  self.manifest.write_text(json.dumps(self.config))
  with self.assertRaises(ValueError):m.prepare('literal',self.manifest,self.memories,self.output)
  self.assertFalse(self.output.exists())

if __name__=='__main__':unittest.main()
