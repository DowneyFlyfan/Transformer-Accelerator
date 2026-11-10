`timescale 1ns/1ps
// Tri-Oracle Fig31.6.3: iterative token-table cursor and origin location table.
// Counts describe original positions [0, query_position], including the query.
// Local interfaces, storage realization and backward-query support are choices
// for this reconstruction; no physical area, timing or full-chip claim is made.
module tri_oracle_causal_token_size #(
  parameter int unsigned MAX_TOKENS=576,
  localparam int unsigned INDEX_W=MAX_TOKENS>1?$clog2(MAX_TOKENS):1,
  localparam int unsigned COUNT_W=$clog2(MAX_TOKENS+1)
)(
  input logic clk,rst_n,
  input logic frame_valid,
  output logic frame_ready,
  input logic map_valid,
  output logic map_ready,
  input logic [INDEX_W-1:0] map_origin,
  input logic map_last,
  input logic query_valid,
  output logic query_ready,
  input logic [INDEX_W-1:0] query_position,
  output logic out_valid,
  input logic out_ready,
  output logic [INDEX_W-1:0] out_origin,
  output logic [COUNT_W-1:0] out_count,
  output logic out_last,
  output logic error
);
  typedef enum logic [1:0] {IDLE,LOAD,WALK,EMIT} state_t;
  state_t state;
  logic loaded;
  logic [COUNT_W-1:0] mapped_tokens,root_count,cursor,target_end;
  logic [COUNT_W-1:0] visible_roots,emit_slot;
  logic [INDEX_W-1:0] token_origin[MAX_TOKENS];
  logic [INDEX_W-1:0] origin_location[MAX_TOKENS];
  logic [INDEX_W-1:0] location_origin[MAX_TOKENS];
  logic [COUNT_W-1:0] location_count[MAX_TOKENS];
  logic [INDEX_W-1:0] cursor_token,cursor_origin,cursor_location;

  // New frames take priority over queries only at the idle boundary.
  always_comb begin
    frame_ready=state==IDLE;
    map_ready=state==LOAD;
    query_ready=state==IDLE && loaded && !error && !frame_valid;
    out_valid=state==EMIT && emit_slot<visible_roots;
    out_origin='0;
    out_count='0;
    out_last=0;
    if(out_valid) begin
      out_origin=location_origin[emit_slot];
      out_count=location_count[emit_slot];
      out_last=emit_slot+1'b1==visible_roots;
    end
    cursor_token='0;
    cursor_origin='0;
    cursor_location='0;
    if(state==WALK && cursor!=target_end) begin
      cursor_token=INDEX_W'(cursor<target_end?cursor:cursor-1'b1);
      cursor_origin=token_origin[cursor_token];
      cursor_location=origin_location[cursor_origin];
    end
  end

  // No table-wide reset is needed: each new origin initializes its location,
  // and only positions below mapped_tokens may be read in this frame.
  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      state<=IDLE;
      loaded<=0;
      error<=0;
      mapped_tokens<='0;
      root_count<='0;
      cursor<='0;
      target_end<='0;
      visible_roots<='0;
      emit_slot<='0;
    end else begin
      case(state)
        IDLE: begin
          if(frame_valid) begin
            state<=LOAD;
            loaded<=0;
            error<=0;
            mapped_tokens<='0;
            root_count<='0;
            cursor<='0;
            target_end<='0;
            visible_roots<='0;
            emit_slot<='0;
          end else if(query_valid && query_ready) begin
            if(query_position>=mapped_tokens) begin
              error<=1;
              loaded<=0;
            end else begin
              target_end<=COUNT_W'(query_position)+1'b1;
              emit_slot<='0;
              state<=WALK;
            end
          end
        end
        LOAD: if(map_valid) begin
          if(map_origin>=MAX_TOKENS || map_origin>mapped_tokens ||
             (map_origin<mapped_tokens && token_origin[map_origin]!=map_origin) ||
             (mapped_tokens==MAX_TOKENS-1 && !map_last)) begin
            error<=1;
            loaded<=0;
            state<=IDLE;
          end else begin
            token_origin[mapped_tokens]<=map_origin;
            if(map_origin==mapped_tokens) begin
              origin_location[map_origin]<=INDEX_W'(root_count);
              location_origin[root_count]<=map_origin;
              location_count[root_count]<='0;
              root_count<=root_count+1'b1;
            end
            mapped_tokens<=mapped_tokens+1'b1;
            if(map_last) begin loaded<=1;state<=IDLE;end
          end
        end
        WALK: begin
          if(cursor<target_end) begin
            location_count[cursor_location]<=location_count[cursor_location]+1'b1;
            if(cursor_origin==cursor_token) visible_roots<=visible_roots+1'b1;
            cursor<=cursor+1'b1;
          end else if(cursor>target_end) begin
            location_count[cursor_location]<=location_count[cursor_location]-1'b1;
            if(cursor_origin==cursor_token) visible_roots<=visible_roots-1'b1;
            cursor<=cursor-1'b1;
          end else begin
            emit_slot<='0;
            state<=EMIT;
          end
        end
        EMIT: if(out_valid && out_ready) begin
          if(out_last) state<=IDLE;
          else emit_slot<=emit_slot+1'b1;
        end
        default: begin state<=IDLE;loaded<=0;error<=1;end
      endcase
    end
  end
endmodule
