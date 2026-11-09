"""Native normalization plus learned-scale codes and provisional-frame checks."""
from pathlib import Path
import random
import resource
import subprocess
import tempfile
import unittest

from test_tri_oracle_affine_quantizer import scaled_code
from test_tri_oracle_rmsnorm import normalized_codes


BENCH = r'''`timescale 1ns/1ps
module tri_oracle_rms_activation_tb;
    logic clk=0;
    always #5 clk=~clk;
    logic rst_n=0,cfg_valid=0,cfg_ready;
    logic [31:0] cfg_tag=0,cfg_epsilon_q16=0;
    logic [9:0] cfg_strips=0;
    logic [5:0] cfg_shift=0;
    logic stats_valid=0,stats_ready,stats_last=0;
    logic [127:0] stats_data=0;
    logic replay_valid=0,replay_ready,replay_last=0;
    logic [127:0] replay_data=0,replay_gamma=0;
    logic out_valid,out_ready=0,out_last,out_error;
    logic [31:0] out_tag;
    logic [9:0] out_index;
    logic [3:0] out_count;
    logic [127:0] out_norm_q8;
    logic [7:0] out_outlier_mask;
    logic [63:0] out_activation;
    logic [255:0] packets [0:@DATA_WORDS@-1];
    logic [247:0] expected [0:@EXPECTED_WORDS@-1];
    logic [247:0] held;
    int cycle=0,checked=0,frames=0;
    bit stalled=0,force_stall=0,check_enabled=1;
    tri_oracle_rms_activation dut (.*);
    always @(negedge clk) begin cycle++;out_ready=!force_stall && cycle%17<5;end
    always @(posedge clk) if(rst_n && check_enabled) begin
        if(stalled && (!out_valid || {out_tag,out_index,out_count,out_last,out_error,
            out_norm_q8,out_outlier_mask,out_activation}!==held))
            $fatal(1,"RMS_ACTIVATION_HELD_OUTPUT_CHANGED");
        stalled=out_valid && !out_ready;
        held={out_tag,out_index,out_count,out_last,out_error,
            out_norm_q8,out_outlier_mask,out_activation};
        if(out_valid && out_ready) begin
            if(checked>=@EXPECTED_WORDS@ || held!==expected[checked])
                $fatal(1,"RMS_ACTIVATION_MISMATCH word=%0d tag=%h index=%0d error=%b codes=%h",
                    checked,out_tag,out_index,out_error,out_activation);
            checked++;
            if(out_last) frames++;
        end
        if(out_valid && cfg_ready) $fatal(1,"RMS_ACTIVATION_CONFIG_REOPENED_BEFORE_TERMINAL");
    end
    task automatic configure(input int strips,shift,input logic [31:0] epsilon,tag);
        int timeout;
        begin
            @(negedge clk);#1;cfg_valid=1;cfg_tag=tag;cfg_strips=10'(strips);
            cfg_shift=6'(shift);cfg_epsilon_q16=epsilon;timeout=0;@(posedge clk);
            while(cfg_ready!==1'b1 && timeout<200) begin @(posedge clk);timeout++;end
            if(cfg_ready!==1'b1) $fatal(1,"RMS_ACTIVATION_CONFIG_TIMEOUT");
            @(negedge clk);#1;cfg_valid=0;cfg_tag='1;cfg_strips=0;cfg_shift='1;
            cfg_epsilon_q16='1;
        end
    endtask
    task automatic stats_word(input logic [127:0] data,input bit last);
        int timeout;
        begin
            @(negedge clk);#1;stats_valid=1;stats_last=last;stats_data=data;
            timeout=0;@(posedge clk);
            while(stats_ready!==1'b1 && timeout<200) begin @(posedge clk);timeout++;end
            if(stats_ready!==1'b1) $fatal(1,"RMS_ACTIVATION_STATS_TIMEOUT");
            @(negedge clk);#1;stats_valid=0;stats_data=~data;stats_last=!last;
        end
    endtask
    task automatic replay_word(input logic [255:0] packet,input bit last);
        int timeout;
        begin
            @(negedge clk);#1;replay_valid=1;replay_last=last;
            replay_data=packet[127:0];replay_gamma=packet[255:128];
            timeout=0;@(posedge clk);
            while(replay_ready!==1'b1 && timeout<200) begin @(posedge clk);timeout++;end
            if(replay_ready!==1'b1) $fatal(1,"RMS_ACTIVATION_REPLAY_TIMEOUT");
            @(negedge clk);#1;replay_valid=0;replay_data=~packet[127:0];
            replay_gamma=~packet[255:128];replay_last=!last;
        end
    endtask
    task automatic wait_frame(input int expected_count);
        int timeout;
        begin
            timeout=0;
            while(cfg_ready!==1'b1 && timeout<300) begin @(negedge clk);#1;timeout++;end
            if(cfg_ready!==1'b1 || checked!=expected_count)
                $fatal(1,"RMS_ACTIVATION_RESULT_TIMEOUT checked=%0d expected=%0d",checked,expected_count);
        end
    endtask
    task automatic vector_case(input int base,strips,shift,input logic [31:0] epsilon,tag,
        input int expected_count);
        begin
            configure(strips,shift,epsilon,tag);
            for(int k=0;k<strips;k++) stats_word(packets[base+k][127:0],k==strips-1);
            for(int k=0;k<strips;k++) replay_word(packets[base+k],k==strips-1);
            wait_frame(expected_count);
        end
    endtask
    task automatic reset_now;
        begin
            @(negedge clk);#1;rst_n=0;cfg_valid=0;stats_valid=0;replay_valid=0;
            repeat(2) @(negedge clk);#1;rst_n=1;force_stall=0;stalled=0;check_enabled=1;
            repeat(5) begin @(posedge clk);#1;
                if(out_valid || !cfg_ready || stats_ready || replay_ready)
                    $fatal(1,"RMS_ACTIVATION_RESET_LEFT_FRAME");end
        end
    endtask
    initial begin
        $readmemh("@PACKET_FILE@",packets,0,@DATA_WORDS@-1);
        $readmemh("@EXPECTED_FILE@",expected,0,@EXPECTED_WORDS@-1);
        repeat(2) @(negedge clk);#1;rst_n=1;
@BODY@
        if(checked!=@EXPECTED_WORDS@) $fatal(1,"RMS_ACTIVATION_MISSING_WORDS");
        $display("RMS_ACTIVATION_PASS words=%0d frames=%0d",checked,frames);$finish;
    end
    initial begin #5000000;$fatal(1,"RMS_ACTIVATION_GLOBAL_WATCHDOG");end
endmodule
'''


class RmsActivationTest(unittest.TestCase):
    def test_native_raw_residual_gamma_capture_errors_and_reset(self):
        rng = random.Random(316602)
        packets, expected, body = [], [], []
        tag = 0x80000000

        def append_expected(values, gamma, shift, epsilon, frame_tag,
                            prefix=None, error=False):
            codes = normalized_codes(values, epsilon) if prefix != 0 else []
            strips = len(values)//8
            limit = strips if prefix is None else prefix
            activations = []
            for index in range(limit):
                norm = sum((value & 0xffff) << (16*lane)
                           for lane, value in enumerate(codes[index*8:index*8+8]))
                mask = sum((abs(value) > 768) << lane
                           for lane, value in enumerate(codes[index*8:index*8+8]))
                output = [scaled_code(codes[index*8+lane], gamma[index*8+lane], shift)
                          for lane in range(8)]
                activations.extend(output)
                data = sum((value & 255) << (lane*8) for lane, value in enumerate(output))
                packet = frame_tag << 216 | index << 206 | 8 << 202
                packet |= int(index == strips-1 and not error) << 201
                packet |= norm << 72 | mask << 64 | data
                expected.append(packet)
            if error:
                expected.append(frame_tag << 216 | 1 << 201 | 1 << 200)
            return activations

        def fixture(values, gamma, shift=17, epsilon=0):
            nonlocal tag
            tag += 1
            self.assertEqual(len(values), len(gamma))
            base = len(packets)
            for start in range(0, len(values), 8):
                raw = sum((value & 0xffff) << (16*lane)
                          for lane, value in enumerate(values[start:start+8]))
                coefficients = sum((value & 0xffff) << (16*lane)
                                   for lane, value in enumerate(gamma[start:start+8]))
                packets.append(raw | coefficients << 128)
            return base, tag

        def valid_case(values, gamma, shift=17, epsilon=0):
            base, frame_tag = fixture(values, gamma, shift, epsilon)
            outputs = append_expected(values, gamma, shift, epsilon, frame_tag)
            body.append(f"        vector_case({base},{len(values)//8},{shift},"
                        f"32'h{epsilon:08x},32'h{frame_tag:08x},{len(expected)});")
            return {'tag': frame_tag, 'activation_codes': outputs,
                    'normalized_codes': normalized_codes(values, epsilon)}

        ones = [1]*8
        gamma_literal = [1, -1, 3, -3, 255, -257, 32767, -32768]
        first = valid_case(ones, gamma_literal, 9)
        self.assertEqual(first['activation_codes'], [1, -1, 2, -2, 127, -128, 127, -128])
        boundary = [1537, 1353, 36, 5, 2, 1]+[0]*10
        valid_case(boundary, [rng.randrange(-32768, 32768) for _ in boundary], 17)
        valid_case(boundary, [-32768]*16, 63, 1)
        valid_case([-32768]*4096, [-32768, 32767]*2048, 0)
        valid_case([32767]+[0]*4094+[-32768], [rng.randrange(-32768, 32768) for _ in range(4096)])
        valid_case([rng.randrange(-500, 501) for _ in range(2048)],
                   [rng.randrange(-32768, 32768) for _ in range(2048)], 17, 4295)
        self.extra_case_evidence = []
        for extra in getattr(self, 'extra_model_cases', []):
            self.extra_case_evidence.append(valid_case(**extra))
        held_values = [1]*32
        held_gamma = [1]*8+[3]*8+[-5]*8+[7]*8
        held_base, held_tag = fixture(held_values, held_gamma, 9)
        held_codes = append_expected(held_values, held_gamma, 9, 0, held_tag)
        self.assertEqual(held_codes, [1]*8+[2]*8+[-3]*8+[4]*8)
        body.extend([
            '        force_stall=1;',
            f"        configure(4,9,0,32'h{held_tag:08x});",
            f"        for(int k=0;k<4;k++) stats_word(packets[{held_base}+k][127:0],k==3);",
            f"        for(int k=0;k<3;k++) replay_word(packets[{held_base}+k],0);",
            '        repeat(45) @(negedge clk); #1;',
            '        if(!out_valid || replay_ready || cfg_ready)',
            '            $fatal(1,"RMS_ACTIVATION_FULL_CHAIN_STALL_NOT_REACHED");',
            '        force_stall=0;',
            f"        replay_word(packets[{held_base}+3],1);",
            f"        wait_frame({len(expected)});",
        ])
        # Error words occur after any already-consumed provisional prefix.
        base, frame_tag = fixture([16, -16]+[0]*30, [32767]*32)
        values, gamma = [16, -16]+[0]*30, [32767]*32
        append_expected(values, gamma, 17, 0, frame_tag, prefix=3, error=True)
        body.extend([
            f"        configure(4,17,0,32'h{frame_tag:08x});",
            f"        for(int k=0;k<4;k++) stats_word(packets[{base}+k][127:0],k==3);",
            f"        for(int k=0;k<4;k++) replay_word(packets[{base}+k]^256'(k==3),k==3);",
            f"        wait_frame({len(expected)});",
        ])
        for mode in ('early_stats', 'early_replay', 'late_replay', 'zero_denominator', 'invalid'):
            case_values = [0]*8 if mode == 'zero_denominator' else values
            case_gamma = [32767]*len(case_values)
            base, frame_tag = fixture(case_values, case_gamma)
            prefix = 3 if mode == 'late_replay' else 0
            append_expected(case_values, case_gamma, 17, 0, frame_tag, prefix=prefix, error=True)
            body.append(f"        configure({0 if mode=='invalid' else len(case_values)//8},17,0,32'h{frame_tag:08x});")
            if mode == 'early_stats':
                body.append(f"        stats_word(packets[{base}][127:0],1);")
            elif mode != 'invalid':
                body.append(f"        for(int k=0;k<{len(case_values)//8};k++) "
                            f"stats_word(packets[{base}+k][127:0],k=={len(case_values)//8-1});")
                if mode == 'early_replay':
                    body.append(f"        replay_word(packets[{base}],1);")
                elif mode == 'late_replay':
                    body.extend([f"        for(int k=0;k<4;k++) replay_word(packets[{base}+k],0);",
                                 "        repeat(6) @(negedge clk);",
                                 f"        replay_word(packets[{base}],1);"])
            body.append(f"        wait_frame({len(expected)});")
        # Abort a search before output and clear a held final result.
        abort_base, abort_tag = fixture(values, gamma)
        body.extend([
            "        check_enabled=0;",
            f"        configure(4,17,0,32'h{abort_tag:08x});",
            f"        for(int k=0;k<4;k++) stats_word(packets[{abort_base}+k][127:0],k==3);",
            f"        replay_word(packets[{abort_base}],0); repeat(4) @(negedge clk);",
            "        reset_now();",
        ])
        valid_case(ones, gamma_literal, 9)
        held_base, held_tag = fixture(ones, gamma_literal, 9)
        body.extend([
            "        check_enabled=0;force_stall=1;",
            f"        configure(1,9,0,32'h{held_tag:08x});",
            f"        stats_word(packets[{held_base}][127:0],1);",
            f"        replay_word(packets[{held_base}],1);",
            "        begin int t;t=0;while(!out_valid && t<200) begin",
            "            @(negedge clk);#1;t++;end",
            "            if(!out_valid) $fatal(1,\"RMS_ACTIVATION_HELD_RESET_NOT_REACHED\");end",
            "        reset_now();",
        ])
        valid_case(ones, gamma_literal, 9)
        available = int(next(line.split()[1] for line in
                             Path('/proc/meminfo').read_text().splitlines()
                             if line.startswith('MemAvailable:')))*1024
        self.assertGreaterEqual(available, 8*1024**3)

        def bounded():
            resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))

        with tempfile.TemporaryDirectory(prefix='rms_activation_test_', dir='.cache') as directory:
            root = Path(directory); packet_file = root/'packets.memh'; expected_file = root/'expected.memh'
            packet_file.write_text(''.join(f'{packet:064x}\n' for packet in packets))
            expected_file.write_text(''.join(f'{packet:062x}\n' for packet in expected))
            bench = root/'bench.sv'
            bench.write_text(BENCH.replace('@DATA_WORDS@', str(len(packets)))
                             .replace('@EXPECTED_WORDS@', str(len(expected)))
                             .replace('@PACKET_FILE@', str(packet_file))
                             .replace('@EXPECTED_FILE@', str(expected_file))
                             .replace('@BODY@', '\n'.join(body)))
            binary = root/'rms_activation.vvp'
            compiled = subprocess.run([
                'iverilog', '-g2012', '-s', 'tri_oracle_rms_activation_tb', '-o', str(binary),
                'verilog/tri_oracle_rmsnorm.sv', 'verilog/tri_oracle_affine_quantizer.sv',
                getattr(self, 'source_path', 'verilog/tri_oracle_rms_activation.sv'), str(bench)],
                text=True, capture_output=True, timeout=60, preexec_fn=bounded)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run(['vvp', str(binary)], text=True,
                                    capture_output=True, timeout=120, preexec_fn=bounded)
        self.assertFalse(root.exists())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(result.stdout.count('RMS_ACTIVATION_PASS'), 1)
        self.native_stdout = result.stdout


if __name__ == '__main__':
    unittest.main()
