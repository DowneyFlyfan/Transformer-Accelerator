"""Replay archived attention and a trained layer through both chip weight ports."""

import argparse
import json
from pathlib import Path
import re
import shutil

from prepare_tri_oracle_packed_tensor import rewrite
from verify_tri_oracle_packed_down_weights import ROOT, sha256


BASE = ROOT / ".cache/physical/wide_weight_loader"
MODELS = ROOT / ".cache/model_reference"
ATTENTION_FIXTURE = ROOT / ".cache/physical/shared437/fixture"
XRUN = ("/opt/cadence/bin/xrun", "-64bit", "-sv", "-nospecify",
        "-notimingchecks", "-sequdp_nba_delay", "-xmerror", "RECOME")


def read(path):
    return json.loads(path.read_text())


def verify(pins):
    for name, expected in pins.items():
        assert sha256(ROOT / name) == expected, name


def pin(pins, *paths):
    for path in paths:
        name = str(path.relative_to(ROOT))
        expected = sha256(path)
        assert pins.setdefault(name, expected) == expected, name


def record(output, filename, result, pins, *files):
    verify(pins)
    all_pins = pins.copy()
    pin(all_pins, *files)
    (output / filename).write_text(json.dumps({**result, "input_sha256": all_pins}, indent=2) + "\n")


def replay_attention(trial, output, pins, stage):
    archive = BASE / "unified_chip/full_native/attention_receipt.json"
    archive_data = read(archive)
    prior = BASE / "paired_chip/full_native/attention_receipt.json"
    previous = read(prior)
    assert previous["state"] == "paired_chip_preserved_archived_attention"
    assert previous["native"]["native_exit_status"] == 0
    pin(pins, archive, prior)
    for path in ATTENTION_FIXTURE.iterdir():
        name = str(path.relative_to(ROOT))
        assert sha256(path) == archive_data["input_sha256"][name] == previous["input_sha256"][name]
        pin(pins, path)
    top = "tri_oracle_attention430_tb"
    cmd = [*XRUN, "-top", top, "-defparam", f"{top}.INTEGRATE=1", str(trial / "bundle.sv"),
           f"+FIXTURE={ATTENTION_FIXTURE}", f"+DUMP={output/'unused.hex'}"]
    log, result = stage("attention", cmd, 16, 13, 4, 1800)
    text = log.read_text()
    assert all(text.splitlines().count(marker) == 1 for marker in archive_data["markers"])
    fields, = re.findall(r"(?m)^COMPOSE430_PASS (.*)$", text)
    counters = {name: int(value) for name, value in (item.split("=") for item in fields.split())}
    assert counters == previous["counters"]
    assert text.count("Simulation complete via $finish(1)") == 1
    record(output, "attention_receipt.json", {
        "state": "parallel_chip_preserved_archived_attention", "native": result, "counters": counters,
    }, pins, log)
    print("PARALLEL_CHIP_ARCHIVED_ATTENTION_PASS", counters, flush=True)


def image_bench(source):
    return rewrite(source, (
        ("  logic [1:0][511:0] wide_rsp_data;\n", """  logic [1:0][511:0] wide_rsp_data;
  byte unsigned packed_down[OUTPUTS*INTERMEDIATE];
  byte unsigned packed_pair[2*INTERMEDIATE*HIDDEN];
"""),
        ("      for(int row=0;row<8;row++)\n", """      if(TRAINED)begin
        for(int byte_index=0;byte_index<64;byte_index++)
          wide_rsp_data[lane][byte_index*8+:8]=branch==2 ? packed_down[offset+byte_index] :
            packed_pair[(branch==1 ? INTERMEDIATE*HIDDEN : 0)+offset+byte_index];
      end else for(int row=0;row<8;row++)
"""),
        ("  initial begin: stimulus\n", """  initial begin: stimulus
    string down_image,pair_image;
    integer image_file,image_bytes;
"""),
        ('    if(TRAINED)begin\n      if(!$value$plusargs("FIXTURE=%s",fixture)', """    if(TRAINED)begin
      if(!PACKED || !$value$plusargs("PACKED_IMAGE=%s",down_image) ||
          !$value$plusargs("PAIR_IMAGE=%s",pair_image))$fatal(1,"PARALLEL_CHIP_IMAGE_REQUIRED");
      image_file=$fopen(down_image,"rb");
      if(!image_file)$fatal(1,"PARALLEL_CHIP_DOWN_IMAGE_OPEN");
      image_bytes=$fread(packed_down,image_file,0,OUTPUTS*INTERMEDIATE);
      $fclose(image_file);
      if(image_bytes!=OUTPUTS*INTERMEDIATE)$fatal(1,"PARALLEL_CHIP_DOWN_IMAGE_SHORT");
      $display("PARALLEL_CHIP_DOWN_IMAGE bytes=%0d",image_bytes);
      image_file=$fopen(pair_image,"rb");
      if(!image_file)$fatal(1,"PARALLEL_CHIP_PAIR_IMAGE_OPEN");
      image_bytes=$fread(packed_pair,image_file,0,2*INTERMEDIATE*HIDDEN);
      $fclose(image_file);
      if(image_bytes!=2*INTERMEDIATE*HIDDEN)$fatal(1,"PARALLEL_CHIP_PAIR_IMAGE_SHORT");
      $display("PARALLEL_CHIP_PAIR_IMAGE bytes=%0d",image_bytes);
      if(!$value$plusargs("FIXTURE=%s",fixture)"""),
    ))


def replay_trained(trial, output, pins, stage):
    from run_linked_trained_replay import BENCH, PARAMETERS, archived_inputs, verify_trained

    archive, trained_pins, fixture_args = archived_inputs()
    for path, expected in trained_pins.items():
        name = str(Path(path).relative_to(ROOT))
        assert pins.setdefault(name, expected) == expected
    images = []
    for name, state in (
        ("down", "packed_checkpoint_down_weights_cpu_cuda_exact_for_all_language_layers"),
        ("gate_up", "packed_checkpoint_gate_up_weights_cpu_cuda_exact_for_all_language_layers"),
    ):
        manifest = MODELS / f"packed_{name}_export/v1/manifest.json"
        image = manifest.with_name("weights.bin")
        data = read(manifest)
        assert data["state"] == state and data["weights_sha256"] == sha256(image)
        pin(pins, manifest, image)
        images.append(image)
    original = trial / "trained_tb.sv"
    test = output / "trained_tb.sv"
    bundle = output / "trained_bundle.sv"
    test.write_text(image_bench(original.read_text()))
    bundle.write_text(rewrite((trial / "bundle.sv").read_text(), (
        (f'`include "{original}"', f'`include "{test}"'),
    )))
    progress = output / "trained/progress.log"
    cmd = [*XRUN, "-top", BENCH]
    for parameter, value in PARAMETERS.items():
        cmd.extend(("-defparam", f"{BENCH}.{parameter}={value}"))
    cmd.extend((str(bundle), f"+PROGRESS={progress}", f"+PACKED_IMAGE={images[0]}",
                f"+PAIR_IMAGE={images[1]}", *fixture_args))
    invocation = output / "trained_invocation.json"
    invocation.write_text(json.dumps({"argv": cmd}, indent=2) + "\n")
    verify(pins)
    log, result = stage("trained", cmd, 16.5, 13, 4, 21600)
    counters = verify_trained(log, progress, archive)
    text = log.read_text()
    for marker in ("PARALLEL_CHIP_DOWN_IMAGE bytes=11534336", "PARALLEL_CHIP_PAIR_IMAGE bytes=23068672",
                   "UNIFIED_CHIP_FEEDFORWARD_RESPONSE tag=39300001 error=0",
                   "UNIFIED_CHIP_FEEDFORWARD_PASS descriptor_words=15 commands=1 responses=1"):
        assert text.splitlines().count(marker) == 1, marker
    lanes = re.findall(r"(?m)^PARALLEL_CHIP_BRANCHES lane=([01]) gate=(\d+) up=(\d+) down=(\d+)$", text)
    assert [int(lane[0]) for lane in lanes] == [0, 1]
    assert all(int(value) > 0 for lane in lanes for value in lane[1:])
    overlap, = re.findall(r"(?m)^PARALLEL_CHIP_READS simultaneous_responses=(\d+)$", text)
    cycles, = re.findall(r"(?m)^PACKED_DECODER_PASS .* cycles=(\d+)$", text)
    assert int(overlap) > 0 and counters["exact_outputs"] == 32768
    record(output, "trained_receipt.json", {
        "state": "parallel_chip_replayed_exact_trained_frame_from_both_packed_images",
        "native": result, "counters": counters, "simulated_cycles": int(cycles),
        "simultaneous_responses": int(overlap),
        "responses_by_lane": [dict(zip(("gate", "up", "down"), map(int, lane[1:]), strict=True)) for lane in lanes],
    }, pins, test, bundle, invocation, log, progress)
    print("PARALLEL_CHIP_TRAINED_FRAME_PASS", counters["exact_outputs"], cycles, overlap, flush=True)


def run(trial):
    import replay_fully_mapped_layer as native

    prepared = trial / "prepared.json"
    setup = read(prepared)
    assert setup["state"] == "source_chip_connects_two_packed_read_lanes_to_compiled_clusters"
    pins = setup["input_sha256"]
    pin(pins, prepared, Path(__file__).resolve())
    for label in ("packed", "scalar", "gate_fault_lane0", "gate_fault_lane1", "tail_fault"):
        run_dir = trial / "native" / label
        status, log = run_dir / "exit_status", run_dir / "console.log"
        assert int(status.read_text()) == 0 and re.search(r"(?m)^BATCH408_PASS .* exact_outputs=504 ", log.read_text())
        pin(pins, status, log)
    verify(pins)
    output = trial / "full_native"
    output.mkdir()
    native.OUTPUT = output
    try:
        replay_attention(trial, output, pins, native.stage)
        replay_trained(trial, output, pins, native.stage)
    finally:
        for stage in ("attention", "trained"):
            snapshot = output / stage / "xcelium.d"
            if snapshot.is_dir():
                shutil.rmtree(snapshot)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    run(parser.parse_args().candidate.resolve())
