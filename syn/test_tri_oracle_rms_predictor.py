"""Exercise the real normalization/prediction pipeline and late-fault commit."""
from pathlib import Path
import random
import resource
import subprocess
import tempfile
import unittest

from test_tri_oracle_rmsnorm import normalized_codes


BENCH = r'''`timescale 1ns/1ps
module tri_oracle_rms_predictor_tb;
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
    logic [255:0] replay_gate_signs = 0, replay_up_signs = 0;
    logic out_valid, out_ready = 0, out_error;
    logic [31:0] out_tag, gate_nearzero_mask, up_nearzero_mask, skip_mask;
    logic [12:0] outlier_count;
    logic [639:0] packets [0:DataWords-1];
    bit allow_result = 0;
    int checked = 0;
    tri_oracle_rms_predictor dut (.*);
    always @(posedge clk)
        if (rst_n && out_valid && !allow_result)
            $fatal(1,"PREDICTION_PUBLISHED_BEFORE_TERMINAL_REPLAY");

    task automatic configure(
        input int strips,
        input logic [31:0] epsilon, tag,
        input bit may_finish_without_replay = 0
    );
        int timeout;
        begin
            @(negedge clk); cfg_valid = 1; cfg_tag = tag; expected_tag = tag;
            cfg_strips = 10'(strips); cfg_epsilon_q16 = epsilon;
            allow_result = may_finish_without_replay;
            timeout = 0; @(posedge clk);
            while (cfg_ready !== 1'b1 && timeout < 100) begin
                @(posedge clk); timeout++;
            end
            if (cfg_ready !== 1'b1) $fatal(1,"PRED_CONFIG_TIMEOUT");
            @(negedge clk); cfg_valid = 0; cfg_tag = 0; cfg_strips = '1;
            cfg_epsilon_q16 = '1;
        end
    endtask

    task automatic stats_word(input logic [127:0] data, input bit last);
        int timeout;
        begin
            @(negedge clk); stats_valid = 1; stats_last = last; stats_data = data;
            timeout = 0; @(posedge clk);
            while (stats_ready !== 1'b1 && timeout < 100) begin
                @(posedge clk); timeout++;
            end
            if (stats_ready !== 1'b1) $fatal(1,"PRED_STATS_TIMEOUT");
            @(negedge clk); stats_valid = 0; stats_data = ~data; stats_last = !last;
        end
    endtask

    task automatic replay_word(input logic [639:0] packet, input bit last);
        int timeout;
        begin
            @(negedge clk); replay_valid = 1; replay_last = last;
            replay_data = packet[127:0];
            replay_gate_signs = packet[383:128]; replay_up_signs = packet[639:384];
            timeout = 0; @(posedge clk);
            while (replay_ready !== 1'b1 && timeout < 100) begin
                @(posedge clk); timeout++;
            end
            if (replay_ready !== 1'b1) $fatal(1,"PRED_REPLAY_TIMEOUT");
            @(negedge clk); replay_valid = 0; replay_data = ~packet[127:0];
            replay_gate_signs = ~packet[383:128]; replay_up_signs = ~packet[639:384];
            replay_last = !last;
            if (last) allow_result = 1;
        end
    endtask

    task automatic receive_mask(
        input logic [31:0] gate_mask, up_mask, skipped,
        input int outliers,
        input bit error
    );
        int timeout;
        logic [141:0] held;
        begin
            timeout = 0;
            while (out_valid !== 1'b1 && timeout < 100) begin
                @(negedge clk); timeout++;
            end
            if (out_valid !== 1'b1) $fatal(1,"RMS_PREDICTION_TIMEOUT");
            if ({out_tag,out_error,outlier_count,gate_nearzero_mask,up_nearzero_mask,skip_mask}
                !== {expected_tag,error,13'(outliers),gate_mask,up_mask,skipped})
                $fatal(1,"RMS_PREDICTION_MISMATCH tag=%h error=%b count=%0d skip=%h",
                    out_tag,out_error,outlier_count,skip_mask);
            held = {out_tag,out_error,outlier_count,
                gate_nearzero_mask,up_nearzero_mask,skip_mask};
            cfg_valid = 1; cfg_tag = 32'hbad; cfg_strips = 0;
            repeat (5) begin
                @(posedge clk); #1;
                if (out_valid !== 1'b1 || cfg_ready || stats_ready || replay_ready ||
                    {out_tag,out_error,outlier_count,
                        gate_nearzero_mask,up_nearzero_mask,skip_mask} !== held)
                    $fatal(1,"PRED_STALL_CHANGED_TRANSACTION");
            end
            @(negedge clk); cfg_valid = 0; out_ready = 1;
            @(negedge clk); out_ready = 0; checked++;
        end
    endtask

    task automatic vector_case(
        input int base, strips,
        input logic [31:0] epsilon, tag, gate_mask, up_mask, skipped,
        input int outliers
    );
        begin
            configure(strips,epsilon,tag);
            for (int packet = 0; packet < strips; packet++)
                stats_word(packets[base+packet][127:0],packet == strips-1);
            for (int packet = 0; packet < strips; packet++)
                replay_word(packets[base+packet],packet == strips-1);
            receive_mask(gate_mask,up_mask,skipped,outliers,0);
        end
    endtask

    initial begin
        $readmemh("@PACKET_FILE@",packets,0,DataWords-1);
        repeat (2) @(negedge clk); rst_n = 1;
@BODY@
        $display("RMS_PREDICTOR_PASS frames=%0d",checked); $finish;
    end
    initial begin #2000000; $fatal(1,"PRED_GLOBAL_WATCHDOG"); end
endmodule
'''


class RmsPredictorTest(unittest.TestCase):
    def test_native_masks_captured_signs_late_fault_and_recovery(self):
        rng = random.Random(3165)
        boundary = [1537, 1353, 36, 5, 2, 1]+[0]*10
        vectors = [([16, -16]+[0]*30, 0), ([1]*8, 0), (boundary, 0),
                   (boundary, 1), ([4000]+[0]*150+[-3000], 0),
                   ([rng.randrange(-500, 501) for _ in range(2048)], 4295),
                   ([32767]+[0]*4094+[-32768], 0)]
        packets, body, bases, decisions = [], [], [], []
        for number, (values, epsilon) in enumerate(vectors):
            codes = normalized_codes(values, epsilon)
            active = [i for i, code in enumerate(codes) if abs(code) > 768]
            signs = [[[rng.randrange(2) for _ in values] for _ in range(32)]
                     for _ in range(2)]
            if number == 0:
                for row, pair in enumerate([(0, 1), (1, 0), (0, 0), (1, 0), (0, 1)]):
                    signs[0][row][:2] = pair
                for row, pair in enumerate([(0, 1), (0, 0), (0, 0), (0, 1), (0, 0)]):
                    signs[1][row][:2] = pair
            gate_mask = up_mask = 0
            for channel in range(32):
                margins = [sum(1 if (codes[i] < 0) == matrix[channel][i] else -1
                               for i in active) for matrix in signs]
                gate_mask |= bool(active and margins[0] <= 0) << channel
                up_mask |= bool(active and margins[1] == 0) << channel
            skipped = gate_mask & up_mask
            if number == 0:
                self.assertEqual((gate_mask & 31, up_mask & 31, skipped & 31), (14, 22, 6))
                self.assertEqual(len(active), 2)
            base = len(packets); bases.append(base)
            for start in range(0, len(values), 8):
                raw = sum((value & 0xffff) << (16*lane)
                          for lane, value in enumerate(values[start:start+8]))
                matrices = [sum(matrix[channel][start+lane] << (channel*8+lane)
                                for channel in range(32) for lane in range(8)) for matrix in signs]
                packets.append(raw | (matrices[0] << 128) | (matrices[1] << 384))
            decisions.append((gate_mask, up_mask, skipped, len(active)))
            body.append(f"        vector_case({base},{len(values)//8},32'h{epsilon:08x},"
                        f"32'h{number+1:08x},32'h{gate_mask:08x},32'h{up_mask:08x},"
                        f"32'h{skipped:08x},{len(active)});")
        first, ones = bases[0], bases[1]
        body.extend([
            "        configure(0,0,32'h100,1); receive_mask(0,0,0,0,1);",
            "        configure(513,0,32'h101,1); receive_mask(0,0,0,0,1);",
            f"        configure(2,0,32'h102,1); stats_word(packets[{ones}][127:0],1);",
            "        receive_mask(0,0,0,0,1);",
            f"        configure(4,0,32'h103);",
            f"        for(int k=0;k<4;k++) stats_word(packets[{first}+k][127:0],k==3);",
            f"        for(int k=0;k<3;k++) replay_word(packets[{first}+k],0);",
            f"        replay_word(packets[{first}+3] ^ 640'd1,1);",
            "        receive_mask(0,0,0,0,1);",
            f"        vector_case({ones},1,0,32'h104,0,0,0,0);",
            f"        configure(4,0,32'h105);",
            f"        for(int k=0;k<4;k++) stats_word(packets[{first}+k][127:0],k==3);",
            f"        replay_word(packets[{first}],0); repeat(5) @(negedge clk);",
            "        rst_n=0; repeat(2) @(negedge clk); rst_n=1;",
            "        repeat(20) begin @(negedge clk);",
            "            if(out_valid || !cfg_ready) $fatal(1,\"PRED_RESET_DID_NOT_CLEAR\"); end",
            f"        vector_case({first},4,0,32'h106,32'h{decisions[0][0]:08x},"
            f"32'h{decisions[0][1]:08x},32'h{decisions[0][2]:08x},2);",
            f"        configure(4,0,32'h107);",
            f"        for(int k=0;k<4;k++) stats_word(packets[{first}+k][127:0],k==3);",
            f"        replay_word(packets[{first}],0); replay_word(packets[{first}+1],0);",
            "        repeat(5) @(negedge clk); rst_n=0;",
            "        repeat(2) @(negedge clk); rst_n=1;",
            "        repeat(20) begin @(negedge clk);",
            "            if(out_valid || !cfg_ready) $fatal(1,\"PRED_PARTIAL_RESET_FAILED\"); end",
            f"        vector_case({ones},1,0,32'h108,0,0,0,0);",
            f"        configure(4,0,32'h109);",
            f"        for(int k=0;k<4;k++) stats_word(packets[{first}+k][127:0],k==3);",
            f"        for(int k=0;k<4;k++) replay_word(packets[{first}+k],k==3);",
            "        begin int timeout; timeout=0;",
            "            while(out_valid!==1'b1 && timeout<100) begin",
            "                @(negedge clk); timeout++; end",
            f"            if(out_valid!==1'b1 || skip_mask!==32'h{decisions[0][2]:08x})",
            "                $fatal(1,\"PRED_HELD_RESULT_MISSING\"); end",
            "        rst_n=0; repeat(2) @(negedge clk); rst_n=1;",
            "        repeat(20) begin @(negedge clk);",
            "            if(out_valid || !cfg_ready) $fatal(1,\"PRED_HELD_RESET_FAILED\"); end",
            f"        vector_case({ones},1,0,32'h110,0,0,0,0);",
            f"        configure(1,0,32'h111,1); stats_word(packets[{ones}][127:0],0);",
            "        repeat(6) begin @(negedge clk);",
            "            if(out_valid || cfg_ready) $fatal(1,\"PRED_STATS_DRAIN_EARLY\"); end",
            f"        stats_word(packets[{ones}][127:0],1); receive_mask(0,0,0,0,1);",
            f"        configure(4,0,32'h112);",
            f"        for(int k=0;k<4;k++) stats_word(packets[{first}+k][127:0],k==3);",
            f"        for(int k=0;k<4;k++) replay_word(packets[{first}+k],0);",
            "        repeat(6) begin @(negedge clk);",
            "            if(out_valid || cfg_ready) $fatal(1,\"PRED_REPLAY_DRAIN_EARLY\"); end",
            f"        replay_word(packets[{first}+3],1); receive_mask(0,0,0,0,1);",
            f"        vector_case({ones},1,0,32'h113,0,0,0,0);",
        ])
        available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                             if line.startswith('MemAvailable:')))*1024
        self.assertGreaterEqual(available, 6*1024**3)
        def bounded():
            resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
        with tempfile.TemporaryDirectory(prefix='rms_predictor_test_', dir='.cache') as directory:
            root = Path(directory); packet_file = root/'packets.memh'
            packet_file.write_text(''.join(f'{packet:0160x}\n' for packet in packets))
            bench = root/'bench.sv'
            text = BENCH.replace('@DATA_WORDS@', str(len(packets)))
            text = text.replace('@PACKET_FILE@', str(packet_file))
            bench.write_text(text.replace('@BODY@', '\n'.join(body)))
            binary = root/'pipeline.vvp'
            compile_result = subprocess.run([
                'iverilog', '-g2012', '-s', 'tri_oracle_rms_predictor_tb', '-o', str(binary),
                'verilog/tri_oracle_rmsnorm.sv', 'verilog/tri_oracle_strip_predictor.sv',
                getattr(self, 'predictor_source_path', 'verilog/tri_oracle_rms_predictor.sv'),
                str(bench)], capture_output=True,
                text=True, timeout=60, preexec_fn=bounded)
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            result = subprocess.run(['vvp', str(binary)], capture_output=True, text=True,
                                    timeout=120, preexec_fn=bounded)
        self.assertFalse(root.exists())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(result.stdout.count('RMS_PREDICTOR_PASS'), 1)


if __name__ == '__main__':
    unittest.main()
