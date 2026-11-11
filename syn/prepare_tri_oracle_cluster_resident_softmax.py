"""Build a source candidate with the verified softmax arithmetic inside each aggregator."""

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / ".cache/physical/shared437/aggregator_local_merge/cluster_native/partitioned_parent"
NATIVE = PARENT.parent
sys.path[:0] = [str(PARENT), str(NATIVE)]
from run_separate_cores_fixture_export_at_reserve import read, sha, verify
from prepare_parent_boundary_probe import probe_text

TYPES = "tri_oracle_softmax_bank_types"
COMMAND = f"{TYPES}::command_t"
RESPONSE = f"{TYPES}::response_t"
LINK = ".softmax_command, .softmax_response,"
PACKAGE = f"""package {TYPES};
    typedef struct packed {{
        logic begin_row, load, read_slot, write_weight;
        logic [7:0] slot;
        logic signed [15:0] in_score;
        logic [9:0] in_size;
        logic signed [15:0] maximum;
        logic [28:0] reciprocal;
    }} command_t;
    typedef struct packed {{
        logic signed [15:0] local_maximum;
        logic [37:0] local_sum;
        logic [15:0] probability;
    }} response_t;
endpackage
"""
MONITOR = """`timescale 1ns/1ps
module tri_oracle_softmax_cluster_probe (
    input logic clk, rst_n, begin_row, load, read_slot, write_weight
);
    int rows, loads, reads, weights;
    always @(posedge clk) if (rst_n) begin
        if (begin_row) rows++;
        if (load) loads++;
        if (read_slot) reads++;
        if (write_weight) weights++;
    end
    final $display("SOFTMAX_CLUSTER_BANK %m rows=%0d loads=%0d reads=%0d weights=%0d",
                   rows, loads, reads, weights);
endmodule
bind tri_oracle_softmax_bank tri_oracle_softmax_cluster_probe cluster_probe (.*);
"""


def replace(text, old, new, expected=1):
    assert text.count(old) == expected, (old, text.count(old), expected)
    return text.replace(old, new)


def array_ports(text, bank_side):
    command, response = ("input", "output") if bank_side else ("output", "input")
    anchor = f"{command} tri_oracle_token_size_types::request_t token_sizes_request,"
    return replace(text, anchor, f"{command} {COMMAND} [4:0] softmax_command,\n"
                   f"    {response} {RESPONSE} [4:0] softmax_response,\n    {anchor}")


def bank_ports(text, anchor, count):
    return replace(text, anchor, f"input {COMMAND} softmax_command,\n"
                   f"  output {RESPONSE} softmax_response,\n  {anchor}", count)


def controller(source):
    text = replace(source, "module tri_oracle_aggregator_softmax (",
                   "module tri_oracle_cluster_softmax_control (")
    text = replace(text, "    output logic out_last\n);",
                   f"    output logic out_last,\n    output {COMMAND} [4:0] softmax_command,\n"
                   f"    input {RESPONSE} [4:0] softmax_response\n);")
    text = replace(text, "        localparam int ENTRIES = (MAX_KEYS + BANKS - 1 - bank) / BANKS;\n", "")
    begin = text.index("        tri_oracle_softmax_bank #")
    end = text.index("\n    end", begin)
    existing = text[begin:end]
    assert existing.count(".local_maximum(bank_maximum[bank])") == 1
    assert existing.count(".read_slot((state == READ_SCORE && active_slot) || bank_output_read[bank])") == 1
    wiring = """        assign softmax_command[bank] = '{
            begin_row: begin_row, load: bank_load[bank],
            read_slot: (state == READ_SCORE && active_slot) || bank_output_read[bank],
            write_weight: bank_weight_write[bank], slot: slot_index,
            in_score: in_score, in_size: in_size, maximum: maximum, reciprocal: reciprocal
        };
        assign bank_maximum[bank] = softmax_response[bank].local_maximum;
        assign bank_sum[bank] = softmax_response[bank].local_sum;
        assign bank_probability[bank] = softmax_response[bank].probability;"""
    text = text[:begin] + wiring + text[end:]
    assert "tri_oracle_softmax_bank #" not in text
    return text


def reroute(name, text):
    through = ".token_sizes_request, .token_sizes_response,"
    packed_anchor = "input tri_oracle_merge_range_types::range_command_t merge_range_command,"
    if name == "tri_oracle_attention_row426.sv":
        text = array_ports(text, bank_side=False)
        text = replace(text, "tri_oracle_aggregator_softmax normalize (",
                       "tri_oracle_cluster_softmax_control normalize (\n        " + LINK)
    elif name in ("tri_oracle_attention_layer427.sv", "tri_oracle_attention_pipeline430.sv"):
        text = replace(array_ports(text, bank_side=False), through, through + " " + LINK)
    elif name == "tri_oracle_shared_layer437.sv":
        anchor = "    tri_oracle_token_size_types::request_t token_sizes_request;"
        text = replace(text, anchor, f"    {COMMAND} [4:0] softmax_command;\n"
                       f"    {RESPONSE} [4:0] softmax_response;\n{anchor}")
        text = replace(text, through, through + " " + LINK, 2)
    elif name in ("tri_oracle_batched_learned406.sv", "tri_oracle_batched_frame393.sv",
                  "tri_oracle_batched_shared392.sv", "tri_oracle_batched_tensor390.sv"):
        text = replace(array_ports(text, bank_side=True), through, through + " " + LINK)
        if name in ("tri_oracle_batched_learned406.sv", "tri_oracle_batched_frame393.sv"):
            tie_off = ".token_sizes_request('0), .token_sizes_response(),"
            text = replace(text, tie_off, tie_off + " .softmax_command('0), .softmax_response(),")
    elif name == "tri_oracle_compute_fabric.sv":
        text = array_ports(text, bank_side=True)
        anchor = ".merge_range_command(range_commands[cluster]),"
        text = replace(text, anchor, ".softmax_command(softmax_command[cluster]),\n"
                       "            .softmax_response(softmax_response[cluster]),\n            " + anchor)
    elif name == "cluster_adapter.sv":
        text = bank_ports(text, packed_anchor, 1)
        for bank in (0, 1):
            text = replace(text, f"tri_oracle_native_cluster{bank}_mapped_replay{bank} block_instance",
                           f"tri_oracle_native_cluster{bank} block_instance")
    elif name == "wrappers.sv":
        text = bank_ports(text, "input wire [376:0] merge_range_command,", 5)
        text = replace(text, ".merge_range_command(merge_range_command),",
                       LINK + "\n    .merge_range_command(merge_range_command),", 5)
    elif name == "tri_oracle_sram_compute_cluster.sv":
        text = bank_ports(text, packed_anchor, 2)
        anchor = "  if (LOCAL_TOKEN_MERGE) begin : local_merge"
        instance = """  tri_oracle_softmax_bank #(.ENTRIES(MERGE_TABLE_START == 512 ? 204 : 205)) softmax_bank (
    .clk, .rst_n, .begin_row(softmax_command.begin_row),
    .load(softmax_command.load), .slot(softmax_command.slot),
    .in_score(softmax_command.in_score), .in_size(softmax_command.in_size),
    .read_slot(softmax_command.read_slot), .write_weight(softmax_command.write_weight),
    .maximum(softmax_command.maximum), .reciprocal(softmax_command.reciprocal),
    .local_maximum(softmax_response.local_maximum), .local_sum(softmax_response.local_sum),
    .probability(softmax_response.probability)
  );

"""
        text = replace(text, anchor, instance + anchor)
    else:
        raise ValueError(name)
    return text


FILENAMES = {
    "tri_oracle_attention_row426.sv", "tri_oracle_attention_layer427.sv", "tri_oracle_attention_pipeline430.sv",
    "tri_oracle_shared_layer437.sv", "tri_oracle_batched_learned406.sv", "tri_oracle_batched_frame393.sv",
    "tri_oracle_batched_shared392.sv", "tri_oracle_batched_tensor390.sv", "tri_oracle_compute_fabric.sv",
    "cluster_adapter.sv", "wrappers.sv", "tri_oracle_sram_compute_cluster.sv",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output.resolve()
    source = PARENT / "aggregator_softmax_replay"
    old_prep = source / "receipt.json"
    old_replay = source / "xcelium/receipt.json"
    baseline = read(old_prep)
    proof = read(old_replay)
    assert proof["state"] == "mapped_clusters_passed_integrated_attention_fixture"
    assert proof["mapped_banks"] == baseline["mapped_banks"] == [0, 1]
    assert proof["replay"]["native_exit_status"] == 0
    inputs = proof["input_sha256"].copy()
    verify(inputs)
    output.mkdir()
    types = output / "softmax_bank_types.sv"
    types.write_text(PACKAGE)
    native_controller = output / "tri_oracle_cluster_softmax_control.sv"
    previous = ROOT / "verilog/tri_oracle_aggregator_softmax.sv"
    assert inputs[str(previous)] == sha(previous)
    native_controller.write_text(controller(previous.read_text()))
    monitor = output / "cluster_softmax_probe.sv"
    monitor.write_text(MONITOR)
    merge_monitor = output / "bank_probe.sv"
    merge_monitor.write_text(probe_text([]))
    original = (source / "bundle.sv").read_text()
    includes = set()
    generated = [types, native_controller, monitor, merge_monitor]

    def rewrite(match):
        path = Path(match[1])
        if path.name in FILENAMES:
            assert path.name not in includes, path
            assert inputs[str(path)] == sha(path)
            includes.add(path.name)
            target = output / path.name
            target.write_text(reroute(path.name, path.read_text()))
            generated.append(target)
            return f'`include "{target}"'
        if path == previous:
            return f'`include "{native_controller}"'
        if path.name == "bank_probe.sv":
            assert inputs[str(path)] == sha(path)
            assert path.read_text() == probe_text([0, 1])
            return f'`include "{merge_monitor}"'
        if path.name in {"cluster0.v", "cluster1.v", "shared_compute_core.v", "tcbn28hpcplusbwp12t40p140.v"}:
            return ""
        return match[0]

    body = re.sub(r'(?m)^`include "([^"]+)"$', rewrite, original)
    assert includes == FILENAMES and len(generated) == len(FILENAMES) + 4
    assert body.count(f'`include "{merge_monitor}"') == 1
    bundle = output / "bundle.sv"
    bundle.write_text(f'`include "{types}"\n' + body + f'`include "{monitor}"\n')
    inputs.update({str(path): sha(path) for path in (
        Path(__file__), old_prep, old_replay, bundle, *generated,
    )})
    verify(inputs)
    baseline.update(bundle=str(bundle), input_sha256=inputs, mapped_banks=[], mapped_core_instances={},
                    linked_memory_inventory={}, softmax="bank_under_each_source_aggregator")
    (output / "receipt.json").write_text(json.dumps(baseline, indent=2) + "\n")
    print("Prepared five cluster-resident softmax banks and the separate row coordinator.", flush=True)


if __name__ == "__main__":
    main()
