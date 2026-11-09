"""Native cache commit/discard, compact prediction and registered read checks.

Exposing provisional/stale words, proxy sign errors, burst wrap, dropped held
responses or early context release must fail these actual hardware transactions.
"""
from pathlib import Path
import resource
import subprocess
import tempfile
import unittest


BENCH = r'''`timescale 1ns/1ps
module tri_oracle_activation_cache_tb;
    logic clk=0;
    always #5 clk=~clk;
    logic rst_n=0,cfg_valid=0,cfg_ready;
    logic [31:0] cfg_tag=0;
    logic [9:0] cfg_strips=0;
    logic in_valid=0,in_ready,in_last=0,in_error=0;
    logic [31:0] in_tag=0;
    logic [9:0] in_index=0;
    logic [3:0] in_count=8;
    logic [127:0] in_norm_q8=0;
    logic [7:0] in_outlier_mask=0;
    logic [63:0] in_activation=0;
    logic done_valid,done_ready=0,done_error;
    logic [31:0] done_tag;
    logic release_valid=0,release_ready;
    logic meta_req_valid=0,meta_req_ready;
    logic [8:0] meta_req_index=0;
    logic meta_rsp_valid,meta_rsp_ready=0,meta_rsp_error;
    logic [8:0] meta_rsp_index;
    logic [31:0] meta_rsp_tag;
    logic [127:0] meta_rsp_norm;
    logic read_req_valid=0,read_req_ready;
    logic [8:0] read_req_index=0;
    logic [4:0] read_req_length=0;
    logic read_rsp_valid,read_rsp_ready=0,read_rsp_last,read_rsp_error;
    logic [63:0] read_rsp_data;
    int checked=0;
    tri_oracle_activation_cache dut (.*);
    function automatic logic [127:0] normalized(input int index);
        logic [127:0] value;
        begin
            value={-16'sd16384,16'sd16384,16'sd769,16'sd768,
                16'sd0,-16'sd768,-16'sd769,-16'sd32768};
            normalized=index%2==0?value:-value;
        end
    endfunction
    function automatic logic [7:0] outliers(input logic [127:0] value);
        begin
            for(int lane=0;lane<8;lane++) outliers[lane]=
                $signed(value[lane*16+:16])>768 || $signed(value[lane*16+:16])< -768;
        end
    endfunction
    function automatic logic [127:0] proxy(input logic [127:0] value);
        logic signed [15:0] element;
        begin
            for(int lane=0;lane<8;lane++) begin
                element=$signed(value[lane*16+:16]);
                if(element>768) proxy[lane*16+:16]=16'd769;
                else if(element< -768) proxy[lane*16+:16]=-16'sd769;
                else proxy[lane*16+:16]=16'd0;
            end
        end
    endfunction
    function automatic logic [63:0] activation(input int index,input logic [31:0] tag);
        activation={tag,16'(index),16'(index^16'h5a5a)};
    endfunction
    task automatic configure(input int strips,input logic [31:0] tag);
        begin
            @(negedge clk);cfg_valid=1;cfg_strips=10'(strips);cfg_tag=tag;
            @(posedge clk);if(!cfg_ready) $fatal(1,"CACHE_CONFIG_NOT_READY");
            @(negedge clk);cfg_valid=0;cfg_strips=0;cfg_tag='1;
        end
    endtask
    task automatic write_word(input int index,input logic [31:0] tag,input bit last,
        input int fault=0);
        int timeout;
        begin
            @(negedge clk);in_valid=1;in_last=last;in_error=fault==1;
            in_index=10'(index);in_tag=fault==2?~tag:tag;in_count=fault==3?4'd7:4'd8;
            in_norm_q8=normalized(index);in_outlier_mask=outliers(in_norm_q8)^(fault==4?8'd1:8'd0);
            in_activation=activation(index,tag);timeout=0;@(posedge clk);
            while(!in_ready && timeout<100) begin @(posedge clk);timeout++;end
            if(!in_ready) $fatal(1,"CACHE_WRITE_TIMEOUT");
            @(negedge clk);in_valid=0;in_norm_q8='1;in_outlier_mask=0;
            in_activation='1;in_tag='1;in_count=0;
        end
    endtask
    task automatic completion(input logic [31:0] tag,input bit error);
        int timeout;
        begin
            timeout=0;
            while(!done_valid && timeout<100) begin @(negedge clk);timeout++;end
            if(!done_valid || {done_tag,done_error}!=={tag,error})
                $fatal(1,"CACHE_COMPLETION_MISMATCH tag=%h error=%b",done_tag,done_error);
            repeat(4) begin @(posedge clk);#1;
                if(!done_valid || cfg_ready || in_ready || release_ready ||
                    {done_tag,done_error}!=={tag,error}) $fatal(1,"CACHE_COMPLETION_NOT_HELD");end
            @(negedge clk);done_ready=1;
            @(negedge clk);done_ready=0;
        end
    endtask
    task automatic inaccessible;
        begin
            @(negedge clk);meta_req_valid=1;meta_req_index=0;
            read_req_valid=1;read_req_index=0;read_req_length=1;
            repeat(4) begin @(posedge clk);#1;
                if(meta_req_ready || read_req_ready || meta_rsp_valid || read_rsp_valid)
                    $fatal(1,"CACHE_PROVISIONAL_OR_FAILED_DATA_VISIBLE");end
            @(negedge clk);meta_req_valid=0;read_req_valid=0;
        end
    endtask
    task automatic metadata(input int index,input logic [31:0] tag,input bit error);
        int timeout;
        logic [169:0] held;
        begin
            @(negedge clk);meta_req_valid=1;meta_req_index=9'(index);
            @(posedge clk);if(!meta_req_ready) $fatal(1,"CACHE_META_NOT_READY");
            @(negedge clk);meta_req_valid=0;meta_req_index='1;timeout=0;
            while(!meta_rsp_valid && timeout<100) begin @(negedge clk);timeout++;end
            if(!meta_rsp_valid || {meta_rsp_tag,meta_rsp_index,meta_rsp_error,meta_rsp_norm}!==
                {tag,9'(index),error,error?128'b0:proxy(normalized(index))})
                $fatal(1,"CACHE_META_MISMATCH index=%0d norm=%h error=%b",index,meta_rsp_norm,meta_rsp_error);
            held={meta_rsp_tag,meta_rsp_index,meta_rsp_error,meta_rsp_norm};release_valid=1;
            repeat(5) begin @(posedge clk);#1;
                if(release_ready || !meta_rsp_valid ||
                    {meta_rsp_tag,meta_rsp_index,meta_rsp_error,meta_rsp_norm}!==held)
                    $fatal(1,"CACHE_META_STALL_OR_RELEASE");end
            @(negedge clk);release_valid=0;meta_rsp_ready=1;
            @(negedge clk);meta_rsp_ready=0;checked++;
        end
    endtask
    task automatic read_burst(input int index,length,input logic [31:0] tag,input bit error);
        int timeout;
        logic [65:0] held;
        bit last;
        begin
            @(negedge clk);read_req_valid=1;read_req_index=9'(index);read_req_length=5'(length);
            @(posedge clk);if(!read_req_ready) $fatal(1,"CACHE_READ_NOT_READY");
            @(negedge clk);read_req_valid=0;read_req_index='1;read_req_length=0;
            for(int beat=0;beat<(error?1:length);beat++) begin
                timeout=0;
                while(!read_rsp_valid && timeout<100) begin @(negedge clk);timeout++;end
                last=error || beat==length-1;
                if(!read_rsp_valid || {read_rsp_last,read_rsp_error,read_rsp_data}!==
                    {last,error,error?64'b0:activation(index+beat,tag)})
                    $fatal(1,"CACHE_READ_MISMATCH index=%0d beat=%0d data=%h error=%b",
                        index,beat,read_rsp_data,read_rsp_error);
                held={read_rsp_last,read_rsp_error,read_rsp_data};release_valid=1;
                repeat(3) begin @(posedge clk);#1;
                    if(release_ready || !read_rsp_valid ||
                        {read_rsp_last,read_rsp_error,read_rsp_data}!==held)
                        $fatal(1,"CACHE_READ_STALL_OR_RELEASE");end
                @(negedge clk);release_valid=0;read_rsp_ready=1;
                @(negedge clk);read_rsp_ready=0;
            end
            checked++;
        end
    endtask
    task automatic release_context;
        begin
            @(negedge clk);release_valid=1;
            @(posedge clk);if(!release_ready) $fatal(1,"CACHE_RELEASE_NOT_READY");
            @(negedge clk);release_valid=0;
            if(!cfg_ready) $fatal(1,"CACHE_RELEASE_DID_NOT_FREE_CONTEXT");
        end
    endtask
    task automatic metadata_stream(input logic [31:0] tag);
        begin
            @(negedge clk);meta_req_valid=1;meta_rsp_ready=1;meta_req_index=7;
            for(int index=7;index<=10;index++) begin
                @(posedge clk);
                if(!meta_req_ready) $fatal(1,"CACHE_META_REPLACEMENT_NOT_READY");
                if(index>7 && (!meta_rsp_valid ||
                    {meta_rsp_tag,meta_rsp_index,meta_rsp_error,meta_rsp_norm}!==
                    {tag,9'(index-1),1'b0,proxy(normalized(index-1))}))
                    $fatal(1,"CACHE_META_REPLACEMENT_MISMATCH");
                @(negedge clk);meta_req_index=9'(index+1);
            end
            meta_req_valid=0;
            @(posedge clk);
            if(!meta_rsp_valid || {meta_rsp_tag,meta_rsp_index,meta_rsp_error,meta_rsp_norm}!==
                {tag,9'd10,1'b0,proxy(normalized(10))})
                $fatal(1,"CACHE_META_REPLACEMENT_FINAL");
            @(negedge clk);meta_rsp_ready=0;checked+=4;
        end
    endtask
    task automatic reset_now;
        begin
            @(negedge clk);rst_n=0;cfg_valid=0;in_valid=0;done_ready=0;release_valid=0;
            meta_req_valid=0;read_req_valid=0;meta_rsp_ready=0;read_rsp_ready=0;
            repeat(2) @(negedge clk);rst_n=1;
            repeat(4) begin @(posedge clk);#1;
                if(!cfg_ready || done_valid || meta_rsp_valid || read_rsp_valid ||
                    meta_req_ready || read_req_ready) $fatal(1,"CACHE_RESET_LEFT_CONTEXT");end
        end
    endtask
    initial begin
        repeat(2) @(negedge clk);rst_n=1;
        configure(512,32'h80000001);
        for(int k=0;k<511;k++) write_word(k,32'h80000001,0);
        inaccessible();
        write_word(511,32'h80000001,1);completion(32'h80000001,0);
        metadata(0,32'h80000001,0);metadata(1,32'h80000001,0);
        metadata(511,32'h80000001,0);
        read_burst(0,16,32'h80000001,0);read_burst(496,16,32'h80000001,0);
        read_burst(511,1,32'h80000001,0);read_burst(511,2,32'h80000001,1);
        read_burst(0,0,32'h80000001,1);read_burst(0,17,32'h80000001,1);
        metadata_stream(32'h80000001);
        fork metadata(20,32'h80000001,0);read_burst(20,3,32'h80000001,0);join
        release_context();inaccessible();
        for(int mode=1;mode<=4;mode++) begin
            configure(2,32'(mode));write_word(0,32'(mode),0);
            write_word(1,32'(mode),1,mode);completion(32'(mode),1);inaccessible();release_context();
        end
        configure(2,32'h10);write_word(0,32'h10,1);completion(32'h10,1);inaccessible();release_context();
        configure(2,32'h11);write_word(0,32'h11,0);write_word(0,32'h11,1);
        completion(32'h11,1);inaccessible();release_context();
        configure(1,32'h12);write_word(0,32'h12,0);inaccessible();
        if(done_valid) $fatal(1,"CACHE_LATE_FRAME_COMPLETED_EARLY");
        write_word(1,32'h12,1);completion(32'h12,1);release_context();
        configure(0,32'h13);write_word(0,32'h13,1,1);completion(32'h13,1);release_context();
        configure(3,32'h14);write_word(0,32'h14,0);write_word(1,32'h14,0,2);
        write_word(2,32'h14,1);completion(32'h14,1);inaccessible();release_context();
        configure(513,32'h15);
        for(int k=0;k<513;k++) write_word(k,32'h15,k==512);
        completion(32'h15,1);inaccessible();release_context();
        configure(1,32'h20);write_word(0,32'h20,1);completion(32'h20,0);
        metadata(0,32'h20,0);metadata(1,32'h20,1);read_burst(1,1,32'h20,1);release_context();
        configure(2,32'h30);write_word(0,32'h30,0);reset_now();inaccessible();
        configure(1,32'h31);write_word(0,32'h31,1);completion(32'h31,0);
        @(negedge clk);meta_req_valid=1;read_req_valid=1;read_req_index=0;read_req_length=1;
        @(posedge clk);if(!meta_req_ready || !read_req_ready) $fatal(1,"CACHE_RESET_READS_NOT_ACCEPTED");
        @(negedge clk);meta_req_valid=0;read_req_valid=0;
        if(!meta_rsp_valid || !read_rsp_valid) $fatal(1,"CACHE_RESET_READS_NOT_HELD");
        reset_now();inaccessible();
        configure(1,32'h32);write_word(0,32'h32,1);completion(32'h32,0);
        metadata(0,32'h32,0);read_burst(0,1,32'h32,0);release_context();
        $display("ACTIVATION_CACHE_PASS read_checks=%0d",checked);$finish;
    end
    initial begin #2000000;$fatal(1,"CACHE_GLOBAL_WATCHDOG");end
endmodule
'''


class ActivationCacheTest(unittest.TestCase):
    def test_native_commit_discard_proxy_bursts_release_and_reset(self):
        available = int(next(line.split()[1] for line in
                             Path('/proc/meminfo').read_text().splitlines()
                             if line.startswith('MemAvailable:')))*1024
        self.assertGreaterEqual(available, 8*1024**3)

        def bounded():
            resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))

        with tempfile.TemporaryDirectory(prefix='activation_cache_test_', dir='.cache') as directory:
            root = Path(directory);bench = root/'bench.sv';bench.write_text(BENCH)
            binary = root/'cache.vvp'
            compiled = subprocess.run([
                'iverilog', '-g2012', '-s', 'tri_oracle_activation_cache_tb', '-o', str(binary),
                getattr(self, 'source_path', 'verilog/tri_oracle_activation_cache.sv'), str(bench)],
                capture_output=True, text=True, timeout=60, preexec_fn=bounded)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            native = subprocess.run(['vvp', str(binary)], capture_output=True, text=True,
                                    timeout=60, preexec_fn=bounded)
        self.assertFalse(root.exists())
        self.assertEqual(native.returncode, 0, native.stdout+native.stderr)
        self.assertEqual(native.stdout.count('ACTIVATION_CACHE_PASS'), 1)
        self.native_stdout = native.stdout


if __name__ == '__main__':
    unittest.main()
