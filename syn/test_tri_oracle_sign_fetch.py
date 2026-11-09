"""Native checks for outlier-only packed sign reads, framing and fault drain.

Wrong lane transposition, fetching non-outlier pairs, unchecked address wrap,
premature error publication, or a stale result after reset must fail this test.
"""
from pathlib import Path
import random
import resource
import subprocess
import tempfile
import unittest


BENCH = r'''`timescale 1ns/1ps
module tri_oracle_sign_fetch_tb;
    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, in_valid = 0, in_ready;
    logic [31:0] in_tag = 0;
    logic [10:0] in_group = 0;
    logic [9:0] in_strips = 0, in_index = 0;
    logic in_last = 0, in_error = 0;
    logic [127:0] in_norm_q8 = 0;
    logic [63:0] in_gate_base = 0, in_up_base = 0;
    logic out_valid, out_ready = 0, out_last, out_error;
    logic [31:0] out_tag;
    logic [10:0] out_group;
    logic [9:0] out_index;
    logic [127:0] out_norm_q8;
    logic [255:0] out_gate_signs, out_up_signs;
    logic req_valid, req_ready = 0;
    logic [63:0] req_address;
    logic [4:0] req_length;
    logic rsp_valid = 0, rsp_ready, rsp_last = 0, rsp_error = 0;
    logic [63:0] rsp_data = 0;
    logic [127:0] requests [0:@REQUEST_WORDS@-1];
    int cursor = 0, limit = 0, fault_at = -1, fault_mode = 0;
    int cycle = 0, delay_count = 0, beat = 0, active_request = -1;
    int checked = 0, drains = 0;
    bit pending = 0, consumed = 0, force_request_stall = 0;
    bit force_response_stall = 0;
    logic [63:0] active_data = 0;
    tri_oracle_sign_fetch dut (.*);

@MEMORY_PEER@
    task automatic send_strip(
        input logic [31:0] tag,
        input int group_id, strips, index,
        input bit last, error,
        input logic [127:0] data,
        input logic [63:0] gate_base, up_base
    );
        int timeout;
        begin
            @(negedge clk); #1;
            in_valid = 1; in_tag = tag; in_group = 11'(group_id);
            in_strips = 10'(strips); in_index = 10'(index);
            in_last = last; in_error = error; in_norm_q8 = data;
            in_gate_base = gate_base; in_up_base = up_base;
            timeout = 0; @(posedge clk);
            while (in_ready !== 1'b1 && timeout < 200) begin
                @(posedge clk); timeout++;
            end
            if (in_ready !== 1'b1) $fatal(1,"SIGN_INPUT_TIMEOUT");
            @(negedge clk); #1;
            in_valid = 0; in_tag = ~tag; in_group = '1; in_strips = 0;
            in_index = '1; in_last = !last; in_error = !error;
            in_norm_q8 = ~data; in_gate_base = '1; in_up_base = '1;
        end
    endtask

    task automatic run_case(
        input logic [31:0] tag,
        input int group_id, strips, index,
        input bit last, error,
        input logic [127:0] data,
        input logic [63:0] gate_base, up_base,
        input bit expected_error,
        input logic [255:0] gate_signs, up_signs,
        input int first_request, request_count, fault_offset, mode
    );
        int timeout;
        logic [31:0] held_tag;
        logic [127:0] wanted_data;
        begin
            if (cursor != first_request) $fatal(1,"SIGN_REQUEST_SCRIPT_POSITION");
            limit = first_request + request_count;
            fault_at = fault_offset < 0 ? -1 : first_request + fault_offset;
            fault_mode = mode;
            send_strip(tag,group_id,strips,index,last,error,data,gate_base,up_base);
            timeout = 0;
            while (out_valid !== 1'b1 && timeout < 300) begin
                @(negedge clk); #1; timeout++;
            end
            if (out_valid !== 1'b1) $fatal(1,"SIGN_RESULT_TIMEOUT");
            wanted_data = expected_error ? 128'b0 : data;
            if ({out_tag,out_group,out_index,out_last,out_error,out_norm_q8,
                    out_gate_signs,out_up_signs} !==
                {tag,11'(group_id),10'(index),last,expected_error,wanted_data,
                    gate_signs,up_signs})
                $fatal(1,"SIGN_RESULT_MISMATCH tag=%h error=%b gate=%h up=%h",
                    out_tag,out_error,out_gate_signs,out_up_signs);
            if (cursor != limit || pending) $fatal(1,"SIGN_INCOMPLETE_RESPONSE_DRAIN");
            // Neither changing inputs nor a held replacement transaction may
            // alter the current result or issue a new request.
            in_valid = 1; held_tag = out_tag;
            repeat (6) begin
                @(posedge clk); #1;
                if (out_valid !== 1'b1 || in_ready || req_valid ||
                    {out_tag,out_group,out_index,out_last,out_error,out_norm_q8,
                        out_gate_signs,out_up_signs} !==
                    {held_tag,11'(group_id),10'(index),last,expected_error,wanted_data,
                        gate_signs,up_signs})
                    $fatal(1,"SIGN_STALL_CHANGED_RESULT");
            end
            @(negedge clk); #1; in_valid = 0; out_ready = 1;
            @(negedge clk); #1; out_ready = 0; checked++;
        end
    endtask

    task automatic reset_now;
        begin
            @(negedge clk); #1; rst_n = 0; in_valid = 0; out_ready = 0;
            repeat (2) @(negedge clk);
            #1; rst_n = 1; force_request_stall = 0; force_response_stall = 0;
            repeat (4) begin
                @(posedge clk); #1;
                if (out_valid || req_valid || rsp_ready || !in_ready)
                    $fatal(1,"SIGN_RESET_LEFT_TRANSACTION");
            end
        end
    endtask

    initial begin
        $readmemh("@REQUEST_FILE@",requests,0,@REQUEST_WORDS@-1);
        repeat (2) @(negedge clk); #1; rst_n = 1;
@BODY@
        $display("SIGN_FETCH_PASS cases=%0d requests=%0d drain_beats=%0d",
            checked,cursor,drains);
        $finish;
    end
    initial begin #2000000; $fatal(1,"SIGN_GLOBAL_WATCHDOG"); end
endmodule
'''


MEMORY_PEER = r'''    always @(posedge clk) begin
        if (rst_n) begin
            if (req_valid && req_ready) begin
                if (pending || cursor >= limit || req_length !== 5'd1 ||
                    req_address !== requests[cursor][127:64])
                    $fatal(1,"SIGN_REQUEST_MISMATCH cursor=%0d address=%h",cursor,req_address);
                pending = 1; active_request = cursor;
                active_data = requests[cursor][63:0]; cursor++;
                delay_count = 1 + cycle%3; beat = 0;
            end
            if (rsp_valid && rsp_ready) begin
                if (!pending) $fatal(1,"SIGN_UNOWNED_RESPONSE");
                if (!rsp_last && out_valid) $fatal(1,"SIGN_ERROR_PUBLISHED_BEFORE_DRAIN");
                if (rsp_last) pending = 0;
                else begin beat++; delay_count = 2; drains++; end
                consumed = 1;
            end
        end
    end
    always @(negedge clk) begin
        if (!rst_n) begin
            req_ready = 0; rsp_valid = 0; pending = 0; consumed = 0;
        end else begin
            cycle++;
            req_ready = !force_request_stall && cycle%4 != 0;
            if (consumed) begin rsp_valid = 0; consumed = 0; end
            if (pending && !rsp_valid && !force_response_stall) begin
                if (delay_count > 0) delay_count--;
                else begin
                    rsp_valid = 1;
                    rsp_data = beat == 0 ? active_data : 64'hbad0bad0bad0bad0;
                    rsp_error = active_request == fault_at && fault_mode == 1;
                    rsp_last = !(active_request == fault_at && fault_mode == 2 && beat < 2);
                end
            end
        end
    end

'''

class SignFetchTest(unittest.TestCase):
    def test_native_outlier_reads_layout_fault_drain_and_reset(self):
        rng = random.Random(316502)
        requests, body = [], []
        tag = 0

        def case(values, *, group=0, strips=1, index=0, last=True,
                 error=False, gate_base=0x1000, up_base=0x100000,
                 invalid=False, fault_offset=-1, fault_mode=0):
            nonlocal tag
            tag += 1
            raw = sum((value & 0xffff) << (16*lane)
                      for lane, value in enumerate(values))
            first = len(requests)
            signs = [0, 0]
            active = [abs(value) > 768 for value in values]
            if not (invalid or error):
                for pair in range(4):
                    if not any(active[pair*2:pair*2+2]):
                        continue
                    for matrix, base in enumerate((gate_base, up_base)):
                        address = base+group*strips*32+index*32+pair*8
                        # Each plane has one independent bit per output row.
                        word = rng.getrandbits(64)
                        requests.append((address, word))
                        for lane in (2*pair, 2*pair+1):
                            if active[lane]:
                                for channel in range(32):
                                    bit = (word >> (channel+32*(lane%2))) & 1
                                    signs[matrix] |= bit << (8*channel+lane)
                        if len(requests)-first-1 == fault_offset:
                            break
                    if len(requests)-first-1 == fault_offset:
                        break
            wanted_error = bool(invalid or error or fault_offset >= 0)
            if wanted_error:
                signs = [0, 0]
            body.append(
                f"        run_case(32'h{tag:08x},{group},{strips},{index},"
                f"1'b{int(last)},1'b{int(error)},128'h{raw:032x},"
                f"64'h{gate_base:016x},64'h{up_base:016x},1'b{int(wanted_error)},"
                f"256'h{signs[0]:064x},256'h{signs[1]:064x},"
                f"{first},{len(requests)-first},{fault_offset},{fault_mode});")

        case([769, -769, 768, -768, 32767, -32768, 0, 1])
        self.assertEqual([address for address, _ in requests],
                         [0x1000, 0x100000, 0x1010, 0x100010])
        case([768, -768, 0, 1, -1, 500, -600, 256])
        case([-32768]*8, group=2047, strips=512, index=511,
             gate_base=0xfffffffff0000000, up_base=0xffffffffe0000000)
        for _ in range(30):
            strips = rng.randint(1, 512)
            case([rng.randint(-1600, 1600) for _ in range(8)],
                 group=rng.randint(0, 2047), strips=strips,
                 index=rng.randrange(strips), last=bool(rng.randrange(2)))
        for kwargs in ({'strips': 0}, {'strips': 513}, {'index': 1},
                       {'gate_base': 0x1001}, {'up_base': 0x100001},
                       {'gate_base': 0xfffffffffffffff8},
                       {'group': 1, 'up_base': 0xffffffffffffffe0}):
            case([900]*8, invalid=True, **kwargs)
        case([900]*8, error=True)
        case([900]*8, fault_offset=0, fault_mode=1)
        case([900]*8, fault_offset=3, fault_mode=2)
        case([900, 0, 0, 0, 0, 0, 0, 0])
        # Reset before a request is accepted, after acceptance, and while an
        # output is held. The memory peer resets with the engine by contract.
        body.extend([
            "        force_request_stall=1; limit=cursor;",
            "        send_strip(32'h100,0,1,0,1,0,128'd900,64'h1000,64'h100000);",
            "        begin int t; t=0; while(!req_valid && t<20) begin",
            "            @(negedge clk); #1; t++; end",
            "            if(!req_valid) $fatal(1,\"SIGN_RESET_REQUEST_NOT_REACHED\"); end",
            "        reset_now();",
        ])
        case([900, 0, 0, 0, 0, 0, 0, 0])
        # One accepted request is deliberately cancelled by shared reset.
        accepted = len(requests)
        requests.append((0x1000, 0x123456789abcdef0))
        body.extend([
            "        force_response_stall=1; limit=cursor+1; fault_at=-1;",
            "        send_strip(32'h101,0,1,0,1,0,128'd900,64'h1000,64'h100000);",
            f"        begin int t; t=0; while(cursor!={accepted+1} && t<20) begin",
            "            @(negedge clk); #1; t++; end",
            f"            if(cursor!={accepted+1} || !pending)",
            "                $fatal(1,\"SIGN_RESET_RESPONSE_NOT_REACHED\"); end",
            "        reset_now();",
        ])
        case([900, 0, 0, 0, 0, 0, 0, 0])
        body.extend([
            "        limit=cursor;",
            "        send_strip(32'h102,0,1,0,1,0,128'd1,64'h1000,64'h100000);",
            "        begin int t; t=0; while(!out_valid && t<20) begin",
            "            @(negedge clk); #1; t++; end",
            "            if(!out_valid) $fatal(1,\"SIGN_RESET_OUTPUT_NOT_REACHED\"); end",
            "        reset_now();",
        ])
        case([900, 0, 0, 0, 0, 0, 0, 0])
        available = int(next(line.split()[1] for line in
                             Path('/proc/meminfo').read_text().splitlines()
                             if line.startswith('MemAvailable:')))*1024
        self.assertGreaterEqual(available, 6*1024**3)

        def bounded():
            resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))

        with tempfile.TemporaryDirectory(prefix='sign_fetch_test_', dir='.cache') as directory:
            root = Path(directory)
            request_file = root/'requests.memh'
            request_file.write_text(''.join(f'{address:016x}{word:016x}\n'
                                            for address, word in requests))
            bench = root/'bench.sv'
            bench.write_text(BENCH.replace('@MEMORY_PEER@', MEMORY_PEER)
                             .replace('@REQUEST_WORDS@', str(len(requests)))
                             .replace('@REQUEST_FILE@', str(request_file))
                             .replace('@BODY@', '\n'.join(body)))
            binary = root/'sign_fetch.vvp'
            compiled = subprocess.run([
                'iverilog', '-g2012', '-s', 'tri_oracle_sign_fetch_tb', '-o', str(binary),
                getattr(self, 'source_path', 'verilog/tri_oracle_sign_fetch.sv'), str(bench)],
                text=True, capture_output=True, timeout=60, preexec_fn=bounded)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run(['vvp', str(binary)], text=True,
                                    capture_output=True, timeout=60, preexec_fn=bounded)
        self.assertFalse(root.exists())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(result.stdout.count('SIGN_FETCH_PASS'), 1)


if __name__ == '__main__':
    unittest.main()
