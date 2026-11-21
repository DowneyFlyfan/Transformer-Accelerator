`timescale 1ns/1ps
// Portable dataflow check. The real mapped metadata-client rebuild has a
// separate local test; this bench parks a synthetic inactive metadata client.
module tri_oracle_raw_context_buffer_tb;
    logic clk=0,rst_n=0;always #5 clk=~clk;
    logic metadata_idle=0,acquire_valid=0,acquire_ready,release_valid=0,release_ready;
    logic [1:0] owner=0;
    logic memory_req_valid,memory_req_ready,memory_req_write,memory_rsp_valid,memory_rsp_ready,memory_rsp_error;
    logic [9:0] memory_req_word;
    logic [63:0] memory_req_data,memory_rsp_data;
    logic read_valid=0,read_ready=0;
    logic [9:0] read_word;
    logic pack_clear=0,pack_clear_ready,row_valid=0,row_ready,frame_ready,frame_error;
    logic [4:0] row_head;
    logic [2047:0] row_data;
    logic signed [7:0] row_value_exponent;
    logic signed [8:0] context_exponent,convert_exponent;
    logic pack_req_valid,pack_rsp_ready;
    logic [9:0] pack_req_word;
    logic [63:0] pack_req_data;
    logic start_valid=0,start_ready,done_valid,done_ready=0,done_error;
    logic convert_req_valid,convert_req_write,convert_rsp_ready;
    logic [9:0] convert_req_word;
    logic [63:0] convert_req_data;
    logic [2055:0] rows[96];
    logic [63:0] expected_raw[2496],expected_codes[768];
    logic [8:0] expected_units[3];
    string row_file,raw_file,code_file,unit_file;

    assign memory_req_valid=owner==1 ? pack_req_valid : owner==2 ? convert_req_valid : read_valid;
    assign memory_req_write=owner==1 || (owner==2 && convert_req_write);
    assign memory_req_word=owner==1 ? pack_req_word : owner==2 ? convert_req_word : read_word;
    assign memory_req_data=owner==1 ? pack_req_data : owner==2 ? convert_req_data : 64'b0;
    assign memory_rsp_ready=owner==1 ? pack_rsp_ready : owner==2 ? convert_rsp_ready : read_ready;
    tri_oracle_raw_context_shared_storage memory (
        .clk,.rst_n,.metadata_idle,.acquire_valid,.acquire_ready,.release_valid,.release_ready,
        .metadata_ce_n(6'b111111),.metadata_we_n(6'b111111),.metadata_address(54'b0),
        .metadata_write_data(768'b0),.metadata_write_mask(768'b0),.metadata_read_data(),
        .req_valid(memory_req_valid),.req_ready(memory_req_ready),.req_write(memory_req_write),
        .req_word(memory_req_word),.req_data(memory_req_data),.rsp_valid(memory_rsp_valid),
        .rsp_ready(memory_rsp_ready),.rsp_error(memory_rsp_error),.rsp_data(memory_rsp_data)
    );
    tri_oracle_raw_context_row_packer packer (
        .clk,.rst_n,.clear(pack_clear),.clear_ready(pack_clear_ready),.zero_exponent(9'sd0),
        .row_valid,.row_ready,.row_head,.row_data,.row_value_exponent,.frame_ready,.frame_error,.context_exponent,
        .req_valid(pack_req_valid),.req_ready(owner==1 && memory_req_ready),.req_word(pack_req_word),.req_data(pack_req_data),
        .rsp_valid(owner==1 && memory_rsp_valid),.rsp_ready(pack_rsp_ready),.rsp_error(memory_rsp_error)
    );
    tri_oracle_raw_context_inplace_convert convert (
        .clk,.rst_n,.start_valid,.start_ready,.context_exponent(convert_exponent),.done_valid,.done_ready,.done_error,
        .req_valid(convert_req_valid),.req_ready(owner==2 && memory_req_ready),.req_write(convert_req_write),
        .req_word(convert_req_word),.req_data(convert_req_data),.rsp_valid(owner==2 && memory_rsp_valid),
        .rsp_ready(convert_rsp_ready),.rsp_error(memory_rsp_error),.rsp_data(memory_rsp_data)
    );
    task automatic check_word(input int word,input logic [63:0] expected);
        read_word=10'(word);read_valid=1;
        @(posedge clk);if(!memory_req_ready)$fatal(1,"RAW_PORTABLE_READ_ACCEPT");
        @(negedge clk);read_valid=0;
        repeat(2)begin
            @(posedge clk);
            if({memory_rsp_valid,memory_rsp_error,memory_rsp_data,release_ready}!=={2'b10,expected,1'b0})
                $fatal(1,"RAW_PORTABLE_DATA word=%0d got=%h expected=%h",word,memory_rsp_data,expected);
            @(negedge clk);
        end
        read_ready=1;@(negedge clk);read_ready=0;
        if(memory_rsp_valid)$fatal(1,"RAW_PORTABLE_EXTRA_RESPONSE");
    endtask
    initial begin
        if(!$value$plusargs("ROWS=%s",row_file)||!$value$plusargs("RAW=%s",raw_file)||
           !$value$plusargs("CODES=%s",code_file)||!$value$plusargs("UNITS=%s",unit_file))$fatal(1,"RAW_PORTABLE_ARGUMENTS");
        $readmemh(row_file,rows);$readmemh(raw_file,expected_raw);
        $readmemh(code_file,expected_codes);$readmemh(unit_file,expected_units);
        repeat(2)@(negedge clk);rst_n=1;acquire_valid=1;
        repeat(3)begin @(posedge clk);if(acquire_ready)$fatal(1,"RAW_PORTABLE_BUSY_ACQUIRE");@(negedge clk);end
        metadata_idle=1;@(posedge clk);if(!acquire_ready)$fatal(1,"RAW_PORTABLE_ACQUIRE");
        @(negedge clk);acquire_valid=0;
        for(int frame=0;frame<3;frame++)begin
            owner=1;pack_clear=1;@(posedge clk);if(!pack_clear_ready)$fatal(1,"RAW_PORTABLE_CLEAR");
            @(negedge clk);pack_clear=0;
            for(int i=0;i<32;i++)begin
                row_head=5'(17*i+31);{row_value_exponent,row_data}=rows[frame*32+int'(row_head)];row_valid=1;
                do @(posedge clk);while(!row_ready);
                @(negedge clk);row_valid=0;
                if(frame_error || frame_ready!==(i==31))$fatal(1,"RAW_PORTABLE_COMMIT");
            end
            if(context_exponent!==expected_units[frame])$fatal(1,"RAW_PORTABLE_UNIT");
            owner=0;for(int word=0;word<832;word++)check_word(word,expected_raw[frame*832+word]);
            owner=2;convert_exponent=context_exponent;start_valid=1;
            @(posedge clk);if(!start_ready)$fatal(1,"RAW_PORTABLE_CONVERT_START");
            @(negedge clk);start_valid=0;convert_exponent=127;
            wait(done_valid);@(negedge clk);
            repeat(3)begin @(posedge clk);if(!done_valid || done_error || start_ready || convert_req_valid)$fatal(1,"RAW_PORTABLE_CONVERT_HELD");@(negedge clk);end
            owner=0;for(int word=0;word<256;word++)check_word(word,expected_codes[frame*256+word]);
            for(int head=0;head<32;head++)check_word(800+head,expected_raw[frame*832+800+head]);
            done_ready=1;@(negedge clk);done_ready=0;
            if(done_valid || !start_ready)$fatal(1,"RAW_PORTABLE_CONVERT_TERMINAL");
        end
        release_valid=1;read_valid=1;@(posedge clk);
        if(!release_ready || memory_req_ready)$fatal(1,"RAW_PORTABLE_RELEASE_PRIORITY");
        @(negedge clk);release_valid=0;read_valid=0;
        $display("RAW_CONTEXT_PORTABLE_PASS frames=3 raw_words=2496 code_words=768 retained_unit_words=96");
        $finish;
    end
    initial begin #3000000;$fatal(1,"RAW_PORTABLE_TIMEOUT");end
endmodule
