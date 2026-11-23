"""Prepare a verified row-frame source bundle on the host; never start a simulator.

Supply the six local compiler Verilog files with repeated --memory-file options.
The bundle references those files; it never distributes their contents.
"""
from pathlib import Path
import argparse,hashlib,json,re,sys
ROOT=Path(__file__).resolve().parents[1]
FROZEN_SEQUENCES={
 'literal':'edd507350a402e262214b1f3cf634ee2886308c9000aa7c38ad4d146579e62dc',
 'learned':'aface249655cd3325ab2f1898f258ec4e166569607ed6bfccca996a39e374084',
}
SOURCE_COUNTS={'literal':72,'learned':73}
DEFINITIONS=['UNIT_DELAY','TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC']

def digest(raw):return hashlib.sha256(raw).hexdigest()

def prepare(kind,manifest,memory_files,output_directory):
 """Authenticate source order and file bytes before writing an isolated bundle."""
 if Path('/.dockerenv').exists():raise ValueError('Prepare row sources on the host')
 if kind not in FROZEN_SEQUENCES:raise ValueError('Unknown row replay kind')
 output=Path(output_directory).resolve();cache=(ROOT/'.cache').resolve()
 if output==cache or not output.is_relative_to(cache):raise ValueError('Output must be below the project .cache directory')
 if output.exists():raise ValueError('Preserve existing output; choose a new directory')
 raw=Path(manifest).read_bytes();config=json.loads(raw)
 if config.get('version')!=1:raise ValueError('Unsupported row source manifest version')
 events=config['ordered_events']
 if not isinstance(events,list):raise ValueError('Ordered source events must be a list')
 expected_definitions=[dict(kind='define',name=n) for n in DEFINITIONS]
 if events[:2]!=expected_definitions:raise ValueError('Incorrect leading preprocessor definitions')
 supplied={}
 for item in memory_files:
  path=Path(item).resolve(strict=True)
  if path.name in supplied:raise ValueError('Duplicate memory filename: '+path.name)
  supplied[path.name]=path
 sequence=[];inputs={};lines=[];memory_names=set();sources=0
 for i,event in enumerate(events):
  if not isinstance(event,dict):raise ValueError('Source event must be an object')
  if i<2:
   sequence.append(event.copy());lines.append('`define '+event['name']);continue
  if set(event)!={'kind','path','sha256'}:raise ValueError('Unexpected source event fields')
  checksum=event['sha256']
  if not isinstance(checksum,str) or not re.fullmatch('[0-9a-f]{64}',checksum):raise ValueError('Invalid input digest')
  name=event['path']
  if not isinstance(name,str) or any(c in name for c in ['"','\n','\r','\x00']):raise ValueError('Invalid include path')
  if event['kind']=='source':
   relative=Path(name);path=(ROOT/relative).resolve(strict=True)
   if relative.is_absolute() or not path.is_relative_to((ROOT/'verilog').resolve()):raise ValueError('Source must remain inside repository Verilog')
   sources+=1
  elif event['kind']=='memory':
   if Path(name).name!=name or name not in supplied:raise ValueError('Missing or invalid external memory filename: '+name)
   if name in memory_names:raise ValueError('Duplicate memory source event')
   memory_names.add(name);path=supplied[name]
  else:raise ValueError('Unknown source event kind')
  if str(path) in inputs:raise ValueError('Repeated source input')
  if digest(path.read_bytes())!=checksum:raise ValueError('Changed source bytes: '+name)
  inputs[str(path)]=checksum
  sequence.append(dict(kind=event['kind'],sha256=checksum))
  lines.append('`include '+json.dumps(str(path)))
 fingerprint=digest(json.dumps(sequence,sort_keys=True,separators=(',',':')).encode())
 if fingerprint!=config['source_sequence_sha256'] or fingerprint!=FROZEN_SEQUENCES[kind]:raise ValueError('Source order differs from the frozen native design')
 if sources!=SOURCE_COUNTS[kind] or len(memory_names)!=6 or set(supplied)!=memory_names:raise ValueError('Incorrect source or external memory count')
 bundle=('\n'.join(lines)+'\n').encode()
 receipt=dict(state='row_source_bundle_prepared_not_native_execution_proof',kind=kind,
  manifest_sha256=digest(raw),bundle_sha256=digest(bundle),source_sequence_sha256=fingerprint,
  ordered_inputs=len(inputs),repository_sources=sources,external_memory_models=len(memory_names),
  input_sha256=inputs,vendor_memory_contents_copied=False,native_execution_verified=False,paper_matching=False)
 output.mkdir(parents=True,exist_ok=False)
 (output/'bundle.sv').write_bytes(bundle)
 (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
 return receipt

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--kind',choices=sorted(FROZEN_SEQUENCES),default='learned')
 parser.add_argument('--manifest',type=Path)
 parser.add_argument('--memory-file',type=Path,action='append',default=[])
 parser.add_argument('--output-directory',type=Path,required=True)
 args=parser.parse_args()
 manifest=args.manifest or ROOT/('syn/tri_oracle_row_'+args.kind+'_sources.json')
 try:receipt=prepare(args.kind,manifest,args.memory_file,args.output_directory)
 except (ValueError,OSError,KeyError,TypeError) as error:
  print('error: '+str(error),file=sys.stderr);return 1
 print(json.dumps({k:receipt[k] for k in ['state','kind','repository_sources','external_memory_models']},indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
