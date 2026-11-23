`timescale 1ns/1ps
// Capture paired producer streams into full-precision external-memory rows.
// A done response is a frame lease: hold done_ready low while replaying it.
// Offered writes remain stable through abort and drain to acknowledgement.
module tri_oracle_residual_external_writer (
  input logic clk,rst_n,
  input logic cfg_valid,
  output logic cfg_ready,
  input logic [31:0] cfg_tag,
  input logic [63:0] cfg_base,
  input logic [9:0] cfg_rows,
  input logic abort_frame,
  input logic bypass_valid,
  output logic bypass_ready,
  input logic [31:0] bypass_tag,
  input logic [8:0] bypass_row,
  input logic [231:0] bypass_data,
  input logic normalization_valid,
  output logic normalization_ready,
  input logic [31:0] normalization_tag,
  input logic [8:0] normalization_row,
  input logic [127:0] normalization_data,
  input logic source_done_valid,source_done_error,
  output logic source_done_ready,
  input logic [31:0] source_done_tag,
  output logic write_valid,
  input logic write_ready,
  output logic [63:0] write_address,
  output logic [511:0] write_data,
  input logic write_rsp_valid,write_rsp_error,
  output logic write_rsp_ready,
  output logic done_valid,done_error,
  input logic done_ready,
  output logic [31:0] done_tag,
  output logic [7:0] done_code
);
  typedef enum logic[2:0] {Idle,Capture,Offer,AwaitAck,Done} state_t;
  state_t state;
  logic [63:0] base,offered_address;
  logic [31:0] tag;
  logic [9:0] rows,bypass_received,normalization_received,paired_rows,acknowledged_rows;
  logic bypass_pending,normalization_pending,packet_half,packet_full,source_seen,failed;
  logic [8:0] held_bypass_row,held_normalization_row,packet_first_row;
  logic [231:0] held_bypass;
  logic [127:0] held_normalization;
  logic [127:0] reconstructed_normalization;
  logic [511:0] packet,offered_data;
  logic [23:0] correction;
  logic [255:0] encoded_row;
  logic active,bypass_fire,normalization_fire,source_fire,pair_fire,fault_now,cfg_bad;
  logic [7:0] fault_code;
  logic [64:0] cfg_last_byte;

  tri_oracle_residual_replay_row codec (
    .write_bypass(held_bypass),.write_normalization(held_normalization),.write_padding(correction),
    .read_bypass(held_bypass),.read_padding(correction),.read_normalization(reconstructed_normalization)
  );

  always_comb begin
    cfg_last_byte={1'b0,cfg_base}+({50'd0,cfg_rows,5'd0}-65'd1);
    cfg_bad=cfg_rows<10'd2 || cfg_rows>10'd512 || cfg_rows[0] ||
            cfg_base[5:0]!=0 || cfg_last_byte[64];
    active=state==Capture || state==Offer || state==AwaitAck;
    cfg_ready=rst_n && state==Idle && !abort_frame;
    bypass_ready=rst_n && active && !failed && !abort_frame && !source_seen &&
                 !bypass_pending && bypass_received<rows;
    normalization_ready=rst_n && active && !failed && !abort_frame && !source_seen &&
                        !normalization_pending && normalization_received<rows;
    source_done_ready=rst_n && active && !source_seen;
    bypass_fire=bypass_valid && bypass_ready;
    normalization_fire=normalization_valid && normalization_ready;
    source_fire=source_done_valid && source_done_ready;
    fault_now=0;fault_code=0;
    if(active)begin
      if(abort_frame)begin fault_now=1;fault_code=8'h02;end
      else if(bypass_fire && ({1'b0,bypass_row}!==bypass_received || bypass_tag!==tag))begin
        fault_now=1;fault_code=8'h03;
      end else if(normalization_fire &&
                  ({1'b0,normalization_row}!==normalization_received || normalization_tag!==tag))begin
        fault_now=1;fault_code=8'h04;
      end else if((bypass_valid && bypass_received>=rows) ||
                  (normalization_valid && normalization_received>=rows))begin
        fault_now=1;fault_code=8'h05;
      end else if(source_fire && (source_done_error!==1'b0 || source_done_tag!==tag ||
                  bypass_received!=rows || normalization_received!=rows ||
                  bypass_valid || normalization_valid))begin
        fault_now=1;fault_code=8'h06;
      end else if(state==AwaitAck && write_rsp_valid && write_rsp_error!==1'b0)begin
        fault_now=1;fault_code=8'h07;
      end else if(bypass_pending && normalization_pending && held_bypass_row!==held_normalization_row)begin
        fault_now=1;fault_code=8'h08;
      end else if(bypass_pending && normalization_pending &&
                  reconstructed_normalization!==held_normalization)begin
        fault_now=1;fault_code=8'h09;
      end
    end
    encoded_row={correction,held_bypass};
    pair_fire=rst_n && active && !failed && !fault_now && !packet_full &&
              bypass_pending && normalization_pending;
    write_valid=rst_n && state==Offer;
    write_address=write_valid ? offered_address : 64'd0;
    write_data=write_valid ? offered_data : 512'd0;
    write_rsp_ready=rst_n && state==AwaitAck;
    done_valid=rst_n && state==Done;
    done_error=failed;
    done_tag=tag;
  end

  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      state<=Idle;base<=0;tag<=0;rows<=0;
      bypass_received<=0;normalization_received<=0;paired_rows<=0;acknowledged_rows<=0;
      bypass_pending<=0;normalization_pending<=0;packet_half<=0;packet_full<=0;
      source_seen<=0;failed<=0;done_code<=0;
      held_bypass_row<=0;held_normalization_row<=0;packet_first_row<=0;
    end else begin
      if(bypass_fire)begin
        held_bypass<=bypass_data;held_bypass_row<=bypass_row;
        bypass_pending<=1;bypass_received<=bypass_received+10'd1;
      end
      if(normalization_fire)begin
        held_normalization<=normalization_data;held_normalization_row<=normalization_row;
        normalization_pending<=1;normalization_received<=normalization_received+10'd1;
      end
      if(source_fire)source_seen<=1;
      if(fault_now && !failed)begin failed<=1;done_code<=fault_code;end
      if(pair_fire)begin
        bypass_pending<=0;normalization_pending<=0;paired_rows<=paired_rows+10'd1;
        if(!packet_half)begin
          packet[255:0]<=encoded_row;packet_first_row<=held_bypass_row;packet_half<=1;
        end else begin packet[511:256]<=encoded_row;packet_half<=0;packet_full<=1;end
      end
      case(state)
        Idle:if(cfg_valid && cfg_ready)begin
          base<=cfg_base;tag<=cfg_tag;rows<=cfg_rows;
          bypass_received<=0;normalization_received<=0;paired_rows<=0;acknowledged_rows<=0;
          bypass_pending<=0;normalization_pending<=0;packet_half<=0;packet_full<=0;
          source_seen<=0;failed<=cfg_bad;done_code<=cfg_bad ? 8'h01:8'h00;
          state<=cfg_bad ? Done:Capture;
        end
        Capture:begin
          if(failed || fault_now)state<=Done;
          else if(packet_full)begin
            offered_address<=base+{50'd0,packet_first_row[8:1],6'd0};
            offered_data<=packet;state<=Offer;
          end else if(source_seen && paired_rows==rows && acknowledged_rows==rows &&
                      !bypass_pending && !normalization_pending && !packet_half)state<=Done;
        end
        Offer:if(write_valid && write_ready)state<=AwaitAck;
        AwaitAck:if(write_rsp_valid && write_rsp_ready)begin
          packet_full<=0;
          if(failed || fault_now)state<=Done;
          else begin acknowledged_rows<=acknowledged_rows+10'd2;state<=Capture;end
        end
        Done:if(done_ready)state<=Idle;
        default:state<=Idle;
      endcase
    end
  end
endmodule
