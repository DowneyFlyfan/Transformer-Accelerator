`timescale 1ns/1ps
`default_nettype none
// First corrected GREEN cases1/2 only. Actual SAME raw32 C and its arithmetic, synthetic
// external memories/native DOWN0/registered routing proxy. No physical fabric,
// weight execution, PRE/POST provenance or real store lease is claimed here.
module real_C_cfg_idle_boundary_tb_v3;
  import tri_oracle_FF_frame_types_v2::*;
  localparam integer N=264,B=16;
  localparam logic [63:0] RAW=64'h10000000,META=64'h11000000,WGAMMA=64'h12000000,
    TABLE=64'h13000000,DOWN=64'h14000000,GAMMA=64'h15000000,
    TARGET=64'h16000000,TMETA=64'h17000000;
  localparam logic [63:0] FRAME_BYTES=64'd2203648;
  logic clk,rst_n;
  integer case_id,cycle;
  logic warm_active,warm_cfg_valid,warm_row_valid,warm_retire_valid,warm_finished;
  logic [9:0] warm_rank;
  logic proxy_owner_held,proxy_cfg_held,proxy_cfg_done;
  frame_t proxy_frame;
  integer proxy_captures,physical_target_cfgs,client_cfg_ACKs,target_demands,target_retires;
  integer proxy_delay_edges,first_target_strips,first_row_done_edge;
  logic frame_seen,batch_seen,native_owned,final_seen,terminal_seen;
  integer packets,ngroup,ntoken,final_cycle,native_terminals;

  // Consumer port names intentionally match the unchanged baseline module.
  logic external_cancel_q,owner_held,parent_fault,correction_enable_cfg;
  logic frame_valid,frame_ready,batch_valid,batch_ready,batch_launch_valid,batch_launch_ready;
  frame_t frame_context,held_frame;
  batch_t batch_context,held_batch;
  native_cfg_t batch_launch_context;
  logic in_valid,in_ready,in_last,native_done_fire,native_done_error;
  logic [31:0] in_tag,native_done_tag;
  logic [3:0] in_token;
  logic [15:0] in_start;
  logic [7:0] in_count;
  logic [5119:0] in_data;
  logic req_valid,req_ready,rsp_valid,rsp_last,rsp_error,rsp_ready,physical_unowned_response;
  logic [63:0] req_address,rsp_data;
  logic [4:0] req_length;
  logic write_req_valid,write_req_ready,write_data_valid,write_data_ready,write_last;
  logic write_rsp_valid,write_rsp_error,write_rsp_ready;
  logic [63:0] write_address,write_data;
  logic [4:0] write_length;
  logic [7:0] write_strobe;
  logic c_read_selected,c_cfg_valid,c_demand_valid,c_retire_valid,c_output_ready;
  logic [9:0] c_demand_rank,c_demand_root;
  logic c_cfg_ready,c_demand_ready,c_retire_ready,c_fault,c_producer_idle,c_port_idle,c_idle;
  logic [9:0] c_accepted_rows,c_completed_rows;
  logic c_output_valid,c_read_request_valid,c_read_response_valid,c_output_fire;
  logic c_output_last,c_output_error;
  logic [31:0] c_output_tag;
  logic [9:0] c_output_index;
  logic [3:0] c_output_count;
  logic row_done_valid,row_done_error,row_done_ready,batch_done_valid,batch_done_error,batch_done_ready;
  logic frame_done_valid,frame_done_error,frame_done_ready;
  logic [31:0] row_done_tag;
  logic [9:0] row_done_rank,completed_rows;
  logic active,epoch_fault,abort_registered,native_input_drained,independent_admission_fault;
  logic scratch_ACK,raw_ACK,metadata_ACK;
  logic [9:0] ACK_rank;

  // These are direct ACTUAL source ports, never written as model status.
  logic src_cfg_valid,src_cfg_ready,src_row_valid,src_row_ready,src_retire_valid,src_retire_ready;
  logic src_new_image,src_out_valid,src_out_last,src_out_error,src_out_ready;
  logic [31:0] src_cfg_tag,src_row_tag,src_out_tag;
  logic [4:0] src_cfg_layer,src_row_layer;
  logic [15:0] src_cfg_epoch,src_row_epoch;
  logic [9:0] src_image_start,src_input_rows,src_row_rank,src_row_root,src_out_index;
  logic [3:0] src_out_count;
  logic [63:0] src_raw_base,src_raw_bytes,src_meta_base,src_meta_bytes,src_gamma_base,src_gamma_bytes;
  logic signed [7:0] src_gamma_exponent;
  logic [63:0] src_out_activation;
  logic signed [8:0] src_out_exponent;
  logic [7:0] src_out_mask,src_out_negative,src_out_normalized_negative;
  logic src_req_valid,src_req_ready,src_rsp_valid,src_rsp_ready,src_rsp_last,src_rsp_error;
  logic [63:0] src_req_address,src_rsp_data;
  logic [4:0] src_req_length;
  logic src_fault,src_producer_idle,src_port_idle,src_idle;
  logic [9:0] src_accepted,src_completed;
  logic physical_cfg_fire,physical_target_cfg_fire;
  integer warm_strips,warm_completed_seen,warm_retires,warm_cfgs;
  integer c_read_requests,c_read_beats,c_metadata_requests,c_raw_requests,c_gamma_requests;
  integer c_metadata_beats,c_raw_beats,c_gamma_beats,c_kind,c_len,c_beat;
  logic c_mem_busy,c_mem_offer;
  logic [63:0] c_mem_address;
  integer ff_read_requests,ff_read_beats,ff_table_words,ff_meta_words;
  integer ff_len,ff_beat,ff_kind;
  logic ff_busy,ff_offer;
  logic [63:0] ff_address;
  integer wr_len,wr_beat,wr_kind,wr_token,ack_delay;
  logic wr_owned,wr_complete,ack_offer;
  logic [63:0] wr_address,wr_words[0:7];
  logic [63:0] scratch_words[0:16383],target_words[0:1023],target_metadata_words[0:1];
  logic scratch_valid[0:16383],target_valid[0:1023],target_metadata_valid;
  integer scratch_acks[0:15],scratch_total,raw_total,meta_total,write_requests,write_beats,write_ACKs;
  logic target_cfg_post_seen;
  integer cfg_edge,fault_edge;
  logic previous_cfg_valid,previous_cfg_ready;
  frame_t previous_cfg_frame;

  function automatic void require(input logic value,input string why);
    if(value!==1'b1)$fatal(1,"REAL_C_IDLE_ASSERT case=%0d cycle=%0d %s",case_id,cycle,why);
  endfunction
  function automatic logic quiet_C();
    return src_producer_idle===1'b1 && src_port_idle===1'b1 && src_out_valid===1'b0 &&
      src_req_valid===1'b0 && src_rsp_valid===1'b0 && src_fault===1'b0;
  endfunction
  function automatic logic [127:0] original_metadata(input integer rank);
    return {5'd0,16'd1,5'd0,10'(5+2*rank+1),10'(rank),10'(2*rank+1),8'd0,64'd1};
  endfunction
  function automatic logic [7:0] gamma_byte(input integer offset);
    return offset%3==2 ? 8'h7f:8'hff;
  endfunction
  function automatic logic [63:0] gamma_word(input integer offset);
    logic [63:0] value;
    for(integer k=0;k<8;k++)value[k*8+:8]=gamma_byte(offset+k);
    return value;
  endfunction
  function automatic logic [63:0] source_word(input logic [63:0] address);
    logic [127:0] value;integer rank,index;
    if(address>=RAW+5*8192 && address<RAW+FRAME_BYTES)return 64'd0;
    if(address>=META && address<META+N*16)begin
      rank=int'((address-META)/16);value=original_metadata(rank);
      return address[3] ? value[127:64]:value[63:0];
    end
    if(address>=WGAMMA && address<WGAMMA+6144)return gamma_word(int'(address-WGAMMA));
    if(address>=GAMMA+12288 && address<GAMMA+12288+6144)return gamma_word(int'(address-GAMMA));
    if(address>=TARGET+5*8192 && address<TARGET+6*8192)begin
      index=int'((address-TARGET-5*8192)/8);
      require(target_valid[index]===1'b1,"actual C target read requires physical RAW ACK visibility");
      return target_words[index];
    end
    if(address>=TMETA && address<TMETA+16)begin
      require(target_metadata_valid===1'b1,"actual C metadata read requires physical metadata ACK visibility");
      return target_metadata_words[int'((address-TMETA)/8)];
    end
    $fatal(1,"REAL_C_IDLE_UNKNOWN_SOURCE_ADDRESS address=%016h",address);return 'x;
  endfunction
  function automatic logic [63:0] consumer_word(input logic [63:0] address);
    integer index;
    if(address>=TABLE && address<TABLE+1024)return 0;
    if((address>=RAW+5*8192 && address<RAW+FRAME_BYTES) || (address>=META && address<META+N*16))return source_word(address);
    if(address>=DOWN && address<DOWN+B*8192)begin
      index=int'((address-DOWN)/8);require(scratch_valid[index]===1'b1,"replay needs actual successful scratch ACK");return scratch_words[index];
    end
    $fatal(1,"REAL_C_IDLE_UNKNOWN_CONSUMER_ADDRESS address=%016h",address);return 'x;
  endfunction

  // Registered inputs only; no returning C status feeds a request builder.
  always_comb begin
    frame_context='0;
    frame_context.common.source_tag=32'h1000;frame_context.common.source_layer=0;frame_context.common.source_epoch=1;
    frame_context.common.image_start=5;frame_context.common.input_count=N;frame_context.common.kept_count=N;
    frame_context.common.bundle=128'h1234;frame_context.common.phase=1;frame_context.common.normalization_role=1;
    frame_context.common.raw_base=RAW;frame_context.common.raw_bytes=FRAME_BYTES;
    frame_context.common.metadata_base=META;frame_context.common.metadata_bytes=N*16;
    frame_context.common.down_table_base=TABLE;frame_context.common.down_scratch_base=DOWN;frame_context.common.down_scratch_bytes=B*8192;
    frame_context.common.target_raw_base=TARGET;frame_context.common.target_raw_bytes=FRAME_BYTES;
    frame_context.common.target_metadata_base=TMETA;frame_context.common.target_metadata_bytes=N*16;
    frame_context.common.gamma_table_base=GAMMA;frame_context.common.gamma_table_bytes=276480;
    frame_context.common.target_gamma_base=GAMMA+12288;frame_context.common.target_gamma_bytes=6144;
    frame_context.common.target_gamma_exponent=-23;frame_context.common.target_gamma_index=2;
    frame_context.common.target_layer=1;frame_context.common.target_epoch=2;frame_context.common.target_tag_base=32'h2000;
    frame_context.common.target_count=N;frame_context.common.target_role=0;
    frame_context.common.gate_weight_unit=-8;frame_context.common.up_weight_unit=-9;frame_context.common.down_weight_unit=-7;
    frame_context.upstream_input_count=N;frame_context.post_code_base=64'h20000000;
    frame_context.post_feature_base=64'h21000000;frame_context.post_feature_bytes=N*768;
    frame_context.gate_base=64'h30000000;frame_context.up_base=64'h32000000;frame_context.down_base=64'h34000000;
    frame_context.gate_sign_base=64'h36000000;frame_context.up_sign_base=64'h38000000;
    frame_context.gate_sign_bytes=1441792;frame_context.up_sign_bytes=1441792;
    frame_context.row_units_base=64'h3a000000;frame_context.row_units_bytes=4544;
    frame_context.intermediate_base=64'h3b000000;frame_context.intermediate_bytes=B*5632;
    frame_context.common.protected_count=1;frame_context.common.protected_base[0]=frame_context.intermediate_base;
    frame_context.common.protected_bytes[0]=frame_context.intermediate_bytes;
    batch_context='0;batch_context.tag=32'h1000;batch_context.start_rank=0;batch_context.tokens=B;
    for(integer t=0;t<B;t++)begin
      batch_context.rows[t].source_tag=32'h1000+32'(t);batch_context.rows[t].original_root=10'(2*t+1);
      batch_context.rows[t].raw_input_rank=10'(t);batch_context.rows[t].upstream_input_rank=10'(t);
      batch_context.rows[t].frame_rank=10'(t);batch_context.rows[t].activation_unit=-9'sd6;
    end
  end
  assign external_cancel_q=1'b0;
  assign parent_fault=1'b0;
  assign correction_enable_cfg=1'b0;
  assign owner_held=proxy_owner_held;
  assign frame_valid=rst_n && proxy_owner_held && !frame_seen;
  assign batch_valid=rst_n && frame_seen && !batch_seen;
  assign batch_launch_ready=rst_n && !native_owned;
  assign native_done_fire=rst_n && native_owned && final_seen && !terminal_seen && cycle==final_cycle+3;
  assign native_done_error=1'b0;
  assign native_done_tag=32'h1000;
  assign physical_unowned_response=1'b0;
  assign row_done_ready=1'b0;
  assign batch_done_ready=1'b0;
  assign frame_done_ready=1'b0;

  assign src_cfg_valid=warm_active ? warm_cfg_valid:proxy_cfg_held;
  assign src_new_image=1'b0;
  assign src_cfg_tag=warm_active ? 32'h1000:proxy_frame.common.target_tag_base;
  assign src_cfg_layer=warm_active ? 5'd0:proxy_frame.common.target_layer;
  assign src_cfg_epoch=warm_active ? 16'd1:proxy_frame.common.target_epoch;
  assign src_image_start=warm_active ? 10'd5:proxy_frame.common.image_start;
  assign src_input_rows=warm_active ? 10'd264:proxy_frame.common.target_count;
  assign src_raw_base=warm_active ? RAW:proxy_frame.common.target_raw_base;
  assign src_raw_bytes=warm_active ? FRAME_BYTES:proxy_frame.common.target_raw_bytes;
  assign src_meta_base=warm_active ? META:proxy_frame.common.target_metadata_base;
  assign src_meta_bytes=warm_active ? 64'(N*16):proxy_frame.common.target_metadata_bytes;
  assign src_gamma_base=warm_active ? WGAMMA:proxy_frame.common.target_gamma_base;
  assign src_gamma_bytes=warm_active ? 64'd6144:proxy_frame.common.target_gamma_bytes;
  assign src_gamma_exponent=warm_active ? -8'sd23:proxy_frame.common.target_gamma_exponent;
  assign src_row_valid=warm_active ? warm_row_valid:(proxy_cfg_done && c_demand_valid);
  assign src_row_rank=warm_active ? warm_rank:c_demand_rank;
  assign src_row_root=warm_active ? 10'(2*int'(warm_rank)+1):c_demand_root;
  assign src_row_tag=warm_active ? 32'h1000+32'(warm_rank):held_frame.common.target_tag_base+32'(c_demand_rank);
  assign src_row_layer=warm_active ? 5'd0:held_frame.common.target_layer;
  assign src_row_epoch=warm_active ? 16'd1:held_frame.common.target_epoch;
  assign src_retire_valid=warm_active ? warm_retire_valid:(proxy_cfg_done && c_retire_valid);
  assign src_out_ready=warm_active ? 1'b1:c_output_ready;
  assign physical_cfg_fire=src_cfg_valid && src_cfg_ready;
  assign physical_target_cfg_fire=!warm_active && physical_cfg_fire;
  // Ready is the actual forwarded physical ACK, never proxy-capture ACK.
  assign c_cfg_ready=!warm_active && proxy_cfg_held && src_cfg_ready;
  assign c_demand_ready=!warm_active && proxy_cfg_done && src_row_ready;
  assign c_retire_ready=!warm_active && proxy_cfg_done && src_retire_ready;
  assign c_fault=src_fault;
  assign c_idle=src_idle;
  assign c_producer_idle=src_producer_idle;
  assign c_port_idle=src_port_idle;
  assign c_accepted_rows=src_accepted;
  assign c_completed_rows=src_completed;
  assign c_output_valid=src_out_valid;
  assign c_read_request_valid=src_req_valid;
  assign c_read_response_valid=src_rsp_valid;
  assign c_output_fire=src_out_valid && src_out_ready && !warm_active;
  assign c_output_last=src_out_last;
  assign c_output_error=src_out_error;
  assign c_output_tag=src_out_tag;
  assign c_output_index=src_out_index;
  assign c_output_count=src_out_count;

  tri_oracle_raw32_residual_commit_frame_v4 consumer(.*);
  tri_oracle_raw32_frame_source_v1 physical_C(
    .clk,.rst_n,.abort_valid(1'b0),.cfg_valid(src_cfg_valid),.cfg_ready(src_cfg_ready),
    .cfg_new_image(src_new_image),.cfg_tag_base(src_cfg_tag),.cfg_layer(src_cfg_layer),.cfg_epoch(src_cfg_epoch),
    .cfg_image_start(src_image_start),.cfg_input_rows(src_input_rows),.cfg_raw_frame_base(src_raw_base),.cfg_raw_frame_bytes(src_raw_bytes),
    .cfg_metadata_base(src_meta_base),.cfg_metadata_bytes(src_meta_bytes),.cfg_gamma_base(src_gamma_base),.cfg_gamma_bytes(src_gamma_bytes),
    .cfg_gamma_exponent(src_gamma_exponent),.row_request_valid(src_row_valid),.row_request_ready(src_row_ready),
    .row_request_original_root(src_row_root),.row_request_input_rank(src_row_rank),.row_request_tag(src_row_tag),
    .row_request_layer(src_row_layer),.row_request_epoch(src_row_epoch),.out_valid(src_out_valid),.out_last(src_out_last),
    .out_error(src_out_error),.out_ready(src_out_ready),.out_tag(src_out_tag),.out_index(src_out_index),.out_count(src_out_count),
    .out_activation(src_out_activation),.out_exponent(src_out_exponent),.out_outlier_mask(src_out_mask),
    .out_outlier_negative(src_out_negative),.out_normalized_negative(src_out_normalized_negative),
    .read_req_valid(src_req_valid),.read_req_ready(src_req_ready),.read_req_address(src_req_address),.read_req_length(src_req_length),
    .read_rsp_valid(src_rsp_valid),.read_rsp_last(src_rsp_last),.read_rsp_error(src_rsp_error),.read_rsp_ready(src_rsp_ready),.read_rsp_data(src_rsp_data),
    .retire_valid(src_retire_valid),.retire_ready(src_retire_ready),.row_source_error(src_fault),
    .producer_idle(src_producer_idle),.port_idle(src_port_idle),.idle(src_idle),.accepted_rows(src_accepted),.completed_rows(src_completed));

  // Two explicit external memory ports share actual ACK-backed scratch/target
  // data. They are test models, not two C instances or an added physical bank.
  assign src_req_ready=rst_n && !c_mem_busy && !c_mem_offer;
  assign src_rsp_valid=c_mem_offer;
  assign src_rsp_last=c_beat+1==c_len;
  assign src_rsp_error=1'b0;
  assign req_ready=rst_n && !ff_busy && !ff_offer;
  assign rsp_valid=ff_offer;
  assign rsp_last=ff_beat+1==ff_len;
  assign rsp_error=1'b0;
  assign write_req_ready=rst_n && !wr_owned && !ack_offer;
  assign write_data_ready=rst_n && wr_owned && !wr_complete;
  assign write_rsp_valid=ack_offer;
  assign write_rsp_error=1'b0;

  always_ff @(posedge clk or negedge rst_n)begin : source_memory
    if(!rst_n)begin
      c_mem_busy<=0;c_mem_offer<=0;c_mem_address<=0;c_len<=0;c_beat<=0;src_rsp_data<=0;c_kind<=0;
      c_read_requests<=0;c_read_beats<=0;c_metadata_requests<=0;c_raw_requests<=0;c_gamma_requests<=0;
      c_metadata_beats<=0;c_raw_beats<=0;c_gamma_beats<=0;
    end else begin
      if(src_req_valid && src_req_ready)begin
        require(!$isunknown({src_req_address,src_req_length}) && src_req_address[2:0]==0,"actual C known aligned request");
        c_mem_busy<=1;c_mem_address<=src_req_address;c_len<=int'(src_req_length);c_beat<=0;c_read_requests<=c_read_requests+1;
        if(src_req_address>=META && src_req_address<META+N*16)begin
          require(warm_active && src_req_length==2 && src_req_address==META+64'(src_accepted-1)*16,"actual metadata address uses admitted dense rank");
          c_kind<=0;c_metadata_requests<=c_metadata_requests+1;
        end else if(src_req_address>=RAW+5*8192 && src_req_address<RAW+FRAME_BYTES)begin
          require(warm_active && src_req_length==4 && src_req_address[4:0]==0,"actual raw source four-beat strip");
          c_kind<=1;c_raw_requests<=c_raw_requests+1;
        end else if((src_req_address>=WGAMMA && src_req_address<WGAMMA+6144) ||
                    (src_req_address>=GAMMA+12288 && src_req_address<GAMMA+12288+6144))begin
          require(src_req_length==3,"actual three-beat signed24 gamma strip");c_kind<=2;c_gamma_requests<=c_gamma_requests+1;
        end else if(src_req_address>=TMETA && src_req_address<TMETA+16)begin
          require(!warm_active && target_metadata_valid && src_req_length==2,"target metadata physically committed before source read");c_kind<=3;
        end else if(src_req_address>=TARGET+5*8192 && src_req_address<TARGET+6*8192)begin
          require(!warm_active && src_req_length==4,"target raw actual reader shape");c_kind<=4;
        end else require(0,"actual C read outside explicit original/ACK-committed target extents");
      end
      if(c_mem_busy && !c_mem_offer)begin src_rsp_data<=source_word(c_mem_address+64'(c_beat)*8);c_mem_offer<=1;end
      if(c_mem_offer && src_rsp_ready)begin
        require(!$isunknown({src_rsp_data,src_rsp_last}) && c_mem_busy,"owned known actual C read response");
        c_mem_offer<=0;c_read_beats<=c_read_beats+1;
        if(c_kind==0)c_metadata_beats<=c_metadata_beats+1;
        if(c_kind==1)c_raw_beats<=c_raw_beats+1;
        if(c_kind==2)c_gamma_beats<=c_gamma_beats+1;
        if(c_beat+1==c_len)c_mem_busy<=0;else c_beat<=c_beat+1;
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n)begin : consumer_memory
    integer index,t,k;
    if(!rst_n)begin
      ff_busy<=0;ff_offer<=0;ff_address<=0;ff_len<=0;ff_beat<=0;ff_kind<=0;rsp_data<=0;
      ff_read_requests<=0;ff_read_beats<=0;ff_table_words<=0;ff_meta_words<=0;
      wr_owned<=0;wr_complete<=0;ack_offer<=0;wr_address<=0;wr_len<=0;wr_beat<=0;wr_kind<=0;wr_token<=0;ack_delay<=0;
      scratch_total<=0;raw_total<=0;meta_total<=0;write_requests<=0;write_beats<=0;write_ACKs<=0;target_metadata_valid<=0;
      for(k=0;k<16384;k++)scratch_valid[k]<=0;
      for(k=0;k<1024;k++)target_valid[k]<=0;
      for(k=0;k<B;k++)scratch_acks[k]<=0;
      for(k=0;k<8;k++)wr_words[k]<=0;
    end else begin
      if(req_valid && req_ready)begin
        require(!$isunknown({req_address,req_length}) && req_address[2:0]==0,"known aligned consumer request");
        ff_busy<=1;ff_address<=req_address;ff_len<=int'(req_length);ff_beat<=0;ff_read_requests<=ff_read_requests+1;
        if(req_address>=TABLE && req_address<TABLE+1024)begin
          require(req_length==8 && req_address==TABLE+64'(ff_table_words/8)*64,"ordered128word immutable zero table preflight");ff_kind<=0;
        end else if(req_address>=META && req_address<META+B*16)begin require(req_length==2,"consumer metadata two beats");ff_kind<=1;end
        else if(req_address>=RAW+5*8192 && req_address<RAW+(5+B)*8192)begin require(req_length==8 && req_address[5:0]==0,"consumer source dense raw rank line");ff_kind<=2;end
        else if(req_address>=DOWN && req_address<DOWN+B*8192)begin require(req_length==8 && req_address[5:0]==0,"actual scratch replay line");ff_kind<=3;end
        else require(0,"consumer read outside declared table/original/scratch intervals");
      end
      if(ff_busy && !ff_offer)begin rsp_data<=consumer_word(ff_address+64'(ff_beat)*8);ff_offer<=1;end
      if(ff_offer && rsp_ready)begin
        require(!$isunknown(rsp_data) && ff_busy,"known owned consumer response");ff_offer<=0;ff_read_beats<=ff_read_beats+1;
        if(ff_kind==0)begin
          $display("REAL_C_SCALE_WORD cycle=%0d index=%0d address=%016h data=%016h last=%b error=0",cycle,ff_table_words,ff_address+64'(ff_beat)*8,rsp_data,rsp_last);
          require(rsp_data===64'd0,"all16 decrements0/high16padding0");ff_table_words<=ff_table_words+1;
        end
        if(ff_kind==1)ff_meta_words<=ff_meta_words+1;
        if(ff_beat+1==ff_len)ff_busy<=0;else ff_beat<=ff_beat+1;
      end
      if(write_req_valid && write_req_ready)begin
        require(!$isunknown({write_address,write_length}) && write_address[2:0]==0,"known owned write header");
        wr_owned<=1;wr_complete<=0;wr_address<=write_address;wr_len<=int'(write_length);wr_beat<=0;ack_delay<=0;write_requests<=write_requests+1;
        if(write_address>=DOWN && write_address<DOWN+B*8192)begin
          t=int'((write_address-DOWN)/8192);require(write_length==8 && write_address==DOWN+64'(t)*8192+64'(scratch_acks[t])*64,"each scratch line exactly once per actual token");wr_kind<=0;wr_token<=t;
        end else if(write_address>=TARGET+5*8192 && write_address<TARGET+6*8192)begin
          require(write_length==8 && write_address==TARGET+5*8192+64'(raw_total)*64,"first target raw compact rank0 sequential lines");wr_kind<=1;
        end else if(write_address==TMETA)begin
          require(write_length==2 && raw_total==128 && scratch_total==2048 && native_terminals==1,"metadata follows all actual scratch/native terminal and first row RAW ACKs");wr_kind<=2;
        end else require(0,"unexpected consumer write region");
      end
      if(write_data_valid && write_data_ready)begin
        require(wr_owned && !$isunknown({write_data,write_last,write_strobe}) && write_strobe==8'hff &&
          write_last==(wr_beat+1==wr_len),"physical write beat ownership/strobe/LAST");
        wr_words[wr_beat]<=write_data;write_beats<=write_beats+1;
        if(wr_kind==0)require(write_data===64'd0,"scratch data is actual DOWN0 native payload");
        if(wr_beat+1==wr_len)wr_complete<=1;else wr_beat<=wr_beat+1;
      end
      if(wr_owned && wr_complete && !ack_offer)begin ack_delay<=ack_delay+1;if(ack_delay==2)ack_offer<=1;end
      if(ack_offer && write_rsp_ready)begin
        require(wr_owned && wr_complete,"successful known owned complete write ACK");
        if(wr_kind==0)begin
          index=int'((wr_address-DOWN)/8);
          for(k=0;k<8;k++)begin require(scratch_valid[index+k]===1'b0,"scratch no duplicate commits");scratch_words[index+k]<=wr_words[k];scratch_valid[index+k]<=1;end
          scratch_acks[wr_token]<=scratch_acks[wr_token]+1;scratch_total<=scratch_total+1;
        end else if(wr_kind==1)begin
          index=int'((wr_address-TARGET-5*8192)/8);
          for(k=0;k<8;k++)begin require(target_valid[index+k]===1'b0,"target no duplicate commits");target_words[index+k]<=wr_words[k];target_valid[index+k]<=1;end
          raw_total<=raw_total+1;
        end else begin
          require(target_metadata_valid===1'b0 && wr_words[0]===64'd1 &&
            wr_words[1]==={5'd0,16'd2,5'd1,10'd6,10'd0,10'd1,8'd0},"captured target metadata exact known zero residual identity/unit/EPS");
          target_metadata_words[0]<=wr_words[0];target_metadata_words[1]<=wr_words[1];target_metadata_valid<=1;meta_total<=meta_total+1;
        end
        ack_offer<=0;wr_owned<=0;wr_complete<=0;write_ACKs<=write_ACKs+1;
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n)begin : native_and_proxy
    if(!rst_n)begin
      cycle<=0;frame_seen<=0;batch_seen<=0;native_owned<=0;packets<=0;ngroup<=0;ntoken<=0;
      final_seen<=0;final_cycle<=0;terminal_seen<=0;native_terminals<=0;
      in_valid<=0;in_tag<=0;in_token<=0;in_start<=0;in_count<=0;in_last<=0;in_data<=0;
      proxy_owner_held<=0;proxy_cfg_held<=0;proxy_cfg_done<=0;proxy_frame<='0;proxy_captures<=0;proxy_delay_edges<=0;
      physical_target_cfgs<=0;client_cfg_ACKs<=0;target_demands<=0;target_retires<=0;
    end else begin
      cycle<=cycle+1;require(cycle<20000000,"finite20million cycle source deadline");
      if(warm_finished && src_idle===1'b1 && quiet_C() && src_accepted==N && src_completed==N)proxy_owner_held<=1;
      if(frame_valid && frame_ready)begin require(proxy_owner_held && src_idle===1'b1 && src_accepted==N && src_completed==N,"consumer admission real retired N/N");frame_seen<=1;end
      if(batch_valid && batch_ready)batch_seen<=1;
      if(batch_launch_valid && batch_launch_ready)begin
        require(!native_owned && batch_launch_context.tokens==16 && batch_launch_context.tag==32'h1000 &&
          batch_launch_context.row_enable===1'b1 && batch_launch_context.correction_enable===1'b0 &&
          batch_launch_context.input_features==2048 && batch_launch_context.intermediate_features==5632 && batch_launch_context.output_features==2048,
          "one actual accepted B16 synthetic-native configuration");native_owned<=1;
      end
      if(native_owned && !in_valid && !final_seen)begin
        in_valid<=1;in_tag<=32'h1000;in_token<=4'(ntoken);in_start<=16'(ngroup*160);in_count<=ngroup==12 ? 128:160;
        in_last<=ngroup==12 && ntoken==15;in_data<=0;
      end
      if(in_valid && in_ready)begin
        in_valid<=0;packets<=packets+1;
        if(ngroup==12 && ntoken==15)begin final_seen<=1;final_cycle<=cycle;end
        if(ntoken==15)begin ntoken<=0;ngroup<=ngroup+1;end else ntoken<=ntoken+1;
      end
      if(native_done_fire)begin
        require(packets==208 && scratch_total==2040 && native_input_drained===1'b0,"Done+3 follows208 actual packets with last8 scratchACK pending");
        native_terminals<=native_terminals+1;terminal_seen<=1;
        $display("REAL_C_NATIVE_DONE cycle=%0d final_cycle=%0d packets=%0d scratch_ACK=%0d input_drained=%b",cycle,final_cycle,packets,scratch_total,native_input_drained);
      end
      if(case_id==2 && c_cfg_valid && !proxy_cfg_held && !proxy_cfg_done && proxy_owner_held && proxy_delay_edges<3)begin
        require(src_idle===1'b1 && quiet_C() && src_accepted==N && src_completed==N && c_cfg_ready===1'b0,
          "three delayed capture edges retain real idle1/N/N and no client ACK");
        proxy_delay_edges<=proxy_delay_edges+1;
        $display("REAL_C_CFG_CAPTURE_DELAY cycle=%0d delayed_edges=%0d idle=%b accepted=%0d completed=%0d",cycle,proxy_delay_edges+1,src_idle,src_accepted,src_completed);
      end
      if(c_cfg_valid && !proxy_cfg_held && !proxy_cfg_done && proxy_owner_held && parent_fault===1'b0 &&
        (case_id==1 || proxy_delay_edges==3) && src_idle===1'b1 && quiet_C() && src_cfg_ready===1'b1 && src_accepted==N && src_completed==N)begin
        require(target_metadata_valid && raw_total==128 && meta_total==1 && native_input_drained===1'b1 && epoch_fault===1'b0,"fresh cfg capture only after actual healthy publication");
        proxy_cfg_held<=1;proxy_frame<=held_frame;proxy_captures<=proxy_captures+1;
        $display("REAL_C_OWN_OFFER_CAPTURE cycle=%0d idle=%b accepted=%0d completed=%0d metadata_ACK=%0d",cycle,src_idle,src_accepted,src_completed,meta_total);
      end
      if(physical_target_cfg_fire)begin
        require(proxy_delay_edges==(case_id==2 ? 3:0),"exact immediate/delay3 capture schedule");
        require(proxy_cfg_held && c_cfg_valid && c_cfg_ready===1'b1,"client ACK equals real forwarded cfg handshake");
        proxy_cfg_held<=0;proxy_cfg_done<=1;physical_target_cfgs<=physical_target_cfgs+1;
      end
      if(c_cfg_valid && c_cfg_ready)client_cfg_ACKs<=client_cfg_ACKs+1;
      if(!warm_active && src_row_valid && src_row_ready)target_demands<=target_demands+1;
      if(!warm_active && src_retire_valid && src_retire_ready)target_retires<=target_retires+1;
    end
  end

  // Every actual warmup strip and completed counter transition is checked.
  always_ff @(posedge clk or negedge rst_n)begin : warm_observer
    if(!rst_n)begin warm_strips<=0;warm_completed_seen<=0;warm_retires<=0;warm_cfgs<=0;first_target_strips<=0;end
    else begin
      require(src_fault===1'b0,"actual C must stay healthy throughout baseline negative");
      if(warm_active && physical_cfg_fire)begin require(warm_cfgs==0 && src_input_rows==264 && src_new_image===1'b0,"one legal264 source configuration");warm_cfgs<=warm_cfgs+1;end
      if(warm_active && src_out_valid && src_out_ready)begin
        require(!$isunknown({src_out_tag,src_out_index,src_out_count,src_out_last,src_out_error,src_out_activation,
          src_out_exponent,src_out_mask,src_out_negative,src_out_normalized_negative}) &&
          src_out_tag==32'h1000+32'(warm_strips/256) && src_out_index==10'(warm_strips%256) && src_out_count==8 &&
          src_out_last==(warm_strips%256==255) && src_out_error===1'b0 && src_out_activation===64'd0 &&
          src_out_exponent===9'sd0 && src_out_mask===8'd0 && src_out_negative===8'd0 && src_out_normalized_negative===8'd0,
          "actual warmup strip identity/known zero output");warm_strips<=warm_strips+1;
      end
      if(warm_active && src_completed!=warm_completed_seen)begin
        require(src_completed==warm_completed_seen+1 && src_accepted==src_completed && warm_strips==int'(src_completed)*256,"actual completion only after256 accepted strips per dense row");
        $display("REAL_C_WARM_ROW cycle=%0d rank=%0d root=%0d accepted=%0d completed=%0d strips=%0d",cycle,warm_completed_seen,2*warm_completed_seen+1,src_accepted,src_completed,warm_strips);
        warm_completed_seen<=int'(src_completed);
      end
      if(!warm_active && src_out_valid && src_out_ready)begin
        require(target_cfg_post_seen===1'b1 && target_demands==1 && first_target_strips<256 &&
          !$isunknown({src_out_tag,src_out_index,src_out_count,src_out_last,src_out_error,src_out_activation,
            src_out_exponent,src_out_mask,src_out_negative,src_out_normalized_negative}) &&
          src_out_tag==32'h2000 && src_out_index==10'(first_target_strips) && src_out_count==8 &&
          src_out_last==(first_target_strips==255) && src_out_error===1'b0 && src_out_activation===64'd0 &&
          src_out_exponent===9'sd0 && src_out_mask===8'd0 && src_out_negative===8'd0 && src_out_normalized_negative===8'd0,
          "first actual ACK-backed target C row has256 known ordered zero strips");
        first_target_strips<=first_target_strips+1;
      end
      if(warm_active && src_retire_valid && src_retire_ready)begin
        require(src_accepted==264 && src_completed==264 && warm_strips==67584 && quiet_C(),"real retire forbidden before complete264 row counts/quiet");warm_retires<=warm_retires+1;
      end
    end
  end

  // Correct observation of the ORIGINAL real source: cfg-valid makes idle0
  // before this ACK. No old idle1 assertion may preempt the actual DUT fault.
  always @(posedge clk or negedge rst_n)begin : configuration_observer
    if(!rst_n)begin target_cfg_post_seen=0;cfg_edge=-1;fault_edge=-1;first_row_done_edge=-1;previous_cfg_valid=0;previous_cfg_ready=0;previous_cfg_frame='0;end
    else begin
      if(previous_cfg_valid && previous_cfg_ready!==1'b1)require(c_cfg_valid===1'b1 && held_frame===previous_cfg_frame,"consumer exposed cfg tuple retained until physical ACK");
      previous_cfg_valid=c_cfg_valid;previous_cfg_ready=c_cfg_ready;previous_cfg_frame=held_frame;
      if(physical_target_cfg_fire)begin
        require(src_idle===1'b0 && quiet_C() && src_accepted==264 && src_completed==264 &&
          proxy_owner_held===1'b1 && raw_total==128 && meta_total==1 && physical_target_cfgs==0,
          "physical cfg ACK real idle0/prior264/264/quiet/publication");
        require(src_cfg_tag==32'h2000 && src_cfg_layer==1 && src_cfg_epoch==2 && src_input_rows==264 &&
          src_image_start==5 && src_raw_base==TARGET && src_raw_bytes==FRAME_BYTES && src_meta_base==TMETA && src_meta_bytes==4224 &&
          src_gamma_base==GAMMA+12288 && src_gamma_bytes==6144 && src_gamma_exponent==-23,"whole forwarded target config tuple");
        cfg_edge=cycle;
        $display("REAL_C_PHYSICAL_CFG_ACK cycle=%0d idle=%b old_accepted=%0d old_completed=%0d producer=%b port=%b metadata_ACK=%0d rows=%0d",cycle,src_idle,src_accepted,src_completed,src_producer_idle,src_port_idle,meta_total,src_input_rows);
        #1ps;
        require(src_idle===1'b0 && src_accepted===10'd0 && src_completed===10'd0 && quiet_C(),"only same real cfg ACK resets actual source counters to0/0");
        target_cfg_post_seen=1;
        $display("REAL_C_PHYSICAL_CFG_POST cycle=%0d idle=%b accepted=%0d completed=%0d Cfault=%b consumer_fault=%b",cycle,src_idle,src_accepted,src_completed,src_fault,epoch_fault);
      end
      #1ps;
      require(epoch_fault===1'b0 && abort_registered===1'b0,"corrected consumer never poisons on legitimate own cfg/row");
      if(target_cfg_post_seen && target_demands==0)require(c_read_requests==270600,"no actual C source read before first target demand");
      require(target_retires==0 && c_retire_valid===1'b0 && proxy_owner_held==warm_finished,"no partial1of264 retire/release");
      if(row_done_valid===1'b1)begin
        require(row_done_error===1'b0 && row_done_ready===1'b0 && row_done_rank===10'd0 && row_done_tag===32'h2000 &&
          completed_rows===10'd1 && src_accepted===10'd1 && src_completed===10'd1 && src_idle===1'b0 && quiet_C() &&
          first_target_strips==256 && target_demands==1 && physical_target_cfgs==1 && client_cfg_ACKs==1 &&
          frame_done_valid===1'b0 && batch_done_valid===1'b0,"held real first rowDone with actual1/264 source completion");
        if(first_row_done_edge<0)begin
          first_row_done_edge=cycle;
          $display("REAL_C_FIRST_TARGET_ROW_DONE cycle=%0d rank=%0d accepted=%0d completed=%0d strips=%0d",cycle,row_done_rank,src_accepted,src_completed,first_target_strips);
        end
        if(cycle-first_row_done_edge==8)begin
          require(warm_cfgs==1 && warm_retires==1 && warm_strips==67584 && warm_completed_seen==264 && proxy_captures==1 &&
            packets==208 && native_terminals==1 && scratch_total==2048 && raw_total==128 && meta_total==1 &&
            write_requests==2177 && write_ACKs==2177 && write_beats==17410 && ff_table_words==128 && ff_meta_words==32 &&
            ff_read_requests==2336 && ff_read_beats==18592 && c_read_requests==271625 && c_read_beats==950290 &&
            !c_mem_busy && !c_mem_offer && !ff_busy && !ff_offer && !wr_owned && !ack_offer,"first real target row and complete physical/source/ACK census");
          $display("REAL_C_IDLE_CORRECTED_GREEN_PASS case=%0d cycle=%0d delay=%0d warm_rows=264 warm_strips=%0d physical_cfg=%0d target_rows=1 target_count=264 target_strips=%0d held_rowDone_cycles=8 target_retire=%0d scope=REAL_C_SYNTHETIC_NATIVE_ROUTING_PROXY",case_id,cycle,proxy_delay_edges,warm_strips,physical_target_cfgs,first_target_strips,target_retires);
          $finish;
        end
      end else if(first_row_done_edge>=0)require(0,"held rowDone cannot retract while ready0");
    end
  end

  initial begin clk=0;forever #5ns clk=~clk;end
  initial begin : run_first_corrected_green
    rst_n=0;case_id=-1;warm_active=1;warm_cfg_valid=0;warm_row_valid=0;warm_retire_valid=0;warm_finished=0;warm_rank=0;
    if(!$value$plusargs("case=%d",case_id) || (case_id!=1 && case_id!=2))$fatal(1,"REAL_C_IDLE_ONLY_CORRECTED_CASES1_2_IMPLEMENTED");
    #40ns;@(negedge clk);#1ps;rst_n=1;
    @(negedge clk);#1ps;warm_cfg_valid=1;
    do @(posedge clk);while(src_cfg_ready!==1'b1);
    @(negedge clk);#1ps;warm_cfg_valid=0;
    for(integer r=0;r<N;r++)begin
      while(src_row_ready!==1'b1)@(negedge clk);
      #1ps;warm_rank=10'(r);warm_row_valid=1;
      do @(posedge clk);while(src_row_ready!==1'b1);
      @(negedge clk);#1ps;warm_row_valid=0;
      while(src_completed!==10'(r+1) || src_producer_idle!==1'b1 || src_port_idle!==1'b1 || src_out_valid!==1'b0 || src_req_valid!==1'b0 || src_rsp_valid!==1'b0)@(negedge clk);
    end
    @(negedge clk);#1ps;
    require(src_accepted===10'd264 && src_completed===10'd264 && warm_strips==67584 && quiet_C(),"all actual264 rows before retire request");
    warm_retire_valid=1;
    do @(posedge clk);while(src_retire_ready!==1'b1);
    @(negedge clk);#1ps;warm_retire_valid=0;
    #1ps;
    require(src_idle===1'b1 && src_accepted===10'd264 && src_completed===10'd264 && quiet_C(),"same actual source retains264/264 after real retire");
    require(c_metadata_requests==264 && c_metadata_beats==528 && c_raw_requests==135168 && c_raw_beats==540672 &&
      c_gamma_requests==135168 && c_gamma_beats==405504,"complete actual two-pass raw/gamma/metadata source geometry");
    $display("REAL_C_WARM_RETIRED cycle=%0d accepted=%0d completed=%0d idle=%b strips=%0d source_requests=%0d source_beats=%0d",cycle,src_accepted,src_completed,src_idle,warm_strips,c_read_requests,c_read_beats);
    warm_active=0;warm_finished=1;
    // The bounded observers own completion; an unexplained end cannot pass.
  end
  initial begin #200000000ns;$fatal(1,"REAL_C_IDLE_BASELINE_WALL_IN_SIMULATION_DEADLINE");end
endmodule
`default_nettype wire
