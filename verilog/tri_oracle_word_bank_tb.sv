`timescale 1ns/1ps
// Catches address aliasing, writes while reset/disabled, premature forwarding,
// and loss of the second read port used for read-modify-write accumulation.
module tri_oracle_word_bank_tb #(parameter integer DATA_W=64, ADDR_W=5);
    localparam integer DEPTH=1<<ADDR_W, PIVOT=DEPTH/2+1;
    reg clk=0,rst_n=0,write_enable=0;
    reg [ADDR_W-1:0] write_addr=0,read_addr=0,second_addr=0;
    reg [DATA_W-1:0] write_data=0;
    wire [DATA_W-1:0] read_data,second_data;
    reg [DATA_W-1:0] expected [0:DEPTH-1];
    reg [DATA_W-1:0] sampled;
    integer i;
    always #5 clk=~clk;
`ifdef TRI_ORACLE_MAPPED_BANK
    // The fixed default-shape mapped module has no HDL parameters.
    tri_oracle_word_bank dut(.*);
`else
    tri_oracle_word_bank #(.DATA_W(DATA_W),.ADDR_W(ADDR_W)) dut(.*);
`endif
    always @(posedge clk) sampled<=read_data;
    task check_word(input integer address);
        begin
            read_addr=ADDR_W'(address); second_addr=ADDR_W'(DEPTH-1-address); #1;
            if(read_data!==expected[address] || second_data!==expected[DEPTH-1-address])
                $fatal(1,"bank read/independent address mismatch at %0d",address);
        end
    endtask
    initial begin
        @(negedge clk); rst_n=1;
        for(i=0;i<DEPTH;i=i+1) begin
            write_enable=1; write_addr=ADDR_W'(i);
            write_data=DATA_W'(64'hfedcba9876543210 ^ (64'h0102040810204081*i));
            expected[i]=write_data; @(negedge clk);
        end
        write_enable=0;
        for(i=0;i<DEPTH;i=i+1) check_word(i);
        @(negedge clk); read_addr=ADDR_W'(PIVOT); second_addr=ADDR_W'(PIVOT);
        write_addr=ADDR_W'(PIVOT); write_data=DATA_W'(64'h1122334455667788); write_enable=1;
        @(posedge clk); #1;
        if(sampled!==expected[PIVOT]) $fatal(1,"same-edge read must sample old word");
        expected[PIVOT]=write_data;
        if(read_data!==expected[PIVOT] || second_data!==expected[PIVOT])
            $fatal(1,"updated word unavailable after write edge");
        @(negedge clk); write_enable=0; write_data=0;
        repeat(2) @(negedge clk);
        check_word(PIVOT);
        rst_n=0; write_enable=1; write_addr=ADDR_W'(DEPTH-1); write_data=0;
        repeat(2) @(negedge clk);
        rst_n=1; write_enable=0;
        for(i=0;i<DEPTH;i=i+1) check_word(i);
        $display("PASS: all bank addresses, two read ports, old-data sampling, disabled writes, reset retention");
        $finish;
    end
endmodule
