"""Native hardware checks against independent high-precision normalization."""
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction
from math import isqrt
from pathlib import Path
import random
import resource
import subprocess
import tempfile
import unittest


def normalized_codes(values, epsilon):
    energy = sum(value*value for value in values)
    squared_divisor = Fraction(energy, len(values))+Fraction(epsilon, 65536)
    if not squared_divisor:
        raise ValueError("Undefined zero-energy, zero-epsilon normalization")
    numerator_root = isqrt(squared_divisor.numerator)
    denominator_root = isqrt(squared_divisor.denominator)
    if (numerator_root*numerator_root == squared_divisor.numerator and
            denominator_root*denominator_root == squared_divisor.denominator):
        # Exact rational roots also cover half-code ties for non-power-of-two
        # vector lengths, without relying on finite Decimal sqrt rounding.
        return [(-1 if value < 0 else 1)*(
            (2*abs(value)*256*denominator_root+numerator_root)//(2*numerator_root))
            for value in values]
    with localcontext() as context:
        context.prec = 100
        divisor = (Decimal(energy)/len(values)+Decimal(epsilon)/65536).sqrt()
        return [(-1 if value < 0 else 1)*int(
            (Decimal(abs(value))*256/divisor).to_integral_value(rounding=ROUND_HALF_UP))
            for value in values]


BENCH = r'''`timescale 1ns/1ps
module tri_oracle_rmsnorm_tb;
    localparam int DataWords = @DATA_WORDS@;
    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, cfg_valid = 0, cfg_ready;
    logic [31:0] cfg_tag = 0, cfg_epsilon_q16 = 0, expected_tag = 0;
    logic [9:0] cfg_strips = 0;
    logic stats_valid = 0, stats_ready, stats_last = 0;
    logic [127:0] stats_data = 0;
    logic replay_valid = 0, replay_ready, replay_last = 0;
    logic [127:0] replay_data = 0;
    logic out_valid, out_ready = 0, out_last, out_error;
    logic [31:0] out_tag;
    logic [9:0] out_index;
    logic [3:0] out_count;
    logic [127:0] out_norm_q8;
    logic [7:0] out_outlier_mask;
    logic [127:0] input_words [0:DataWords-1];
    logic [135:0] expected_words [0:DataWords-1];
    int outputs_checked = 0;
    tri_oracle_rmsnorm dut (.*);

    task automatic configure(input int strips, input logic [31:0] epsilon, tag);
        int timeout;
        begin
            @(negedge clk);
            cfg_valid = 1; cfg_tag = tag; expected_tag = tag;
            cfg_strips = 10'(strips); cfg_epsilon_q16 = epsilon;
            timeout = 0;
            @(posedge clk);
            while (cfg_ready !== 1'b1 && timeout < 100) begin
                @(posedge clk); timeout++;
            end
            if (cfg_ready !== 1'b1) $fatal(1,"RMS_CONFIG_TIMEOUT");
            @(negedge clk);
            cfg_valid = 0; cfg_tag = 0; cfg_strips = 0; cfg_epsilon_q16 = '1;
        end
    endtask

    task automatic stats_word(input logic [127:0] value, input bit last);
        int timeout;
        begin
            @(negedge clk); stats_valid = 1; stats_last = last; stats_data = value;
            timeout = 0; @(posedge clk);
            while (stats_ready !== 1'b1 && timeout < 100) begin
                @(posedge clk); timeout++;
            end
            if (stats_ready !== 1'b1) $fatal(1,"RMS_STATS_TIMEOUT");
            @(negedge clk); stats_valid = 0; stats_data = ~value; stats_last = !last;
        end
    endtask

    task automatic replay_word(input logic [127:0] value, input bit last);
        int timeout;
        begin
            @(negedge clk); replay_valid = 1; replay_last = last; replay_data = value;
            timeout = 0; @(posedge clk);
            while (replay_ready !== 1'b1 && timeout < 100) begin
                @(posedge clk); timeout++;
            end
            if (replay_ready !== 1'b1) $fatal(1,"RMS_REPLAY_TIMEOUT");
            @(negedge clk);
            replay_valid = 0; replay_data = ~value; replay_last = !last;
        end
    endtask

    task automatic receive_word(
        input int index,
        input logic [135:0] expected,
        input bit last, error
    );
        int timeout;
        logic [183:0] held;
        begin
            timeout = 0;
            while (out_valid !== 1'b1 && timeout < 100) begin
                @(negedge clk); timeout++;
            end
            if (out_valid !== 1'b1) $fatal(1,"RMS_RESULT_TIMEOUT");
            if ({out_tag,out_index,out_count,out_last,out_error} !==
                {expected_tag,10'(index),4'(error ? 0 : 8),last,error})
                $fatal(1,"RMS_METADATA_MISMATCH tag=%h index=%0d",out_tag,out_index);
            if ({out_outlier_mask,out_norm_q8} !== expected)
                $fatal(1,"RMS_VALUE_MISMATCH tag=%h index=%0d got=%h expected=%h",
                    out_tag,index,{out_outlier_mask,out_norm_q8},expected);
            held = {out_tag,out_index,out_count,out_last,out_error,
                out_outlier_mask,out_norm_q8};
            cfg_valid = 1; cfg_tag = 32'hdeadbeef; cfg_strips = '1;
            repeat (4) begin
                @(posedge clk); #1;
                if (out_valid !== 1'b1 || cfg_ready || stats_ready || replay_ready ||
                    {out_tag,out_index,out_count,out_last,out_error,
                        out_outlier_mask,out_norm_q8} !== held)
                    $fatal(1,"RMS_OUTPUT_STALL_CHANGED_TRANSACTION");
            end
            @(negedge clk); cfg_valid = 0; out_ready = 1;
            @(negedge clk); out_ready = 0;
            outputs_checked++;
        end
    endtask

    task automatic vector_case(
        input int base, strips,
        input logic [31:0] epsilon, tag
    );
        begin
            configure(strips,epsilon,tag);
            for (int packet = 0; packet < strips; packet++)
                stats_word(input_words[base+packet],packet == strips-1);
            for (int packet = 0; packet < strips; packet++) begin
                replay_word(input_words[base+packet],packet == strips-1);
                receive_word(packet,expected_words[base+packet],packet == strips-1,0);
            end
            $display("RMS_VECTOR_PASS tag=%h strips=%0d",tag,strips);
        end
    endtask

    initial begin
        $readmemh("@INPUT_FILE@",input_words,0,DataWords-1);
        $readmemh("@EXPECTED_FILE@",expected_words,0,DataWords-1);
        repeat (2) @(negedge clk); rst_n = 1;
@BODY@
        $display("RMS_NORMALIZER_PASS outputs=%0d",outputs_checked);
        $finish;
    end
    initial begin #2000000; $fatal(1,"RMS_GLOBAL_WATCHDOG"); end
endmodule
'''


class RmsNormalizerTest(unittest.TestCase):
    def test_native_values_boundaries_framing_stalls_and_reset(self):
        # Changing comparison >= to > loses the exact half-code boundaries;
        # dropping the last search update or truncating x*x also breaks these.
        boundary = [1537, 1353, 36, 5, 2, 1]+[0]*10
        self.assertEqual(normalized_codes(boundary, 0)[:6], [769, 677, 18, 3, 1, 1])
        self.assertEqual(normalized_codes(boundary, 1)[:6], [768, 676, 18, 2, 1, 0])
        rational_ties = [1, 1448, 21, 2, 1, 1]+[0]*386
        self.assertEqual(normalized_codes(rational_ties, 0)[:6], [4, 5068, 74, 7, 4, 4])
        rng = random.Random(31865)
        cases = [
            ([1]*8, 0),
            ([1]*16, 0),
            (boundary, 0),
            (boundary, 1),
            ([-value for value in boundary], 0),
            ([3]+[1]*7+[0]*8, 0),
            ([0]*8, 1),
            ([rng.randrange(-32768, 32768) for _ in range(152)], 4295),
            ([rng.randrange(-500, 501) for _ in range(2048)], 0xffffffff),
            ([-32768]*4096, 0),
            ([32767]+[0]*4095, 0),
            ([-32768]+[0]*4095, 0),
            (rational_ties, 0),
        ]
        input_words, expected_words, body = [], [], []
        bases = []
        for number, (values, epsilon) in enumerate(cases):
            normalized = normalized_codes(values, epsilon)
            base = len(input_words); strips = len(values)//8; bases.append(base)
            for start in range(0, len(values), 8):
                input_words.append(sum((value & 0xffff) << (16*lane)
                                       for lane, value in enumerate(values[start:start+8])))
                codes = normalized[start:start+8]
                mask = sum((abs(value) > 768) << lane for lane, value in enumerate(codes))
                expected_words.append(sum((value & 0xffff) << (16*lane)
                                          for lane, value in enumerate(codes)) | (mask << 128))
            body.append(f"        vector_case({base},{strips},32'h{epsilon:08x},32'h{number+1:08x});")
        ones, twice, zero = bases[0], bases[1], bases[6]
        body.extend([
            "        configure(0,0,32'h100); receive_word(0,0,1,1);",
            "        configure(513,0,32'h101); receive_word(0,0,1,1);",
            f"        configure(1,0,32'h102); stats_word(input_words[{zero}],1);",
            "        receive_word(0,0,1,1);",
            f"        configure(2,0,32'h103); stats_word(input_words[{ones}],1);",
            "        receive_word(0,0,1,1);",
            f"        configure(1,0,32'h104); stats_word(input_words[{ones}],0);",
            f"        stats_word(input_words[{ones}],1); receive_word(0,0,1,1);",
            f"        configure(2,0,32'h105); stats_word(input_words[{twice}],0);",
            f"        stats_word(input_words[{twice+1}],1); replay_word(input_words[{twice}],1);",
            "        receive_word(0,0,1,1);",
            f"        configure(1,0,32'h106); stats_word(input_words[{ones}],1);",
            f"        replay_word(input_words[{ones}],0); replay_word(input_words[{ones}],1);",
            "        receive_word(0,0,1,1);",
            f"        configure(2,0,32'h107); stats_word(input_words[{twice}],0);",
            f"        stats_word(input_words[{twice+1}],1); replay_word(input_words[{twice}],0);",
            f"        receive_word(0,expected_words[{twice}],0,0);",
            f"        replay_word(input_words[{twice+1}] ^ 128'd1,1); receive_word(0,0,1,1);",
            f"        configure(1,0,32'h108); stats_word(input_words[{ones}],1);",
            f"        replay_word(input_words[{ones}],1); repeat(5) @(negedge clk);",
            "        rst_n=0; repeat(2) @(negedge clk); rst_n=1;",
            "        repeat(20) begin @(negedge clk);",
            "            if(out_valid || !cfg_ready) $fatal(1,\"RMS_RESET_DID_NOT_CLEAR\"); end",
            f"        vector_case({ones},1,0,32'h109);",
            f"        configure(1,0,32'h110); stats_word(input_words[{ones}],1);",
            f"        replay_word(input_words[{ones}],1);",
            "        begin int timeout; timeout=0;",
            "            while(out_valid!==1'b1 && timeout<100) begin",
            "                @(negedge clk); timeout++; end",
            "            if(out_valid!==1'b1) $fatal(1,\"RMS_HELD_RESULT_MISSING\"); end",
            "        rst_n=0; repeat(2) @(negedge clk); rst_n=1;",
            "        repeat(20) begin @(negedge clk);",
            "            if(out_valid || !cfg_ready) $fatal(1,\"RMS_HELD_RESET_FAILED\"); end",
            f"        vector_case({ones},1,0,32'h111);",
        ])
        available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                             if line.startswith('MemAvailable:')))*1024
        self.assertGreaterEqual(available, 6*1024**3)
        def bounded():
            resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
        with tempfile.TemporaryDirectory(prefix='rmsnorm_test_', dir='.cache') as directory:
            root = Path(directory)
            input_file, expected_file = root/'input.memh', root/'expected.memh'
            input_file.write_text(''.join(f'{word:032x}\n' for word in input_words))
            expected_file.write_text(''.join(f'{word:034x}\n' for word in expected_words))
            bench = root/'bench.sv'
            text = BENCH.replace('@DATA_WORDS@', str(len(input_words)))
            text = text.replace('@INPUT_FILE@', str(input_file))
            text = text.replace('@EXPECTED_FILE@', str(expected_file))
            bench.write_text(text.replace('@BODY@', '\n'.join(body)))
            binary = root/'rmsnorm.vvp'
            compile_result = subprocess.run([
                'iverilog', '-g2012', '-s', 'tri_oracle_rmsnorm_tb', '-o', str(binary),
                getattr(self, 'normalizer_source_path', 'verilog/tri_oracle_rmsnorm.sv'),
                str(bench)],
                capture_output=True, text=True, timeout=60, preexec_fn=bounded)
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            result = subprocess.run(['vvp', str(binary)], capture_output=True, text=True,
                                    timeout=120, preexec_fn=bounded)
        self.assertFalse(root.exists())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(result.stdout.count('RMS_NORMALIZER_PASS'), 1)
        self.assertEqual(result.stdout.count('RMS_VECTOR_PASS'), len(cases)+2)


if __name__ == '__main__':
    unittest.main()
