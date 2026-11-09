"""Run the existing cache contract against actual compiled memory models."""

import ast
import hashlib
import json
from pathlib import Path
import re
import resource
import subprocess
import tempfile
import unittest

from tri_oracle_process_guard import terminate_process_group


EXTRA_TRANSACTIONS = r'''
    task automatic independent_ports(input logic [31:0] tag);
        logic [169:0] expected_meta;
        logic [65:0] expected_read;
        begin
            @(negedge clk);
            meta_req_valid=1;meta_req_index=511;
            read_req_valid=1;read_req_index=0;read_req_length=3;
            @(posedge clk);
            if(!meta_req_ready || !read_req_ready) $fatal(1,"SRAM_DUAL_REQUEST_NOT_READY");
            @(negedge clk);meta_req_valid=0;read_req_valid=0;
            for(int beat=0;beat<3;beat++) begin
                expected_meta={tag,9'(511-beat),1'b0,proxy(normalized(511-beat))};
                expected_read={beat==2,1'b0,activation(beat,tag)};
                repeat(3) begin
                    @(posedge clk);#1;
                    if(!meta_rsp_valid || !read_rsp_valid ||
                        {meta_rsp_tag,meta_rsp_index,meta_rsp_error,meta_rsp_norm}!==expected_meta ||
                        {read_rsp_last,read_rsp_error,read_rsp_data}!==expected_read)
                        $fatal(1,"SRAM_INDEPENDENT_PORT_OR_STALL_MISMATCH beat=%0d",beat);
                end
                @(negedge clk);meta_rsp_ready=1;read_rsp_ready=1;
                meta_req_valid=beat<2;meta_req_index=9'(510-beat);
                @(posedge clk);
                if(beat<2 && !meta_req_ready) $fatal(1,"SRAM_META_REPLACEMENT_NOT_READY");
                @(negedge clk);meta_rsp_ready=0;read_rsp_ready=0;meta_req_valid=0;
            end
            if(meta_rsp_valid || read_rsp_valid) $fatal(1,"SRAM_DUAL_RESPONSE_NOT_DRAINED");
            checked+=6;
            $display("SRAM_INDEPENDENT_PORTS_PASS");
        end
    endtask
    task automatic inactive_response_hold;
        logic [169:0] held_meta;
        logic [65:0] held_read;
        begin
            held_meta={meta_rsp_tag,meta_rsp_index,meta_rsp_error,meta_rsp_norm};
            held_read={read_rsp_last,read_rsp_error,read_rsp_data};
            configure(2,32'h51515151);
            for(int index=0;index<2;index++) begin
                write_word(index,32'h51515151,index==1);
                @(posedge clk);#1;
                if(meta_rsp_valid || read_rsp_valid ||
                    {meta_rsp_tag,meta_rsp_index,meta_rsp_error,meta_rsp_norm}!==held_meta ||
                    {read_rsp_last,read_rsp_error,read_rsp_data}!==held_read)
                    $fatal(1,"SRAM_INACTIVE_RESPONSE_CHANGED_DURING_REFILL");
            end
            completion(32'h51515151,0);release_context();checked++;
            $display("SRAM_INACTIVE_RESPONSE_HOLD_PASS");
        end
    endtask
'''


def contract_bench():
    path = Path("syn/test_tri_oracle_activation_cache.py")
    tree = ast.parse(path.read_text())
    values = [ast.literal_eval(node.value) for node in tree.body
              if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "BENCH"
                      for target in node.targets)]
    if len(values) != 1:
        raise AssertionError("Expected the independent original cache bench")
    bench = values[0]
    anchor = "    task automatic reset_now;"
    if bench.count(anchor) != 1:
        raise AssertionError("Original cache bench anchor changed")
    bench = bench.replace(anchor, EXTRA_TRANSACTIONS + anchor)
    anchor = "        release_context();inaccessible();\n        for(int mode=1;mode<=4;mode++)"
    if bench.count(anchor) != 1:
        raise AssertionError("Original committed-cache sequence changed")
    return bench.replace(
        anchor,
        "        independent_ports(32'h80000001);\n"
        "        release_context();inaccessible();inactive_response_hold();\n"
        "        for(int mode=1;mode<=4;mode++)")


def generated_models(corner):
    record = json.loads(Path("records/sram_activation_cache_banks_generation.json").read_text())
    if not record["views_generated"]:
        raise AssertionError("Actual compiled cache memories are required")
    models = []
    for width in (64, 16):
        matches = list(Path(record["cwd"]).glob(f"*/VERILOG/*512x{width}m4f_*_{corner}.v"))
        if len(matches) != 1:
            raise AssertionError((corner, width, matches))
        path = matches[0]
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["view_sha256"][str(path)]:
            raise AssertionError(f"Generated model changed: {path}")
        models.append(path)
    return models


def cycle_peer_bench(bench):
    header = Path("verilog/tri_oracle_activation_cache.sv").read_text().split("(", 1)[1].split(");", 1)[0]
    direction = width = None
    declarations = ["    int unsigned peer_checks=0;"]
    connections = []
    checks = []
    for declaration in header.split(","):
        match = re.fullmatch(r"\s*(?:(input|output)\s+logic\s*(\[[^]]+\])?\s*)?(\w+)\s*",
                             declaration)
        if not match:
            raise AssertionError("Unsupported original port declaration: " + declaration)
        new_direction, new_width, name = match.groups()
        if new_direction:
            direction, width = new_direction, new_width or ""
        if direction == "output":
            declarations.append(f"    logic {width} peer_{name};")
            connections.append(f".{name}(peer_{name})")
            checks.append(f'        if(peer_{name} !== {name}) '
                          f'$fatal(1,"SRAM_CACHE_CYCLE_MISMATCH signal={name}");')
        else:
            connections.append(f".{name}({name})")
    if len(checks) != 17:
        raise AssertionError("Original cache output interface changed")
    peer = "\n".join(declarations) + "\n    tri_oracle_sram_activation_cache peer (\n        "
    peer += ",\n        ".join(connections) + ");\n"
    peer += "    always @(posedge clk) begin\n        #1;\n" + "\n".join(checks)
    peer += "\n        peer_checks++;\n    end\n"
    anchor = "    tri_oracle_activation_cache dut (.*);"
    if bench.count(anchor) != 1:
        raise AssertionError("Original DUT anchor changed")
    bench = bench.replace(anchor, peer + anchor)
    anchor = '$display("ACTIVATION_CACHE_PASS read_checks=%0d",checked);'
    if bench.count(anchor) != 1:
        raise AssertionError("Original completion marker changed")
    return bench.replace(anchor, 'if(peer_checks<1000) $fatal(1,"SRAM_CYCLE_PEER_NOT_EXERCISED");'
                         '$display("SRAM_CACHE_CYCLE_PEER_PASS checks=%0d",peer_checks);' + anchor)


def run_bounded(args):
    def limits():
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))

    with subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, start_new_session=True,
                          preexec_fn=limits) as child:
        try:
            stdout, stderr = child.communicate(timeout=60)
        finally:
            terminate_process_group(child, grace_seconds=1)
        return {"exit_status": child.returncode, "stdout": stdout, "stderr": stderr}


class SramActivationCacheTest(unittest.TestCase):
    def simulate(self, source, corner=None, default_module_name=False, cycle_peer=False):
        available = next(int(line.split()[1]) * 1024 for line in
                         Path("/proc/meminfo").read_text().splitlines()
                         if line.startswith("MemAvailable:"))
        self.assertGreaterEqual(available, 8 * 1024**3)
        self.native_runs = getattr(self, "native_runs", [])
        with tempfile.TemporaryDirectory(prefix="sram_cache_", dir=".cache") as directory:
            root = Path(directory)
            bench = contract_bench()
            if cycle_peer:
                bench = cycle_peer_bench(bench)
            if default_module_name:
                self.assertEqual(bench.count("tri_oracle_activation_cache dut (.*);"), 1)
                bench = bench.replace("tri_oracle_activation_cache dut (.*);",
                                      "tri_oracle_sram_activation_cache dut (.*);")
            path = root / "bench.sv"
            path.write_text(bench)
            binary = root / "cache.vvp"
            command = ["iverilog", "-g2012", "-s", "tri_oracle_activation_cache_tb",
                       "-o", str(binary)]
            if corner:
                command.append("-DUNIT_DELAY")
                if not default_module_name and not cycle_peer:
                    command.append("-DTRI_ORACLE_SRAM_CACHE_BIND_PUBLIC")
                command.extend(str(model) for model in generated_models(corner))
            if cycle_peer:
                command.append("verilog/tri_oracle_activation_cache.sv")
            command.extend([str(source), str(path)])
            compiled = run_bounded(command)
            self.assertEqual(compiled["exit_status"], 0, compiled["stdout"] + compiled["stderr"])
            native = run_bounded(["vvp", str(binary)])
        self.assertFalse(root.exists())
        native["corner"] = corner
        native["cycle_peer"] = cycle_peer
        self.native_runs.append(native)
        return native

    def assert_contract(self, result):
        self.assertEqual(result["exit_status"], 0, result["stdout"] + result["stderr"])
        for marker in ("ACTIVATION_CACHE_PASS", "SRAM_INDEPENDENT_PORTS_PASS",
                       "SRAM_INACTIVE_RESPONSE_HOLD_PASS"):
            self.assertEqual(result["stdout"].count(marker), 1, result["stdout"])

    def test_original_contract_with_independent_ports_and_refill(self):
        self.assert_contract(self.simulate("verilog/tri_oracle_activation_cache.sv"))

    def test_actual_compiler_models_at_three_corners(self):
        for corner in ("tt1v25c", "ssg0p9v125c", "ffg1p05vm40c"):
            with self.subTest(corner=corner):
                self.assert_contract(self.simulate("verilog/tri_oracle_sram_activation_cache.sv", corner))

    def test_distinct_default_module_name(self):
        self.assert_contract(self.simulate("verilog/tri_oracle_sram_activation_cache.sv", "tt1v25c",
                                          default_module_name=True))

    def test_cycle_equivalence_to_original_at_three_corners(self):
        for corner in ("tt1v25c", "ssg0p9v125c", "ffg1p05vm40c"):
            with self.subTest(corner=corner):
                result = self.simulate("verilog/tri_oracle_sram_activation_cache.sv", corner,
                                       cycle_peer=True)
                self.assert_contract(result)
                self.assertEqual(result["stdout"].count("SRAM_CACHE_CYCLE_PEER_PASS"), 1)

    def test_native_fault_controls(self):
        source = Path("verilog/tri_oracle_sram_activation_cache.sv").read_text()
        changes = (
            ("shared_read_address", "metadata_addr = meta_req_index;",
             "metadata_addr = activation_addr;", 1, "CACHE_META_MISMATCH"),
            ("uncommitted_reads", "busy && committed && !done_valid",
             "busy && !done_valid", 2, "CACHE_PROVISIONAL_OR_FAILED_DATA_VISIBLE"),
            ("advance_while_stalled", "read_rsp_valid && read_rsp_ready && !read_rsp_last",
             "read_rsp_valid && !read_rsp_last", 1, "CACHE_READ_STALL_OR_RELEASE"),
        )
        with tempfile.TemporaryDirectory(prefix="sram_cache_fault_", dir=".cache") as directory:
            root = Path(directory)
            for name, before, after, count, expected in changes:
                with self.subTest(variant=name):
                    self.assertEqual(source.count(before), count, name)
                    path = root / (name + ".sv")
                    path.write_text(source.replace(before, after))
                    result = self.simulate(path, "tt1v25c")
                    result["fault_variant"] = name
                    self.assertEqual(result["exit_status"], 1, result["stdout"] + result["stderr"])
                    self.assertIn(expected, result["stdout"])
        self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
