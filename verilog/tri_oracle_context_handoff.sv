`timescale 1ns/1ps
// One token's native32-head attention results -> leased existing metadata
// memories -> hardware common-unit selection -> in-place context conversion.
// row_query, row_head, row_error, row_data and row_value_exponent must all
// remain stable from row_valid assertion through row_ready. Producer errors
// must be final before assertion; asynchronous cancellation uses rst_n.
// metadata_block prevents NEW client work; existing work must drain before
// metadata_idle. Acquisition also requires all six client chip-enables idle.
// A successful lease destroys metadata: rebuild it before using that client.
// A terminal error invalidates all reads carrying the same context_tag.
module tri_oracle_context_handoff (
  input logic clk,rst_n,cfg_valid,
  output logic cfg_ready,
  input logic [31:0] cfg_tag,
  input logic [10:0] cfg_query,
  input logic signed [8:0] cfg_zero_exponent,
  input logic row_valid,
  output logic row_ready,
  input logic row_error,
  input logic [10:0] row_query,
  input logic [4:0] row_head,
  input logic [2047:0] row_data,
  input logic signed [7:0] row_value_exponent,
  input logic metadata_idle,
  output logic metadata_block,metadata_needs_rebuild,
  input logic metadata_rebuilt,
  output logic lease_active,
  input logic [5:0] metadata_ce_n,metadata_we_n,
  input logic [53:0] metadata_address,
  input logic [767:0] metadata_write_data,metadata_write_mask,
  output logic [767:0] metadata_read_data,
  output logic context_valid,
  output logic [31:0] context_tag,
  output logic [10:0] context_query,
  output logic signed [8:0] context_exponent,
  input logic read_req_valid,
  output logic read_req_ready,
  input logic [9:0] read_req_word,
  output logic read_rsp_valid,
  input logic read_rsp_ready,
  output logic read_rsp_error,
  output logic [63:0] read_rsp_data,
  input logic finish_valid,
  output logic finish_ready,done_valid,
  input logic done_ready,
  output logic done_error
);
  typedef enum logic [2:0] {Idle,Acquire,Pack,StartConvert,Convert,Context,Release,Done} state_t;
  state_t state;
  logic pack_clear_ready,pack_row_valid,pack_row_ready,pack_frame_ready,pack_frame_error;
  logic signed [8:0] pack_exponent;
  logic pack_req_valid,pack_rsp_ready;
  logic [9:0] pack_req_word;
  logic [63:0] pack_req_data;
  logic convert_start_ready,convert_done_valid,convert_done_error;
  logic convert_req_valid,convert_req_write,convert_rsp_ready;
  logic [9:0] convert_req_word;
  logic [63:0] convert_req_data;
  logic acquire_ready,release_ready,memory_req_valid,memory_req_ready,memory_req_write;
  logic [9:0] memory_req_word;
  logic [63:0] memory_req_data,memory_rsp_data;
  logic memory_rsp_valid,memory_rsp_ready,memory_rsp_error;
  logic bad_row,bad_read,quarantine;
  logic [767:0] client_read_data;

  assign cfg_ready=rst_n && state==Idle && pack_clear_ready && convert_start_ready && !lease_active && !memory_rsp_valid;
  assign metadata_block=!rst_n || state!=Idle || (cfg_valid && cfg_ready);
  assign quarantine=state==Release || state==Done;
  assign metadata_read_data=quarantine ? '0 : client_read_data;
  assign bad_row=row_error || row_query!=context_query;
  assign pack_row_valid=state==Pack && row_valid && !bad_row && !pack_frame_ready;
  assign row_ready=rst_n && state==Pack && !pack_frame_ready &&
                   (bad_row ? pack_clear_ready && row_valid : pack_row_ready);
  assign context_valid=rst_n && state==Context;
  assign read_req_ready=rst_n && state==Context && !bad_read && memory_req_ready && !finish_valid;
  assign read_rsp_valid=rst_n && state==Context && (bad_read || memory_rsp_valid);
  assign read_rsp_error=bad_read || memory_rsp_error;
  assign read_rsp_data=bad_read ? 64'b0 : memory_rsp_data;
  assign finish_ready=rst_n && state==Context && !bad_read && !memory_rsp_valid;
  assign done_valid=rst_n && state==Done;

  always_comb begin
    memory_req_valid=0;memory_req_write=0;memory_req_word=0;memory_req_data=0;memory_rsp_ready=0;
    case(state)
      Pack:begin
        memory_req_valid=pack_req_valid;memory_req_write=1;
        memory_req_word=pack_req_word;memory_req_data=pack_req_data;memory_rsp_ready=pack_rsp_ready;
      end
      Convert:begin
        memory_req_valid=convert_req_valid;memory_req_write=convert_req_write;
        memory_req_word=convert_req_word;memory_req_data=convert_req_data;memory_rsp_ready=convert_rsp_ready;
      end
      Context:begin
        memory_req_valid=read_req_valid && read_req_ready && read_req_word<256;
        memory_req_word=read_req_word;memory_rsp_ready=read_rsp_ready && !bad_read;
      end
      default:begin end
    endcase
  end

  tri_oracle_raw_context_shared_storage storage (
    .clk,.rst_n,.metadata_idle(metadata_idle),
    .acquire_valid(state==Acquire),.acquire_ready,
    .release_valid(state==Release),.release_ready,
    .metadata_ce_n(quarantine ? 6'b111111 : metadata_ce_n),.metadata_we_n,
    .metadata_address,.metadata_write_data,.metadata_write_mask,.metadata_read_data(client_read_data),
    .req_valid(memory_req_valid),.req_ready(memory_req_ready),.req_write(memory_req_write),
    .req_word(memory_req_word),.req_data(memory_req_data),.rsp_valid(memory_rsp_valid),
    .rsp_ready(memory_rsp_ready),.rsp_error(memory_rsp_error),.rsp_data(memory_rsp_data)
  );
  tri_oracle_raw_context_row_packer packer (
    .clk,.rst_n,.clear(cfg_valid && cfg_ready),.clear_ready(pack_clear_ready),.zero_exponent(cfg_zero_exponent),
    .row_valid(pack_row_valid),.row_ready(pack_row_ready),.row_head,.row_data,.row_value_exponent,
    .frame_ready(pack_frame_ready),.frame_error(pack_frame_error),.context_exponent(pack_exponent),
    .req_valid(pack_req_valid),.req_ready(state==Pack && memory_req_ready),.req_word(pack_req_word),.req_data(pack_req_data),
    .rsp_valid(state==Pack && memory_rsp_valid),.rsp_ready(pack_rsp_ready),.rsp_error(memory_rsp_error)
  );
  tri_oracle_raw_context_inplace_convert converter (
    .clk,.rst_n,.start_valid(state==StartConvert),.start_ready(convert_start_ready),.context_exponent,
    .done_valid(convert_done_valid),.done_ready(state==Convert),.done_error(convert_done_error),
    .req_valid(convert_req_valid),.req_ready(state==Convert && memory_req_ready),.req_write(convert_req_write),
    .req_word(convert_req_word),.req_data(convert_req_data),.rsp_valid(state==Convert && memory_rsp_valid),
    .rsp_ready(convert_rsp_ready),.rsp_error(memory_rsp_error),.rsp_data(memory_rsp_data)
  );

  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      state<=Idle;context_tag<=0;context_query<=0;context_exponent<=0;
      lease_active<=0;metadata_needs_rebuild<=1;done_error<=0;bad_read<=0;
    end else begin
      if(metadata_rebuilt && state==Idle && !(cfg_valid && cfg_ready))metadata_needs_rebuild<=0;
      case(state)
        Idle:if(cfg_valid && cfg_ready)begin
          context_tag<=cfg_tag;context_query<=cfg_query;context_exponent<=cfg_zero_exponent;
          done_error<=0;bad_read<=0;state<=Acquire;
        end
        Acquire:if(acquire_ready)begin lease_active<=1;metadata_needs_rebuild<=1;state<=Pack;end
        Pack:begin
          if(pack_frame_error && pack_clear_ready)begin done_error<=1;state<=Release;end
          else if(row_valid && row_ready && bad_row)begin done_error<=1;state<=Release;end
          else if(pack_frame_ready)begin context_exponent<=pack_exponent;state<=StartConvert;end
        end
        StartConvert:if(convert_start_ready)state<=Convert;
        Convert:if(convert_done_valid)begin
          if(convert_done_error)begin done_error<=1;state<=Release;end
          else state<=Context;
        end
        Context:begin
          if(read_req_valid && read_req_ready && read_req_word>=256)begin bad_read<=1;done_error<=1;end
          else if(bad_read && read_rsp_ready)bad_read<=0;
          if(memory_rsp_valid && memory_rsp_error)done_error<=1;
          if(finish_valid && finish_ready)state<=Release;
        end
        Release:if(release_ready)begin lease_active<=0;state<=Done;end
        Done:if(done_ready)state<=Idle;
        default:begin done_error<=1;state<=Release;end
      endcase
    end
  end
endmodule
