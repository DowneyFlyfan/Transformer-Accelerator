`timescale 1ns/1ps
module tri_oracle_attention_projection_scale_tb;
    logic signed [31:0] accumulator;
    logic [4:0] scale_shift;
    logic signed [7:0] projection_code;
    string vector_file;
    int vector_count, fd;

    tri_oracle_attention_projection_scale dut (.*);

    initial begin
        logic [44:0] vector;
        if (!$value$plusargs("VECTORS=%s", vector_file)) $fatal(1, "PROJECTION_SCALE_NO_VECTORS");
        fd = $fopen(vector_file, "r");
        if (fd == 0) $fatal(1, "PROJECTION_SCALE_FILE_OPEN");
        while ($fscanf(fd, "%h", vector) == 1) begin
            {accumulator, scale_shift} = vector[44:8];
            #1;
            if (projection_code !== vector[7:0])
                $fatal(1, "PROJECTION_SCALE_MISMATCH vector=%0d accumulator=%h shift=%0d got=%h expected=%h",
                       vector_count, accumulator, scale_shift, projection_code, vector[7:0]);
            vector_count++;
        end
        if (!$feof(fd)) $fatal(1, "PROJECTION_SCALE_BAD_VECTOR");
        $fclose(fd);
        $display("PROJECTION_SCALE_PASS vectors=%0d", vector_count);
        $finish;
    end
endmodule
