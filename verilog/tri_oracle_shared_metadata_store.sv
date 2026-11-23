`timescale 1ns/1ps
// Two predictor metadata memories, also leased as832 linear64-bit context words.
// The collector blocks NEW predictor descriptors before waiting for ff_idle.
// Existing predictor work and port enables must drain before acquisition.
// A context lease destroys metadata; the next predictor frame must rebuild it.
module tri_oracle_shared_metadata_store (
  input logic clk,rst_n,ff_idle,
  input logic acquire_valid,
  output logic acquire_ready,
  input logic release_valid,
  output logic release_ready,context_owned,
  input logic [1:0] ff_ce_n,ff_we_n,
  input logic [17:0] ff_address,
  input logic [127:0] ff_write_data,
  output logic [127:0] ff_read_data,
  input logic req_valid,req_write,
  output logic req_ready,
  input logic [9:0] req_word,
  input logic [63:0] req_data,
  output logic rsp_valid,rsp_error,
  input logic rsp_ready,
  output logic [63:0] rsp_data
);
  logic accepted,bad_address,response_bank,response_write;
  logic [1:0] ce_n,we_n;
  logic [17:0] address;
  logic [127:0] write_data;
  logic [63:0] lower_q,upper_q;

  assign acquire_ready=rst_n && !context_owned && ff_idle && (&ff_ce_n) && !rsp_valid;
  assign release_ready=rst_n && context_owned && !rsp_valid;
  assign req_ready=rst_n && context_owned && !rsp_valid && !release_valid;
  assign accepted=req_valid && req_ready;
  assign bad_address=req_word>=10'd832;
  assign ff_read_data=rst_n && !context_owned ? {upper_q,lower_q} : 128'b0;
  assign rsp_data=rst_n && rsp_valid && !rsp_error && !response_write ?
                  (response_bank ? upper_q : lower_q) : 64'b0;

  always_comb begin
    ce_n=ff_ce_n;we_n=ff_we_n;address=ff_address;write_data=ff_write_data;
    if(context_owned || !rst_n)begin
      ce_n=2'b11;we_n=2'b11;address='0;write_data='0;
      if(rst_n && accepted && !bad_address)begin
        ce_n[req_word[9]]=0;we_n[req_word[9]]=!req_write;
        address[9*req_word[9]+:9]=req_word[8:0];
        write_data[64*req_word[9]+:64]=req_data;
      end
    end
  end
  TS5N28HPCPSVTA512X64M4F lower_metadata (
    .CLK(clk),.CEB(ce_n[0]),.WEB(we_n[0]),.A(address[8:0]),.D(write_data[63:0]),.Q(lower_q)
  );
  TS5N28HPCPSVTA512X64M4F upper_metadata (
    .CLK(clk),.CEB(ce_n[1]),.WEB(we_n[1]),.A(address[17:9]),.D(write_data[127:64]),.Q(upper_q)
  );
  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      context_owned<=0;rsp_valid<=0;rsp_error<=0;response_bank<=0;response_write<=0;
    end else begin
      if(acquire_valid && acquire_ready)context_owned<=1;
      else if(release_valid && release_ready)context_owned<=0;
      if(rsp_valid && rsp_ready)rsp_valid<=0;
      if(accepted)begin
        rsp_valid<=1;rsp_error<=bad_address;
        response_bank<=req_word[9];response_write<=req_write;
      end
    end
  end
endmodule
