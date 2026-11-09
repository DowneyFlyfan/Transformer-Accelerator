"""Native raw-residual to mask test with real packed-sign memory transactions.

The test catches sign-lane permutations, missing memory reads, early mask
publication and any partial prediction surviving a late sign/normalization fault.
"""
from pathlib import Path
import random
import resource
import subprocess
import tempfile
import unittest

from test_tri_oracle_rmsnorm import normalized_codes
from test_tri_oracle_sign_fetch import MEMORY_PEER


BENCH = r'''`timescale 1ns/1ps
module tri_oracle_rms_sign_predictor_tb;
    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, cfg_valid = 0, cfg_ready;
    logic [31:0] cfg_tag = 0, cfg_epsilon_q16 = 0, expected_tag = 0;
    logic [10:0] cfg_group = 0;
    logic [9:0] cfg_strips = 0;
    logic [63:0] cfg_gate_sign_base = 0, cfg_up_sign_base = 0;
    logic stats_valid = 0, stats_ready, stats_last = 0;
    logic [127:0] stats_data = 0;
    logic replay_valid = 0, replay_ready, replay_last = 0;
    logic [127:0] replay_data = 0;
    logic out_valid, out_ready = 0, out_error;
    logic [31:0] out_tag, gate_nearzero_mask, up_nearzero_mask, skip_mask;
    logic [12:0] outlier_count;
    logic req_valid, req_ready = 0;
    logic [63:0] req_address;
    logic [4:0] req_length;
    logic rsp_valid = 0, rsp_ready, rsp_last = 0, rsp_error = 0;
    logic [63:0] rsp_data = 0;
    logic [127:0] requests [0:@REQUEST_WORDS@-1];
    logic [127:0] packets [0:@DATA_WORDS@-1];
    int cursor = 0, limit = 0, fault_at = -1, fault_mode = 0;
    int cycle = 0, delay_count = 0, beat = 0, active_request = -1;
    int checked = 0, drains = 0;
    bit pending = 0, consumed = 0, force_request_stall = 0;
    bit force_response_stall = 0, allow_result = 0;
    logic [63:0] active_data = 0;
    tri_oracle_rms_sign_predictor dut (.*);
@MEMORY_PEER@
    always @(posedge clk)
        if (rst_n && out_valid && !allow_result)
            $fatal(1,"RMS_SIGN_PREMATURE_MASK");

    task automatic configure(
        input int strips, group_id,
        input logic [31:0] epsilon, tag,
        input logic [63:0] gate_base, up_base,
        input bit invalid = 0
    );
        int timeout;
        begin
            @(negedge clk); #1; cfg_valid = 1; cfg_tag = tag; expected_tag = tag;
            cfg_strips = 10'(strips); cfg_group = 11'(group_id);
            cfg_epsilon_q16 = epsilon;
            cfg_gate_sign_base = gate_base; cfg_up_sign_base = up_base;
            allow_result = invalid;
            timeout = 0; @(posedge clk);
            while (cfg_ready !== 1'b1 && timeout < 100) begin
                @(posedge clk); timeout++;
            end
            if (cfg_ready !== 1'b1) $fatal(1,"RMS_SIGN_CONFIG_TIMEOUT");
            @(negedge clk); #1; cfg_valid = 0; cfg_tag = '1; cfg_strips = 0;
            cfg_group = '1; cfg_epsilon_q16 = '1;
            cfg_gate_sign_base = '1; cfg_up_sign_base = '1;
        end
    endtask

    task automatic stats_word(input logic [127:0] data, input bit last);
        int timeout;
        begin
            @(negedge clk); #1; stats_valid = 1; stats_last = last; stats_data = data;
            timeout = 0; @(posedge clk);
            while (stats_ready !== 1'b1 && timeout < 300) begin
                @(posedge clk); timeout++;
            end
            if (stats_ready !== 1'b1) $fatal(1,"RMS_SIGN_STATS_TIMEOUT");
            @(negedge clk); #1; stats_valid = 0; stats_data = ~data; stats_last = !last;
        end
    endtask

    task automatic replay_word(input logic [127:0] data, input bit last);
        int timeout;
        begin
            @(negedge clk); #1; replay_valid = 1; replay_last = last; replay_data = data;
            timeout = 0; @(posedge clk);
            while (replay_ready !== 1'b1 && timeout < 300) begin
                @(posedge clk); timeout++;
            end
            if (replay_ready !== 1'b1) $fatal(1,"RMS_SIGN_REPLAY_TIMEOUT");
            @(negedge clk); #1; replay_valid = 0; replay_data = ~data; replay_last = !last;
            if (last) allow_result = 1;
        end
    endtask

    task automatic receive_mask(
        input logic [31:0] gate_mask, up_mask, skipped,
        input int outliers,
        input bit error
    );
        int timeout;
        logic [141:0] wanted;
        begin
            timeout = 0;
            while (out_valid !== 1'b1 && timeout < 300) begin
                @(negedge clk); #1; timeout++;
            end
            if (out_valid !== 1'b1) $fatal(1,"RMS_SIGN_RESULT_TIMEOUT");
            wanted = {expected_tag,error,13'(outliers),gate_mask,up_mask,skipped};
            if ({out_tag,out_error,outlier_count,gate_nearzero_mask,up_nearzero_mask,skip_mask}
                !== wanted)
                $fatal(1,"RMS_SIGN_MASK_MISMATCH tag=%h error=%b count=%0d skip=%h",
                    out_tag,out_error,outlier_count,skip_mask);
            if (cursor != limit || pending) $fatal(1,"RMS_SIGN_REQUESTS_NOT_COMPLETE");
            cfg_valid = 1;
            repeat (6) begin
                @(posedge clk); #1;
                if (out_valid !== 1'b1 || cfg_ready || stats_ready || replay_ready || req_valid ||
                    {out_tag,out_error,outlier_count,gate_nearzero_mask,up_nearzero_mask,skip_mask}
                    !== wanted) $fatal(1,"RMS_SIGN_STALL_CHANGED_MASK");
            end
            @(negedge clk); #1; cfg_valid = 0; out_ready = 1;
            @(negedge clk); #1; out_ready = 0; checked++;
        end
    endtask

    task automatic reset_now;
        begin
            @(negedge clk); #1; rst_n = 0; cfg_valid = 0; allow_result = 0;
            repeat (2) @(negedge clk); #1; rst_n = 1;
            repeat (6) begin
                @(posedge clk); #1;
                if (out_valid || req_valid || rsp_ready || !cfg_ready)
                    $fatal(1,"RMS_SIGN_RESET_LEFT_FRAME");
            end
        end
    endtask

    initial begin
        $readmemh("@REQUEST_FILE@",requests,0,@REQUEST_WORDS@-1);
        $readmemh("@PACKET_FILE@",packets,0,@DATA_WORDS@-1);
        repeat (2) @(negedge clk); #1; rst_n = 1;
@BODY@
        $display("RMS_SIGN_PREDICTOR_PASS frames=%0d requests=%0d drain_beats=%0d",
            checked,cursor,drains);
        $finish;
    end
    initial begin #5000000; $fatal(1,"RMS_SIGN_GLOBAL_WATCHDOG"); end
endmodule
'''


class RmsSignPredictorTest(unittest.TestCase):
    def test_native_raw_residual_sign_reads_late_faults_and_recovery(self):
        rng = random.Random(316503)
        packets, requests, body, cases = [], [], [], []

        def fixture(values, *, epsilon=0, group=0, gate_base=0x2000,
                    up_base=0x200000, fault_offset=-1, fault_mode=0,
                    energy_fault=False, invalid_sign_layout=False, matrix_signs=None):
            codes = normalized_codes(values, epsilon)
            active = [abs(code) > 768 for code in codes]
            signs = matrix_signs if matrix_signs is not None else [
                [[rng.randrange(2) for _ in values] for _ in range(32)] for _ in range(2)]
            self.assertEqual(len(signs), 2)
            self.assertTrue(all(len(matrix) == 32 and all(len(row) == len(values)
                                for row in matrix) for matrix in signs))
            if not cases:
                for row, pair in enumerate([(0, 1), (1, 0), (0, 0), (1, 0), (0, 1)]):
                    signs[0][row][:2] = pair
                for row, pair in enumerate([(0, 1), (0, 0), (0, 0), (0, 1), (0, 0)]):
                    signs[1][row][:2] = pair
            masks = [0, 0]
            count = sum(active)
            for row in range(32):
                margins = [sum(1 if (codes[i] < 0) == matrix[row][i] else -1
                               for i in range(len(values)) if active[i]) for matrix in signs]
                masks[0] |= bool(count and margins[0] <= 0) << row
                masks[1] |= bool(count and margins[1] == 0) << row
            first_packet = len(packets)
            for start in range(0, len(values), 8):
                packets.append(sum((value & 0xffff) << (16*lane)
                                   for lane, value in enumerate(values[start:start+8])))
            first_request = len(requests)
            faulted = invalid_sign_layout
            for strip in range(len(values)//8):
                if faulted or (energy_fault and strip == len(values)//8-1):
                    continue
                for pair in range(4):
                    lanes = [strip*8+pair*2, strip*8+pair*2+1]
                    if not any(active[lane] for lane in lanes):
                        continue
                    for matrix, base in enumerate((gate_base, up_base)):
                        address = base+group*(len(values)//8)*32+strip*32+pair*8
                        word = sum(signs[matrix][row][lane] << (row+32*half)
                                   for row in range(32) for half, lane in enumerate(lanes))
                        requests.append((address, word))
                        if len(requests)-first_request-1 == fault_offset:
                            faulted = True
                            break
                    if faulted:
                        break
            error = fault_offset >= 0 or energy_fault or invalid_sign_layout
            if error:
                masks = [0, 0]; count = 0
            tag = len(cases)+1
            result = dict(base=first_packet, strips=len(values)//8, epsilon=epsilon,
                          group=group, gate_base=gate_base, up_base=up_base, tag=tag,
                          first_request=first_request, request_count=len(requests)-first_request,
                          fault_offset=fault_offset, fault_mode=fault_mode,
                          energy_fault=energy_fault, masks=masks, count=count, error=error)
            cases.append(result)
            return result

        def emit(case):
            c = case
            body.extend([
                f"        limit={c['first_request']+c['request_count']};",
                f"        if(cursor!={c['first_request']}) $fatal(1,\"RMS_SIGN_SCRIPT_POSITION\");",
                f"        fault_at={c['first_request']+c['fault_offset'] if c['fault_offset']>=0 else -1};"
                f" fault_mode={c['fault_mode']};",
                f"        configure({c['strips']},{c['group']},32'h{c['epsilon']:08x},"
                f"32'h{c['tag']:08x},64'h{c['gate_base']:016x},64'h{c['up_base']:016x});",
                f"        for(int k=0;k<{c['strips']};k++) "
                f"stats_word(packets[{c['base']}+k],k=={c['strips']-1});",
                f"        for(int k=0;k<{c['strips']};k++) "
                f"replay_word(packets[{c['base']}+k] ^ "
                f"128'(k=={c['strips']-1} && {int(c['energy_fault'])}),k=={c['strips']-1});",
                f"        receive_mask(32'h{c['masks'][0]:08x},32'h{c['masks'][1]:08x},"
                f"32'h{c['masks'][0]&c['masks'][1]:08x},{c['count']},{int(c['error'])});",
            ])

        first = fixture([16, -16]+[0]*30)
        self.assertEqual((first['masks'][0] & 31, first['masks'][1] & 31,
                          (first['masks'][0] & first['masks'][1]) & 31), (14, 22, 6))
        self.assertEqual(first['request_count'], 2)
        emit(first)
        emit(fixture([1]*8))
        self.extra_case_evidence = []
        for extra in getattr(self, 'extra_model_cases', []):
            case = fixture(**extra)
            self.extra_case_evidence.append(case)
            emit(case)
        emit(fixture([1537, 1353, 36, 5, 2, 1]+[0]*10))
        emit(fixture([1537, 1353, 36, 5, 2, 1]+[0]*10, epsilon=1))
        emit(fixture([rng.randrange(-500, 501) for _ in range(2048)], epsilon=4295, group=175))
        emit(fixture([32767]+[0]*4094+[-32768], group=2047,
                     gate_base=0xfffffffff0000000, up_base=0xffffffffe0000000))
        spread = [16, -16]+[0]*14+[16, -16]+[0]*14+[16, -16]+[0]*30
        self.assertEqual(len(spread), 64)
        emit(fixture(spread, fault_offset=2, fault_mode=1))
        emit(fixture(spread, fault_offset=3, fault_mode=2))
        emit(fixture([16, -16]+[0]*30, energy_fault=True))
        emit(fixture([16, -16]+[0]*30, gate_base=0x2001, invalid_sign_layout=True))
        emit(fixture([1]*8))
        body.extend([
            "        limit=cursor; fault_at=-1; fault_mode=0;",
            "        configure(0,0,0,32'h100,64'h2000,64'h200000,1);",
            "        receive_mask(0,0,0,0,1);",
        ])
        # Establish a real outlier prefix in the child predictor before reset.
        # A fresh no-outlier frame must not retain its counts or sign margins.
        prefix = fixture([16, -16]+[0]*30)
        body.extend([
            f"        limit={prefix['first_request']+prefix['request_count']}; fault_at=-1;",
            f"        configure(4,0,0,32'h101,64'h2000,64'h200000);",
            f"        for(int k=0;k<4;k++) stats_word(packets[{prefix['base']}+k],k==3);",
            f"        replay_word(packets[{prefix['base']}],0);",
            f"        replay_word(packets[{prefix['base']}+1],0);",
            "        repeat(80) @(negedge clk); #1;",
            "        if(cursor!=limit || pending) $fatal(1,\"RMS_SIGN_PREFIX_NOT_FETCHED\");",
            "        reset_now();",
        ])
        emit(fixture([1]*8))
        # Reset a held terminal mask too, rather than only an in-flight frame.
        held = fixture([1]*8)
        body.extend([
            "        limit=cursor; fault_at=-1;",
            f"        configure(1,0,0,32'h102,64'h2000,64'h200000);",
            f"        stats_word(packets[{held['base']}],1);",
            f"        replay_word(packets[{held['base']}],1);",
            "        begin int t; t=0; while(!out_valid && t<300) begin",
            "            @(negedge clk); #1; t++; end",
            "            if(!out_valid) $fatal(1,\"RMS_SIGN_HELD_RESULT_NOT_REACHED\"); end",
            "        reset_now();",
        ])
        emit(fixture([1]*8))
        available = int(next(line.split()[1] for line in
                             Path('/proc/meminfo').read_text().splitlines()
                             if line.startswith('MemAvailable:')))*1024
        self.assertGreaterEqual(available, 6*1024**3)

        def bounded():
            resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))

        with tempfile.TemporaryDirectory(prefix='rms_sign_test_', dir='.cache') as directory:
            root = Path(directory)
            request_file, packet_file = root/'requests.memh', root/'packets.memh'
            request_file.write_text(''.join(f'{address:016x}{word:016x}\n'
                                            for address, word in requests))
            packet_file.write_text(''.join(f'{packet:032x}\n' for packet in packets))
            bench = root/'bench.sv'
            bench.write_text(BENCH.replace('@MEMORY_PEER@', MEMORY_PEER)
                             .replace('@REQUEST_WORDS@', str(len(requests)))
                             .replace('@DATA_WORDS@', str(len(packets)))
                             .replace('@REQUEST_FILE@', str(request_file))
                             .replace('@PACKET_FILE@', str(packet_file))
                             .replace('@BODY@', '\n'.join(body)))
            binary = root/'rms_sign.vvp'
            compiled = subprocess.run([
                'iverilog', '-g2012', '-s', 'tri_oracle_rms_sign_predictor_tb',
                '-o', str(binary), 'verilog/tri_oracle_rmsnorm.sv',
                'verilog/tri_oracle_sign_fetch.sv', 'verilog/tri_oracle_strip_predictor.sv',
                getattr(self, 'source_path', 'verilog/tri_oracle_rms_sign_predictor.sv'), str(bench)],
                text=True, capture_output=True, timeout=60, preexec_fn=bounded)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run(['vvp', str(binary)], text=True,
                                    capture_output=True, timeout=120, preexec_fn=bounded)
        self.assertFalse(root.exists())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(result.stdout.count('RMS_SIGN_PREDICTOR_PASS'), 1)
        self.native_stdout = result.stdout


if __name__ == '__main__':
    unittest.main()
