`timescale 1ns/1ps
module tri_oracle_signed_context_transfer_tb;
    logic signed [31:0] accumulator;
    logic scale_right;
    logic [4:0] scale_shift;
    logic signed [7:0] projection_code, expected, legacy_code;
    logic [45:0] vector;
    integer descriptor, status, count, right_count;
    string vector_path;
    tri_oracle_attention_projection_scale_bidirectional dut (.*);
    tri_oracle_attention_projection_scale legacy (.accumulator, .scale_shift, .projection_code(legacy_code));
    initial begin
        if (!$value$plusargs("VECTORS=%s", vector_path)) $fatal(1,"Missing vector path");
        descriptor=$fopen(vector_path,"r");
        if (!descriptor) $fatal(1,"Cannot open vectors");
        count=0;right_count=0;
        while (!$feof(descriptor)) begin
            status=$fscanf(descriptor,"%h\n",vector);
            if (status==1) begin
                {accumulator,scale_right,scale_shift,expected}=vector;
                #1;
                if (projection_code !== expected)
                    $fatal(1,"Mismatch n=%0d acc=%0d right=%0d shift=%0d got=%0d expected=%0d",count,accumulator,scale_right,scale_shift,projection_code,expected);
                if (!scale_right && projection_code !== legacy_code)
                    $fatal(1,"Legacy result changed n=%0d",count);
                count=count+1;right_count=right_count+integer'(scale_right);
            end else if (!$feof(descriptor)) $fatal(1,"Malformed vector file");
        end
        $fclose(descriptor);
        if (count<10000 || right_count<5000) $fatal(1,"Incomplete coverage");
        $display("SIGNED_CONTEXT_TRANSFER_PASS cases=%0d right_cases=%0d",count,right_count);
        $finish;
    end
    initial begin #10000000; $fatal(1,"Timeout");end
endmodule
