"""Native signed learned-scale arithmetic, elastic flow and reset checks.

Unsigned products, asymmetric negative ties, overflowed rounding bias, stale
metadata during stalls or a pipeline word surviving reset must fail this test.
"""
from pathlib import Path
import random
import resource
import subprocess
import tempfile
import unittest


def scaled_code(normalized, gamma, shift):
    product = normalized*gamma
    magnitude = abs(product)
    quotient, remainder = divmod(magnitude, 1 << shift)
    if shift and 2*remainder >= 1 << shift:
        quotient += 1
    signed = -quotient if product < 0 else quotient
    return max(-128, min(127, signed))


BENCH = r'''`timescale 1ns/1ps
module tri_oracle_affine_quantizer_tb;
    logic clk=0;
    always #5 clk=~clk;
    logic rst_n=0,in_valid=0,in_ready,in_last=0,in_error=0;
    logic [31:0] in_tag=0;
    logic [9:0] in_index=0;
    logic [3:0] in_count=8;
    logic [127:0] in_norm_q8=0,in_gamma=0;
    logic [5:0] in_shift=0;
    logic [7:0] in_outlier_mask=0;
    logic out_valid,out_ready=0,out_last,out_error;
    logic [31:0] out_tag;
    logic [9:0] out_index;
    logic [3:0] out_count;
    logic [127:0] out_norm_q8;
    logic [7:0] out_outlier_mask;
    logic [63:0] out_activation;
    logic [247:0] expected [0:@CASES@-1];
    logic [247:0] held;
    int checked=0,cycle=0,input_run=0,output_run=0,longest_input_run=0,longest_output_run=0;
    bit stalled=0,force_stall=0,check_enabled=1,full_rate=1;
    tri_oracle_affine_quantizer dut (.*);
    always @(negedge clk) begin
        cycle++;
        out_ready=!force_stall && (full_rate || cycle%9<4);
    end
    always @(posedge clk) if(rst_n && check_enabled) begin
        input_run=in_valid && in_ready ? input_run+1 : 0;
        output_run=out_valid && out_ready ? output_run+1 : 0;
        if(input_run>longest_input_run) longest_input_run=input_run;
        if(output_run>longest_output_run) longest_output_run=output_run;
        if(stalled && (!out_valid || {out_tag,out_index,out_count,out_last,out_error,
            out_norm_q8,out_outlier_mask,out_activation}!==held))
            $fatal(1,"AFFINE_HELD_OUTPUT_CHANGED");
        stalled=out_valid && !out_ready;
        held={out_tag,out_index,out_count,out_last,out_error,
            out_norm_q8,out_outlier_mask,out_activation};
        if(out_valid && out_ready) begin
            if(checked>=@CASES@ || held!==expected[checked])
                $fatal(1,"AFFINE_RESULT_MISMATCH word=%0d tag=%h activation=%h",
                    checked,out_tag,out_activation);
            checked++;
        end
    end
    task automatic send_word(
        input logic [31:0] tag,
        input int index,count,shift,
        input bit last,error,
        input logic [127:0] normalized,gamma,
        input logic [7:0] outliers
    );
        int timeout;
        begin
            @(negedge clk);#1;in_valid=1;in_tag=tag;in_index=10'(index);
            in_count=4'(count);in_shift=6'(shift);in_last=last;in_error=error;
            in_norm_q8=normalized;in_gamma=gamma;in_outlier_mask=outliers;
            timeout=0;@(posedge clk);
            while(in_ready!==1'b1 && timeout<100) begin @(posedge clk);timeout++;end
            if(in_ready!==1'b1) $fatal(1,"AFFINE_INPUT_TIMEOUT");
            #1;in_valid=0;in_tag=~tag;in_index='1;in_count=0;
            in_shift='1;in_norm_q8=~normalized;in_gamma=~gamma;
            in_last=!last;in_error=!error;in_outlier_mask=~outliers;
        end
    endtask
    task automatic wait_checked(input int count);
        int timeout;
        begin
            timeout=0;
            while(checked<count && timeout<200) begin @(negedge clk);#1;timeout++;end
            if(checked!=count) $fatal(1,"AFFINE_RESULT_TIMEOUT checked=%0d",checked);
        end
    endtask
    initial begin
        $readmemh("@EXPECTED_FILE@",expected,0,@CASES@-1);
        repeat(2) @(negedge clk);#1;rst_n=1;
@BODY@
        wait_checked(@CASES@);
        if(longest_input_run<8 || longest_output_run<8)
            $fatal(1,"AFFINE_FULL_RATE_NOT_PROVEN input=%0d output=%0d",
                longest_input_run,longest_output_run);
        $display("AFFINE_QUANTIZER_PASS words=%0d consecutive_inputs=%0d consecutive_outputs=%0d",
            checked,longest_input_run,longest_output_run);$finish;
    end
    initial begin #1000000;$fatal(1,"AFFINE_GLOBAL_WATCHDOG");end
endmodule
'''


class AffineQuantizerTest(unittest.TestCase):
    def test_native_signed_rounding_elastic_metadata_and_reset(self):
        rng = random.Random(316601)
        cases = []
        boundary = ([256]*8, [1, -1, 3, -3, 255, -257, 32767, -32768], 9)
        self.assertEqual([scaled_code(n, g, 9) for n, g in zip(*boundary[:2])],
                         [1, -1, 2, -2, 127, -128, 127, -128])
        cases.append((*boundary, 8, False, False))
        cases.append(([-32768, -32768, 32767, 32767, 0, 1, -1, 128],
                      [-32768, 32767, -32768, 32767, -32768, -1, -1, 1],
                      0, 8, True, False))
        for shift in (1, 7, 8, 15, 17, 30, 31, 32, 62, 63):
            cases.append(([-32768, -32767, -769, -1, 0, 1, 769, 32767],
                          [32767, -32768, -1, 32767, -32768, -32768, 1, 32767],
                          shift, 8, bool(shift%2), False))
        for _ in range(60):
            cases.append(([rng.randrange(-32768, 32768) for _ in range(8)],
                          [rng.randrange(-32768, 32768) for _ in range(8)],
                          rng.randrange(64), 8, bool(rng.randrange(2)), False))
        for count, error in ((0, False), (7, False), (9, False), (15, False), (8, True)):
            cases.append(([1024]*8, [32767]*8, 17, count, False, error))
        cases.append((*boundary, 8, True, False))
        body, expected = [], []
        for number, (normalized, gamma, shift, count, last, error) in enumerate(cases):
            if number == 12:
                body.append('        full_rate=0;')
            raw = sum((value & 0xffff) << (16*lane) for lane, value in enumerate(normalized))
            coefficients = sum((value & 0xffff) << (16*lane) for lane, value in enumerate(gamma))
            outliers = sum((abs(value) > 768) << lane for lane, value in enumerate(normalized))
            failed = error or count != 8
            data = 0 if failed else sum((scaled_code(n, g, shift) & 255) << (8*lane)
                                       for lane, (n, g) in enumerate(zip(normalized, gamma)))
            tag = 0x80000000+number
            index = (number*17)%512
            packet = (tag << 216) | (index << 206) | ((0 if failed else 8) << 202)
            packet |= int(last or failed) << 201 | int(failed) << 200
            packet |= (0 if failed else raw) << 72 | (0 if failed else outliers) << 64 | data
            expected.append(packet)
            if number == len(cases)-1:
                body.extend([
                    f"        wait_checked({number}); check_enabled=0; force_stall=1;",
                    "        send_word(32'hbad,1,8,17,1,0,{8{16'd256}},{8{16'd128}},0);",
                    "        send_word(32'hbad1,2,8,17,1,0,{8{16'd256}},{8{16'd128}},0);",
                    "        repeat(4) @(negedge clk); #1;",
                    "        if(!out_valid || in_ready) $fatal(1,\"AFFINE_RESET_STAGES_NOT_FULL\");",
                    "        rst_n=0; repeat(2) @(negedge clk); #1; rst_n=1;",
                    "        force_stall=0; stalled=0; check_enabled=1;",
                    "        repeat(4) begin @(posedge clk); #1;",
                    "            if(out_valid || !in_ready) $fatal(1,\"AFFINE_RESET_LEFT_WORD\");end",
                ])
            body.append(f"        send_word(32'h{tag:08x},{index},{count},{shift},"
                        f"1'b{int(last)},1'b{int(error)},128'h{raw:032x},"
                        f"128'h{coefficients:032x},8'h{outliers:02x});")
        available = int(next(line.split()[1] for line in
                             Path('/proc/meminfo').read_text().splitlines()
                             if line.startswith('MemAvailable:')))*1024
        self.assertGreaterEqual(available, 8*1024**3)

        def bounded():
            resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))

        with tempfile.TemporaryDirectory(prefix='affine_quantizer_test_', dir='.cache') as directory:
            root = Path(directory); expected_file = root/'expected.memh'
            expected_file.write_text(''.join(f'{packet:062x}\n' for packet in expected))
            bench = root/'bench.sv'
            bench.write_text(BENCH.replace('@CASES@', str(len(cases)))
                             .replace('@EXPECTED_FILE@', str(expected_file))
                             .replace('@BODY@', '\n'.join(body)))
            binary = root/'affine.vvp'
            compiled = subprocess.run([
                'iverilog', '-g2012', '-s', 'tri_oracle_affine_quantizer_tb', '-o', str(binary),
                getattr(self, 'source_path', 'verilog/tri_oracle_affine_quantizer.sv'), str(bench)],
                text=True, capture_output=True, timeout=60, preexec_fn=bounded)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run(['vvp', str(binary)], text=True,
                                    capture_output=True, timeout=60, preexec_fn=bounded)
        self.assertFalse(root.exists())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(result.stdout.count('AFFINE_QUANTIZER_PASS'), 1)
        self.native_stdout = result.stdout


if __name__ == '__main__':
    unittest.main()
