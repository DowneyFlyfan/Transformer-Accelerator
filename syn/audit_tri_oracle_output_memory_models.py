"""Recheck archived native model compatibility and its numerical reference.

This audit does not execute the archived command strings or start a chip tool.
Its finite results are not universal foundry-model or current-chip proofs.
"""
if not __debug__:raise RuntimeError('Archive audit requires assertions')
from pathlib import Path
from hashlib import file_digest,sha256
import json,os,re,resource,sys,time


ARCHIVE_SHA256='696e3be11bbc0b4c182f3eb29ec2c79887a89652487802eb30e5c7b0be82c6e2'
PASS='GPU_CORE_CAPACITY_PASS commands=1024 sums=512 input_addresses=1024'


def validate_native_outcome(record,log):
    required=dict(state='passed',simulator='Cadence Xcelium',profile='capacity',implementation='routed44',
        elaborate_only=False,smoke_only=False,functional_simulation_completed=True,exit_status=0,
        raw_routed_clock_connections_preserved=True)
    assert all(record.get(key)==value and type(record.get(key)) is type(value) for key,value in required.items()),'Invalid archive native outcome'
    negative=record['negative_reference'];assert type(negative) is bool,'Invalid archive native mode'
    if negative:
        assert record['native_exit_status']==2 and record['wrong_reference_rejected'] is True,'Invalid archive native rejection'
        assert PASS not in log and len(re.findall(r'(?m)^GPU_CORE_REFERENCE_MISMATCH slot=0$',log))==1,'Wrong archive native failure'
        assert log.count('xmsim: *F,FATSEV')==1 and 'Simulation terminated via $fatal(1)' in log,'Missing archive native fatal'
    else:
        assert record['native_exit_status']==0 and record['wrong_reference_rejected'] is False,'Invalid archive native success'
        assert log.splitlines().count(PASS)==1 and 'Simulation complete via $finish(1)' in log,'Missing archive native completion'
        assert not re.search(r'(?m)^(?:xrun|xmelab|xmvlog|xmsim):\s+\*[EF],',log),'Unexpected archive native error'


def scalar_commands(weights,activations,masks,commands,*,rows=32,lanes=8,slots=16):
    """Independent scalar signed-byte/mask arithmetic, with modulo32 commits.

    Packed integer inputs come from hexadecimal fixture words: weights has
    [weight_word], each with[rows,lanes,8bits]; activations[activation_word]
    packs[lanes,8bits]; masks[mask_word] packs[rows,lanes]. Commands[command]
    supplies(weight_index,activation_index,mask_index,slot,accumulate).
    Outputs are[slot,row] bit patterns and[command,row] signed dot products.
    """
    result=[[0]*rows for _ in range(slots)];dots=[]
    def signed(value):return (value^128)-128
    for weight,activation,mask,slot,accumulate in commands:
        row_values=[]
        for row in range(rows):
            total=0
            for lane in range(lanes):
                if masks[mask]>>(row*lanes+lane)&1:
                    a=signed(activations[activation]>>(8*lane)&255)
                    b=signed(weights[weight]>>(8*(row*lanes+lane))&255)
                    total+=a*b
            row_values.append(total)
            result[slot][row]=(total+(result[slot][row] if accumulate else 0))&0xffffffff
        dots.append(row_values)
    return result,dots


def cuda_commands(weights,activations,masks,commands):
    """Exact integer GPU oracle; no model, learned parameter, loss or optimizer.

    Inputs packed Python words/commands have the same sources/shapes described
    by scalar_commands. This independently decodes sign on the GPU, multiplies
    selected words and reduces integer products. First16commands initialize
    distinct slots, then all remaining commands accumulate. All GPU tensors
    use int64; even the conservative1024*8*16384bound fits signed32, so exact
    integer index-add order cannot affect the answer. CPU threads are capped1.
    """
    import torch
    from prove_tri_oracle_packaged_products import memory_guard
    memory_guard(10);torch.set_num_threads(1);torch.set_num_interop_threads(1)
    assert torch.cuda.is_available(),'CUDA unavailable for independent archive oracle'
    assert torch.cuda.mem_get_info()[0]>512*2**20,'Insufficient free GPU memory'
    torch.cuda.set_per_process_memory_fraction(.1);torch.cuda.reset_peak_memory_stats()
    assert len(weights)==len(masks)==32 and len(activations)==len(commands)==1024
    assert all(command[3]==index and not command[4] for index,command in enumerate(commands[:16]))
    assert all(command[4] for command in commands[16:])
    # Fixture byte extraction, CPU initialized lists:[32weightwords,32rows,8lanes].
    raw_weights=[[[word>>(8*(row*8+lane))&255 for lane in range(8)] for row in range(32)] for word in weights]
    # Fixture bytes:[1024activationwords,8lanes]; mask bits:[32maskwords,32rows,8lanes].
    raw_inputs=[[word>>(8*lane)&255 for lane in range(8)] for word in activations]
    raw_masks=[[[word>>(row*8+lane)&1 for lane in range(8)] for row in range(32)] for word in masks]
    # CPU lists->CUDA int64; decoded weights[32weightwords,32rows,8lanes].
    weight_values=(torch.tensor(raw_weights,dtype=torch.int64,device='cuda')^128)-128
    # Decoded activations[1024activationwords,8lanes], masks[32maskwords,32rows,8lanes].
    input_values=(torch.tensor(raw_inputs,dtype=torch.int64,device='cuda')^128)-128
    mask_values=torch.tensor(raw_masks,dtype=torch.int64,device='cuda')
    # Command fields->CUDA indices[1024commands], each selecting fixture words or output slots.
    weight_ids=torch.tensor([command[0] for command in commands],dtype=torch.int64,device='cuda')
    activation_ids=torch.tensor([command[1] for command in commands],dtype=torch.int64,device='cuda')
    mask_ids=torch.tensor([command[2] for command in commands],dtype=torch.int64,device='cuda')
    slot_ids=torch.tensor([command[3] for command in commands],dtype=torch.int64,device='cuda')
    # Indexed weights/masks:[1024commands,32rows,8lanes]; inputs broadcast[1024commands,1,8lanes].
    products=weight_values[weight_ids]*input_values[activation_ids,None,:]*mask_values[mask_ids]
    # Lane reduction yields signed dot products[1024commands,32rows].
    dots=products.sum(dim=2,dtype=torch.int64)
    # Initial command rows map1:1to16slots; later command dots accumulate by slot.
    result=dots[:16].clone() # [16slots,32rows], int64 initialization from first16dots.
    result.index_add_(0,slot_ids[16:],dots[16:])
    torch.cuda.synchronize();memory_guard(8.5)
    # CUDA->CPU lists preserve[1024commands,32rows] and[16slots,32rows].
    dot_rows=dots.cpu().tolist();result_rows=[[value&0xffffffff for value in row] for row in result.cpu().tolist()]
    metadata=dict(device=torch.cuda.get_device_name(0),peak_allocated_bytes=torch.cuda.max_memory_allocated(),
        peak_reserved_bytes=torch.cuda.max_memory_reserved(),torch_version=torch.__version__)
    return result_rows,dot_rows,metadata


def verify(output,*,gpu=True):
    from prove_tri_oracle_packaged_products import ROOT,memory_guard
    from prove_tri_oracle_packaged_accumulators import local_source_paths
    from prove_tri_oracle_head_score_frontend import revalidate_evidence
    assert not Path('/.dockerenv').exists() and output.resolve().is_relative_to((ROOT/'.cache').resolve()) and not output.exists()
    memory_guard(10);start=time.monotonic();pins={}
    def pin(path,wanted=None):
        path=path.resolve();assert path.is_relative_to(ROOT),'Archive source outside project'
        with path.open('rb') as stream:actual=file_digest(stream,'sha256').hexdigest()
        assert wanted is None or actual==wanted,('Changed archive source',path)
        assert pins.setdefault(str(path.relative_to(ROOT)),actual)==actual
        return path
    root=pin(ROOT/'records/sram_core_typical44_xcelium_raw_clock_qualification.json',ARCHIVE_SHA256)
    qualification=json.loads(root.read_text());assert qualification['state']=='passed' and qualification['commands_per_corner']==1024 and qualification['gpu_reference_sums_per_corner']==512
    cases=[];tools=set();model_paths=set()
    for label,row in qualification['records'].items():
        record=json.loads(pin(ROOT/row['record'],row['record_sha256']).read_text())
        log=pin(ROOT/'records'/f'{label}_native.log',row['native_log_sha256']).read_text()
        assert row['native_log_sha256']==record['native_log_sha256']
        validate_native_outcome(record,log)
        bundle=record['compiled_bundle'];assert sha256(bundle.encode()).hexdigest()==record['compiled_bundle_sha256']
        assert bundle.startswith('`define UNIT_DELAY\n') and '`undef UNIT_DELAY' not in bundle
        command=record['command'];assert command[0]=='/opt/cadence/bin/xrun' and '-top' in command and 'tri_oracle_sram_gpu_capacity_tb' in command
        assert ('+CORRUPT_REFERENCE' in command)==record['negative_reference']
        sources={}
        for name,wanted in record['source_sha256'].items():
            if name=='/opt/cadence/bin/xrun':tools.add(wanted);continue
            path=pin(Path(name) if Path(name).is_absolute() else ROOT/name,wanted);sources[path]=wanted
        for name in re.findall(r'(?m)^`include "([^"]+)"$',bundle):assert Path(name).resolve() in sources,'Unpinned archive compilation source'
        model,=(path for path in sources if path.name==f'ts6n28hpcpsvta16x128m2f_130a_{record["corner"]}.v')
        model_paths.add(str(model.relative_to(ROOT)))
        cases.append(dict(corner=record['corner'],negative_reference=record['negative_reference'],
            native_exit_status=record['native_exit_status'],model_sha256=sources[model],log_sha256=row['native_log_sha256']))
    assert len(cases)==4 and {c['corner'] for c in cases if not c['negative_reference']}=={'tt1v25c','ssg0p9v125c','ffg1p05vm40c'}
    assert sum(c['negative_reference'] for c in cases)==1 and len(tools)==1
    # Bind the exact TTmodel and functional mode to frozen current elaboration inputs.
    runtime=pin(ROOT/'.cache/wide_packaged_host_link/trained_current_multicore/prefix_check/full_serialized/elaboration_runtime.json',
        'b3b48d38869df5593615b4b05050bbcbc78e0889d2cb1c27cd8f3fd9e0216da2')
    frozen=json.loads(runtime.read_text());tt,=(name for name in model_paths if name.endswith('_tt1v25c.v'))
    assert frozen['evidence_sha256'][tt]==pins[tt]
    bundle_name='.cache/wide_packaged_host_link/trained_current_multicore/bundle.sv'
    current_bundle=pin(ROOT/bundle_name,frozen['evidence_sha256'][bundle_name]).read_text()
    assert re.search(r'(?m)^`define\s+UNIT_DELAY\s*$',current_bundle) and not re.search(r'(?m)^`undef\s+UNIT_DELAY',current_bundle)
    fixture=ROOT/'.cache/model_reference/sram_capacity_gpu'
    def words(name,count,digits):
        raw=pin(fixture/name).read_text().split();assert len(raw)==count and all(re.fullmatch('[0-9a-fA-F]{'+str(digits)+'}',word) for word in raw)
        return [int(word,16) for word in raw]
    weights=words('weights.hex',32,512);activations=words('inputs.hex',1024,16);masks=words('masks.hex',32,64);expected=words('expected.hex',16,256)
    commands=[((index*5+3)%32,index,(index*13+7)%32,index%16 if index<992 else 3,index>=16) for index in range(1024)]
    cpu,dots=scalar_commands(weights,activations,masks,commands)
    wanted=[[(word>>(32*row))&0xffffffff for row in range(32)] for word in expected]
    assert cpu==wanted,'Scalar archive reference differs'
    device=None
    if gpu:
        for key,directory in (('TORCH_HOME','torch'),('TORCH_EXTENSIONS_DIR','torch_extensions'),('CUDA_CACHE_PATH','cuda')):
            path=ROOT/'.cache'/directory;path.mkdir(exist_ok=True);os.environ[key]=str(path)
        native,gpu_dots,device=cuda_commands(weights,activations,masks,commands)
        assert native==cpu==wanted and gpu_dots==dots,'Independent CUDA archive reference differs'
    sources=local_source_paths((Path(__file__).resolve(),ROOT/'syn/test_tri_oracle_output_memory_service_logic.py'),ROOT/'syn')
    for path in sources:pin(path)
    revalidate_evidence(pins,ROOT)
    result=dict(state='archived_output_model_compatibility_and_integer_reference_rechecked',cases=cases,
        archived_positive_commands=3072,archived_positive_output_words=1536,archived_reference_faults_rejected=1,
        current_tt_compiler_model_matches_archive=True,current_functional_mode_matches_archive=True,
        scalar_output_words_recomputed=512,cuda_dot_products_recomputed=32768 if gpu else 0,cuda_output_words_recomputed=512 if gpu else 0,
        device=device,archived_tool_wrapper_sha256=next(iter(tools)),tool_wrapper_current_host_check_performed=False,
        evidence_sha256=pins,elapsed_seconds=time.monotonic()-start,peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        fresh_chip_simulation_executed=False,current_candidate_functionally_qualified=False,
        universal_compiler_memory_contract_verified=False,physical_timing_verified=False,paper_results_matched=False,
        scope='Archived routed44Xcelium finite compatibility cases only, with current model/fixture bytes rehashed and numerical reference independently recomputed. Same TTcompiler-model bytes and UNIT_DELAY mode are bound to current frozen elaboration. No new native job, no current-candidate execution qualification, and no universal vendor timing/unknown-state proof.')
    with output.open('x') as stream:stream.write(json.dumps(result,indent=2)+'\n')
    print(result['state'],result['scalar_output_words_recomputed'],result['cuda_output_words_recomputed'],result['elapsed_seconds'],flush=True)
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);parser.add_argument('--cpu-only',action='store_true')
    args=parser.parse_args();verify(args.output,gpu=not args.cpu_only)
