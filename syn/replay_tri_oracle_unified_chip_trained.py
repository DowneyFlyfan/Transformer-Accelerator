"""Verify the full trained frame through chip commands and the packed weight image."""

import argparse
from hashlib import sha256 as digest_bytes
import json
from pathlib import Path
import re
import shutil
import time

from prepare_tri_oracle_packed_tensor import rewrite
from verify_tri_oracle_packed_down_weights import ROOT, sha256


MODEL = ROOT / ".cache/model_reference/packed_down_export/v1"
BASE = ROOT / ".cache/physical/wide_weight_loader"
CHIP = BASE / "unified_chip"
DECODER = BASE / "unified_decoder"
OUTPUT = CHIP / "image_trained"


def verify(pins):
    assert all(sha256(ROOT / path) == digest for path, digest in pins.items())


def image_bench(source):
    return rewrite(source, (
        ("  logic [511:0] wide_rsp_data;\n", """  logic [511:0] wide_rsp_data;
  byte unsigned packed_weights[OUTPUTS*INTERMEDIATE];
"""),
        ("      for(int row=0;row<8;row++)\n", """      if(TRAINED)begin
        for(int lane=0;lane<64;lane++)wide_rsp_data[lane*8+:8]=packed_weights[offset+lane];
      end else for(int row=0;row<8;row++)
"""),
        ("  initial begin: stimulus\n", """  initial begin: stimulus
    string image;
    integer image_file,image_bytes;
    logic [511:0] first_response,last_response;
"""),
        ("    if(TRAINED)begin\n      if(!$value$plusargs(\"FIXTURE=%s\",fixture)", """    if(TRAINED)begin
      if(!PACKED || !$value$plusargs("PACKED_IMAGE=%s",image))$fatal(1,"UNIFIED_CHIP_WEIGHT_IMAGE_REQUIRED");
      image_file=$fopen(image,"rb");
      if(!image_file)$fatal(1,"UNIFIED_CHIP_WEIGHT_IMAGE_OPEN");
      image_bytes=$fread(packed_weights,image_file,0,OUTPUTS*INTERMEDIATE);
      $fclose(image_file);
      if(image_bytes!=OUTPUTS*INTERMEDIATE)$fatal(1,"UNIFIED_CHIP_WEIGHT_IMAGE_SHORT");
      $display("UNIFIED_CHIP_WEIGHT_IMAGE bytes=%0d offset=0",image_bytes);
      if($test$plusargs("PACKED_IMAGE_SMOKE"))begin
        if(!$value$plusargs("FIRST=%h",first_response) || !$value$plusargs("LAST=%h",last_response))
          $fatal(1,"UNIFIED_CHIP_WEIGHT_IMAGE_CHECK_VALUES");
        for(int lane=0;lane<64;lane++)
          if(packed_weights[lane]!==first_response[lane*8+:8] ||
             packed_weights[image_bytes-64+lane]!==last_response[lane*8+:8])
            $fatal(1,"UNIFIED_CHIP_WEIGHT_IMAGE_LANE_ORDER lane=%0d",lane);
        $display("UNIFIED_CHIP_WEIGHT_IMAGE_SMOKE_PASS boundary_beats=2");
        $finish;
      end
      if(!$value$plusargs("FIXTURE=%s",fixture)"""),
    ))


def prepare():
    manifest = MODEL / "manifest.json"
    image = MODEL / "weights.bin"
    model = json.loads(manifest.read_text())
    assert model["state"] == "packed_checkpoint_down_weights_cpu_cuda_exact_for_all_language_layers"
    assert len(model["layers"]) == 22 and model["layer_zero_matches_hardware_fixture"]
    assert (model["rows_per_layer"], model["features_per_row"], model["bytes_per_response"]) == (2048, 5632, 64)
    assert model["weights_sha256"] == sha256(image)
    layer = model["layers"][0]
    assert layer["layer"] == layer["offset_bytes"] == 0 and layer["bytes"] == 2048 * 5632
    with image.open("rb") as source:
        assert digest_bytes(source.read(layer["bytes"])).hexdigest() == layer["sha256"]

    candidate = CHIP / "prepared.json"
    prepared = json.loads(candidate.read_text())
    assert prepared["state"] == "unified_read_decoder_connected_to_mapped_chip_commands"
    pins = prepared["input_sha256"]
    verify(pins)
    original = CHIP / "trained_tb.sv"
    code = image_bench(original.read_text())
    OUTPUT.mkdir()
    bench = OUTPUT / "trained_tb.sv"
    bundle = OUTPUT / "bundle.sv"
    bench.write_text(code)
    bundle.write_text(rewrite((CHIP / "bundle.sv").read_text(), (
        (f'`include "{original}"', f'`include "{bench}"'),
    )))
    for path in (manifest, image, candidate, bench, bundle, Path(__file__)):
        pins[str(path.relative_to(ROOT))] = sha256(path)
    record = {
        "state": "unified_chip_trained_weight_image_fixture_prepared",
        "image_layer": 0, "image_layer_bytes": layer["bytes"], "image_layer_sha256": layer["sha256"],
        "controller_sha256": prepared["controller_sha256"], "input_sha256": pins,
    }
    (OUTPUT / "prepared.json").write_text(json.dumps(record, indent=2) + "\n")


def process_identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except FileNotFoundError:
        return None
    return None if fields[0] == "Z" else fields[19]


def wait_for_proof(proof, pid, script):
    if proof.exists():
        return
    began = process_identity(pid)
    command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    assert began and any(arg.endswith(("/" + script).encode()) for arg in command)
    deadline = time.monotonic() + 16 * 3600
    print("Waiting for", proof, "from", pid, flush=True)
    while process_identity(pid) == began:
        assert time.monotonic() < deadline
        time.sleep(5)
    assert proof.is_file(), proof


def run(chip_pid, decoder_pid):
    import replay_fully_mapped_layer as native
    from run_linked_trained_replay import BENCH, PARAMETERS, archived_inputs, verify_trained

    prepared = OUTPUT / "prepared.json"
    setup = json.loads(prepared.read_text())
    assert setup["state"] == "unified_chip_trained_weight_image_fixture_prepared"
    pins = setup["input_sha256"]
    attention = CHIP / "full_native/attention_receipt.json"
    trained = DECODER / "full_native/trained_receipt.json"
    for path, pid, script, state in (
        (attention, chip_pid, "run_attention.py", "mapped_chip_commands_preserved_unified_decoder_context_attention"),
        (trained, decoder_pid, "run_trained.py", "packed_context_decoder_replayed_exact_full_width_trained_feedforward"),
    ):
        wait_for_proof(path, pid, script)
        proof = json.loads(path.read_text())
        assert proof["state"] == state and proof["native"]["native_exit_status"] == 0
        verify(proof["input_sha256"])
        pins[str(path.relative_to(ROOT))] = sha256(path)
    archive, archived_pins, fixture_args = archived_inputs()
    for path, digest in archived_pins.items():
        key = str(Path(path).relative_to(ROOT))
        assert pins.setdefault(key, digest) == digest

    progress = OUTPUT / "simulation/progress.log"
    cmd = [
        "/opt/cadence/bin/xrun", "-64bit", "-sv", "-nospecify", "-notimingchecks",
        "-sequdp_nba_delay", "-xmerror", "RECOME", "-top", BENCH,
    ]
    for parameter, value in PARAMETERS.items():
        cmd.extend(("-defparam", f"{BENCH}.{parameter}={value}"))
    cmd.extend((str(OUTPUT / "bundle.sv"), f"+PROGRESS={progress}", f"+PACKED_IMAGE={MODEL/'weights.bin'}", *fixture_args))
    invocation = OUTPUT / "invocation.json"
    invocation.write_text(json.dumps({"argv": cmd}, indent=2) + "\n")
    for path in (prepared, invocation):
        pins[str(path.relative_to(ROOT))] = sha256(path)
    verify(pins)
    native.OUTPUT = OUTPUT
    try:
        log, stage = native.stage("simulation", cmd, 16.5, 13, 4, 21600)
        counters = verify_trained(log, progress, archive)
        assert counters["exact_outputs"] == 32768
        text = log.read_text()
        markers = (
            f'UNIFIED_CHIP_WEIGHT_IMAGE bytes={setup["image_layer_bytes"]} offset=0',
            "UNIFIED_CHIP_FEEDFORWARD_RESPONSE tag=39300001 error=0",
            "UNIFIED_CHIP_FEEDFORWARD_PASS descriptor_words=15 commands=1 responses=1",
        )
        assert all(text.splitlines().count(marker) == 1 for marker in markers)
        direct = json.loads(trained.read_text())
        assert counters == direct["counters"]
        assert progress.read_bytes() == (trained.parent / "trained/progress.log").read_bytes()
        verify(pins)
        for path in (log, progress):
            pins[str(path.relative_to(ROOT))] = sha256(path)
        result = {
            "state": "mapped_chip_commands_replayed_exact_trained_frame_from_packed_weight_image",
            "controller_sha256": setup["controller_sha256"], "native": stage,
            "image_layer_sha256": setup["image_layer_sha256"], "counters": counters,
            "markers": markers, "input_sha256": pins,
        }
        (OUTPUT / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
        print("UNIFIED_CHIP_PACKED_IMAGE_TRAINED_PASS", counters["exact_outputs"], flush=True)
    finally:
        snapshot = OUTPUT / "simulation/xcelium.d"
        if snapshot.is_dir():
            shutil.rmtree(snapshot)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("pids", nargs="*", type=int)
    args = parser.parse_args()
    if args.action == "prepare":
        assert not args.pids
        prepare()
    else:
        run(*args.pids)
