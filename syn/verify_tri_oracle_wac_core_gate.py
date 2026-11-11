"""Replay compute, softmax and outlier decisions with real core memory models."""

import argparse
import json
from pathlib import Path
import re
import tempfile

from prepare_tri_oracle_wac_outlier_layer import ROOT, RTL, edit, read, sha, verify
from replay_mapped_cluster_fixture import shared_memory_stage, wait_for_shared_memory
from run_tri_oracle_wac_shared_imem import BENCH, MACROS, SUCCESS

TOP = "tri_oracle_sram_memory_compute"
OUTLIERS = "WAC_GATE_OUTLIER_PASS codes=8"


def bench(source):
    source = edit(source, "    tri_oracle_wac_compute_softmax dut (.*);", f"""    logic outlier_valid = 0, outlier_response_valid;
    logic [127:0] metadata_values = '0;
    logic [7:0] outliers, negative;
    {TOP} dut (.*);""")
    return edit(source, "        softmax_in_valid = 0;\n        // Result reads", f"""        softmax_in_valid = 0;
        metadata_values = {{16'sd32767, 16'sh8000, -16'sd768, -16'sd769,
                            16'sd768, 16'sd769, -16'sd1, 16'sd0}};
        outlier_valid = 1;
        #2;
        if (outlier_response_valid !== 1'b1 || outliers !== 8'hd4 || negative !== 8'h72)
            $fatal(1, "WAC_GATE_OUTLIER_METADATA");
        outlier_valid = 0;
        #1;
        if ({{outlier_response_valid, outliers, negative}} !== '0) $fatal(1, "WAC_GATE_OUTLIER_IDLE");
        $display("{OUTLIERS}");
        // Result reads""")


def witness():
    return """module tri_oracle_gate_memory_witness #(parameter string MASTER="") ();
    initial $display("WAC_GATE_MEMORY %s %m", MASTER);
endmodule
""" + "".join(f'bind {master} tri_oracle_gate_memory_witness #(.MASTER("{master}")) gate_witness ();\n'
             for master in dict.fromkeys(master for master, _, _ in MACROS))


def run(case, output, mapped):
    preparation = case / "receipt.json"
    setup = read(preparation)
    assert setup["outlier_owner"] == "core_simd_round_robin"
    inputs = setup["input_sha256"].copy()
    verify(inputs)
    model_files = [Path(name) for name in setup["memory_model_paths"]]
    for master, _, _ in MACROS:
        assert any(master.lower().removesuffix("fw").removesuffix("f") in path.name for path in model_files)
    cells = ROOT / ".cache/physical/library/tcbn28hpcplusbwp12t40p140.v"
    if mapped:
        receipt = mapped / "receipt.json"
        mapping = read(receipt)
        assert mapping["state"] == "mapped_core_preserved_verified_processing_array"
        assert mapping["native"]["native_exit_status"] == 0
        assert mapping["native"]["log_sha256"] == sha(mapped / "console.log")
        verify(mapping["input_sha256"])
        units = [mapped / "netlist.v"]
    else:
        receipt = ROOT / ".cache/physical/synthesis/tri_oracle_pe_array/xcelium_gate_no_timing.log"
        assert all(f"PASS: 300 full 32x8 signed compute transactions, masks, stalls, reset; NO_STALL={mode}" in
                   receipt.read_text() for mode in range(2))
        units = [receipt.with_name("netlist.v"), case / f"{TOP}.sv", case / "tri_oracle_wac_softmax.sv",
                 *(RTL / f"tri_oracle_wac_{name}.sv" for name in ("imem_owner", "softmax_imem", "outlier_sign"))]
    source = RTL / f"{BENCH}.sv"
    for path in (Path(__file__), preparation, receipt, cells, source, *units, *model_files):
        value = sha(path)
        assert inputs.get(str(path), value) == value, path
        inputs[str(path)] = value
    output.mkdir()
    with tempfile.TemporaryDirectory(dir=output, prefix="core_gate_") as temporary:
        work = Path(temporary)
        testbench = work / source.name
        testbench.write_text(bench(source.read_text()))
        monitor = work / "memory_witness.sv"
        monitor.write_text(witness())
        wait_for_shared_memory("weight-attention core gate replay", 17)
        native = shared_memory_stage("weight-attention core gate replay", output, [
            "/opt/cadence/bin/xrun", "-64bit", "-sv", "-define", "UNIT_DELAY", "-nospecify", "-notimingchecks",
            "-sequdp_nba_delay", "-xmerror", "RECOME", "-top", BENCH, "-xmlibdirname", str(work / "xcelium.d"),
            "-history_file", str(work / "history"), "-l", str(work / "xrun.log"),
            *map(str, [cells, *model_files, *units, testbench, monitor]),
        ], 180, 0)
    log = (output / "console.log").read_text()
    lines = log.splitlines()
    assert lines.count(SUCCESS) == lines.count(OUTLIERS) == 1 and not re.search(r"\*[EF],", log)
    instances = [line.split(maxsplit=2)[1:] for line in lines if line.startswith("WAC_GATE_MEMORY ")]
    observed = {(master, re.sub(r"[\\\s]", "", path)) for master, path in instances}
    expected = {(master, f"{BENCH}.dut.{bank}[{index}].gate_witness")
                for master, bank, count in MACROS for index in range(count)}
    assert len(instances) == len(expected) and observed == expected, observed ^ expected
    verify(inputs)
    (output / "receipt.json").write_text(json.dumps(dict(state="core_handoff_and_outliers_gate_replayed",
        implementation="mapped_core" if mapped else "mapped_array_linked_to_source_core",
        timing_annotated=False, compiled_memories=len(expected), native=native, input_sha256=inputs), indent=2) + "\n")
    print(SUCCESS, OUTLIERS, "compiled_memories=28", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mapped", type=Path)
    args = parser.parse_args()
    run(args.case.resolve(), args.output.resolve(), args.mapped.resolve() if args.mapped else None)
