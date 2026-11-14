module tri_oracle_key_redirect_tb;
    timeunit 1ns;
    timeprecision 1ps;
    logic clk=0, rst_n=0;
    always #5 clk=~clk;

    logic row_valid=0, row_ready=1, result_valid=0, result_ready=1;
    logic [63:0] row_key_base=64'h1000, row_query_addr=64'h5000;
    logic [10:0] row_key_count=64;
    logic req_valid=0, req_ready;
    logic [63:0] req_address;
    logic [4:0] req_length;
    logic rsp_valid, rsp_ready=1, rsp_last, rsp_error;
    logic [63:0] rsp_word;
    logic narrow_req_valid, narrow_req_ready=1, narrow_rsp_valid=0, narrow_rsp_ready;
    logic narrow_rsp_last=1, narrow_rsp_error=0;
    logic [63:0] narrow_rsp_word=64'h987654321;
    logic wide_req_valid, wide_req_ready=1, wide_rsp_valid=0, wide_rsp_ready;
    logic [63:0] wide_req_address;
    logic wide_rsp_last=1, wide_rsp_error=0;
    logic [511:0] wide_rsp_data='1, storage_data, storage_read='1;
    logic key_owner, storage_select, storage_write;
    logic [4:0] storage_address;

    tri_oracle_key_redirect dut (.*);

    task automatic start_row;
        @(negedge clk);
        row_valid=1;
        @(negedge clk);
        row_valid=0;
    endtask

    task automatic expect_narrow(input logic [63:0] address, input logic [4:0] length);
        @(negedge clk);
        req_address=address; req_length=length; req_valid=1;
        #1;
        if(narrow_req_valid!==1 || req_ready!==1)
            $fatal(1,"REDIRECT_UNSUPPORTED_BURST address=%h length=%d",address,length);
        @(negedge clk);
        req_valid=0;
        narrow_rsp_valid=1;
        for (int beat=0; beat<int'(length); beat++) begin
            narrow_rsp_word=address+64'(8*beat);
            narrow_rsp_last=beat+1==int'(length);
            #1;
            if (wide_req_valid!==0 || narrow_rsp_ready!==1 || rsp_valid!==1 ||
                rsp_error!==0 || rsp_word!==narrow_rsp_word || rsp_last!==narrow_rsp_last)
                $fatal(1,"REDIRECT_NARROW_RESPONSE beat=%0d length=%0d",beat,length);
            @(negedge clk);
        end
        narrow_rsp_valid=0;
    endtask

    initial begin
        repeat(2) @(negedge clk);
        rst_n=1;
        start_row();
        if(key_owner!==1) $fatal(1,"REDIRECT_ROW_NOT_OWNED");
        expect_narrow(64'h1038,31);
        expect_narrow(64'h1038,2);
        expect_narrow(row_query_addr,8);
        @(negedge clk);
        result_valid=1;
        @(negedge clk);
        result_valid=0; row_key_count=1025;
        start_row();
        if(key_owner!==0) $fatal(1,"REDIRECT_OVERSIZED_ROW");
        expect_narrow(64'h1000,2);
        $display("KEY_REDIRECT_BOUNDS_PASS");
        $finish;
    end

    initial begin
        #1000;
        $fatal(1,"KEY_REDIRECT_BOUNDS_TIMEOUT");
    end
endmodule
