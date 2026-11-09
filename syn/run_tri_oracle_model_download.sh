#!/usr/bin/env bash
# Pinned public reference weights; download only, no model loading.
set -euo pipefail
cd /home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator
export HF_HOME="$PWD/.cache/huggingface"
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_XET_CACHE="$HF_HOME/xet"
# Stream through HTTP rather than allocate aggressive parallel Xet buffers.
export HF_HUB_DISABLE_XET=1
export HF_HUB_DISABLE_TELEMETRY=1
repository=bczhou/tiny-llava-v1-hf
revision=70f28eb22f0265a8a41858f6aebc1928cedd53eb
trap 'result=$?; printf "%s\n" "$result" > .cache/model_reference/download_exit_status' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
hf download "$repository" --revision "$revision" \
    --local-dir .cache/model_reference/tiny_llava_v1 --max-workers 2
python3 - <<'PY_VERIFY'
from pathlib import Path
import hashlib,json
record_path=Path('records/model_reference_candidate.json')
record=json.loads(record_path.read_text())
folder=Path('.cache/model_reference/tiny_llava_v1')
verified=[]
for item in record['weight_files']:
    path=folder/item['file']
    if path.stat().st_size!=item['bytes']:raise ValueError('Weight size mismatch: '+str(path))
    checksum=hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda:file.read(1024*1024),b''):checksum.update(block)
    if checksum.hexdigest()!=item['lfs_sha256']:raise ValueError('Weight checksum mismatch: '+str(path))
    verified.append({'path':str(path),'bytes':path.stat().st_size,'sha256':checksum.hexdigest()})
config=folder/'config.json'
if hashlib.sha256(config.read_bytes()).hexdigest()!=record['config_sha256']:
    raise ValueError('Pinned configuration mismatch')
record['weights_downloaded']=True
record['verified_weights']=verified
record['model_executed']=False
record_path.write_text(json.dumps(record,indent=2)+'\n')
print('TRI_ORACLE_MODEL_DOWNLOAD_AND_CHECKSUMS_PASS',flush=True)
PY_VERIFY
