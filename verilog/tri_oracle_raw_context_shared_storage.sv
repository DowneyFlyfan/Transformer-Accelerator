`timescale 1ns/1ps
// The current six metadata memories, exposed as832 leased64-bit words.
module tri_oracle_raw_context_shared_storage (
    input logic clk,rst_n,metadata_idle,acquire_valid,
    output logic acquire_ready,
    input logic release_valid,
    output logic release_ready,
    input logic [5:0] metadata_ce_n,metadata_we_n,
    input logic [53:0] metadata_address,
    input logic [767:0] metadata_write_data,metadata_write_mask,
    output logic [767:0] metadata_read_data,
    input logic req_valid,req_write,
    output logic req_ready,
    input logic [9:0] req_word,
    input logic [63:0] req_data,
    output logic rsp_valid,rsp_error,
    input logic rsp_ready,
    output logic [63:0] rsp_data
);
    logic owner,accepted,bad_address;
    logic [9:0] upper_word;
    logic [2:0] selected_bank,response_bank;
    logic selected_half,response_half,response_write;
    logic [5:0] ce_n,we_n;
    logic [53:0] address;
    logic [767:0] write_data,write_mask,read_data;

    assign acquire_ready=rst_n && !owner && metadata_idle && (&metadata_ce_n) && !rsp_valid;
    assign release_ready=rst_n && owner && !rsp_valid;
    assign req_ready=rst_n && owner && !rsp_valid && !release_valid;
    assign accepted=req_valid && req_ready;
    assign bad_address=req_word>=832;
    assign upper_word=req_word-10'd512;
    assign selected_bank=req_word<512 ? 3'd0 : 3'(1+(upper_word>>6));
    assign selected_half=req_word>=512 && upper_word[0];
    assign metadata_read_data=owner ? '0 : read_data;
    assign rsp_data=rsp_valid && !rsp_error && !response_write ?
                    read_data[128*response_bank+64*response_half+:64] : 64'b0;

    always_comb begin
        ce_n=metadata_ce_n;we_n=metadata_we_n;address=metadata_address;
        write_data=metadata_write_data;write_mask=metadata_write_mask;
        if(owner || !rst_n)begin
            ce_n='1;we_n='1;address='0;write_data='0;write_mask='1;
            if(rst_n && accepted && !bad_address)begin
                ce_n[selected_bank]=0;we_n[selected_bank]=!req_write;
                address[9*selected_bank+:9]=selected_bank==0 ? req_word[8:0] : {4'b0,upper_word[5:1]};
                write_data[128*selected_bank+:128]={req_data,req_data};
                // Numerical negative control: full128-bit raw writes.
                write_mask[128*selected_bank+:128]=~(128'hffffffffffffffff<<(64*selected_half));
            end
        end
    end
    TS5N28HPCPSVTA512X64M4F lower_bank (
        .CLK(clk),.CEB(ce_n[0]),.WEB(we_n[0]),.A(address[8:0]),
        .D(write_data[63:0]),.Q(read_data[63:0])
    );
    assign read_data[127:64]='0;
    for(genvar bank=1;bank<6;bank++)begin:upper_banks
        TS5N28HPCPSVTA32X128M2FW memory (
            .CLK(clk),.CEB(ce_n[bank]),.WEB(we_n[bank]),
            .A(address[9*bank+:5]),.D(write_data[128*bank+:128]),
            .BWEB(write_mask[128*bank+:128]),.Q(read_data[128*bank+:128])
        );
    end
    always_ff @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            owner<=0;rsp_valid<=0;rsp_error<=0;
            response_bank<=0;response_half<=0;response_write<=0;
        end else begin
            if(acquire_valid && acquire_ready)owner<=1;
            else if(release_valid && release_ready)owner<=0;
            if(accepted)begin
                rsp_valid<=1;rsp_error<=bad_address;
                response_bank<=bad_address ? 3'd0 : selected_bank;
                response_half<=selected_half;response_write<=req_write;
            end else if(rsp_valid && rsp_ready)rsp_valid<=0;
        end
    end
endmodule
