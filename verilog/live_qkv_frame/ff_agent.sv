`timescale 1ns/1ps
`define LEARNED_READ_BYTES(array,file_path,start,count) \
  begin \
    int handle,amount; \
    handle=$fopen(file_path,"rb");if(handle==0)$fatal(1,"LEARNED_FILE_OPEN %s",file_path); \
    amount=$fread(array,handle,start,count); \
    if(amount!=count || $fgetc(handle)!=-1)$fatal(1,"LEARNED_FILE_SIZE %s",file_path); \
    $fclose(handle); \
  end

// Complete feedforward reference through one native compute fabric. Literal
// controls check both tails and errors; trained mode uses all original rows.
module tri_oracle_connected_ff_agent (
  input logic clk,rst_n,start_ff,
  input logic external_frame_available,
  input logic external_stats_valid,external_stats_last,external_replay_valid,external_replay_last,
  input logic[127:0] external_stats_data,external_replay_data,
  input logic[8:0] external_strip,
  output logic external_stats_ready,external_replay_ready,external_cfg_accepted,
  output logic[3:0] external_consumer_token,
  output logic client_r_req_valid,
  input logic client_r_req_ready,
  output logic[63:0] client_r_req_address,
  output logic[4:0] client_r_req_length,
  input logic client_r_rsp_valid,client_r_rsp_last,client_r_rsp_error,
  output logic client_r_rsp_ready,
  input logic[63:0] client_r_rsp_data,
  input logic server_r_req_valid,
  output logic server_r_req_ready,
  input logic[63:0] server_r_req_address,
  input logic[4:0] server_r_req_length,
  output logic server_r_rsp_valid,server_r_rsp_last,server_r_rsp_error,
  input logic server_r_rsp_ready,
  output logic[63:0] server_r_rsp_data,
  output logic client_w_req_valid,
  input logic client_w_req_ready,
  output logic[63:0] client_w_address,
  output logic[4:0] client_w_length,
  output logic client_w_data_valid,client_w_data_last,
  input logic client_w_data_ready,
  output logic[63:0] client_w_data,
  output logic[7:0] client_w_strobe,
  input logic client_w_rsp_valid,client_w_rsp_error,
  output logic client_w_rsp_ready,
  input logic server_w_req_valid,
  output logic server_w_req_ready,
  input logic[63:0] server_w_address,
  input logic[4:0] server_w_length,
  input logic server_w_data_valid,server_w_data_last,
  output logic server_w_data_ready,
  input logic[63:0] server_w_data,
  input logic[7:0] server_w_strobe,
  output logic server_w_rsp_valid,server_w_rsp_error,
  input logic server_w_rsp_ready,
  output logic fixture_loaded=0,ff_done=0,
  input logic ff_result_ready,
  output logic ff_down_valid,ff_result_last,ff_sink_ready,
  output logic [31:0] ff_result_tag,
  output logic [3:0] ff_result_token,
  output logic [15:0] ff_result_start,
  output logic [7:0] ff_result_count,
  output logic [5119:0] ff_result_data,
  input logic metadata_block,
  output logic metadata_idle,metadata_rebuilt,
  output logic [1:0] metadata_ce_n,metadata_we_n,
  output logic [17:0] shared_metadata_address,
  output logic [127:0] metadata_write_data,
  input logic [127:0] metadata_read_data,
  input logic raw_cfg_valid,
  output logic raw_cfg_ready,
  input logic [31:0] raw_cfg_tag,raw_cfg_activation_stride,
  input logic [4:0] raw_cfg_tokens,
  input logic [9:0] raw_cfg_feature_words,
  input logic [16:0] raw_cfg_dense_rows,
  input logic [7:0] raw_cfg_count,
  input logic [2559:0] raw_cfg_channels,raw_cfg_keep,
  input logic [63:0] raw_cfg_activation_base,raw_cfg_weight_base,
  output logic raw_out_valid,
  input logic raw_out_ready,
  output logic [31:0] raw_out_tag,
  output logic [3:0] raw_out_token,
  output logic raw_out_last,
  output logic [7:0] raw_out_count,
  output logic [2559:0] raw_out_channels,
  output logic [5119:0] raw_out_data,
  output logic raw_done_valid,
  input logic raw_done_ready,
  output logic raw_done_error,
  output logic [31:0] raw_done_tag,
  output logic raw_req_valid,
  input logic raw_req_ready,
  output logic [63:0] raw_req_address,
  output logic [4:0] raw_req_length,
  input logic raw_rsp_valid,
  output logic raw_rsp_ready,
  input logic raw_rsp_last,raw_rsp_error,
  input logic [63:0] raw_rsp_data,
  output tri_oracle_fabric_owner_types::request_t backend_request,
  input tri_oracle_fabric_owner_types::response_t backend_response,
  output logic [533:0] strip_request,
  input logic [111:0] strip_response
);
  parameter bit CORRUPT_NATIVE_RESIDUAL=0;

  parameter int FAULT=0,HIDDEN=2048,INTERMEDIATE=5632,OUTPUTS=2048,TOKENS=2;
  parameter bit TRAINED=1,ROW_UNITS=1,CORRECTION=1,FAST=0;
  parameter int WEIGHT_GAIN=1;
  parameter bit CORRUPT_UP_SIGNS=0,DUPLICATE_RAW_COORDINATE=0,DUPLICATE_GATED_COORDINATE=0;
  parameter bit PREFIX_ONLY=0;
  bit raw_seen[TOKENS*INTERMEDIATE],gated_seen[TOKENS*INTERMEDIATE];
  int exact_margin_values=0;
  localparam int PLANES=CORRECTION ? 2 : 1;
  localparam int GATE_GROUPS=(INTERMEDIATE+79)/80,OUTPUT_GROUPS=(OUTPUTS+159)/160;
  localparam logic [63:0] ACT_BASE=64'h00000001ffffffc0;
  localparam logic [63:0] GATE_BASE=64'h00000003fffff000;
  localparam logic [63:0] UP_BASE=64'h00000005fffff000;
  localparam logic [63:0] DOWN_BASE=64'h00000007fffff000;
  localparam logic [63:0] SCRATCH_BASE=64'h00000009ffffff80;
  logic cfg_valid=0,done_ready=0;
  wire cfg_ready,done_valid,done_error;
  logic [31:0] cfg_tag=0;
  logic [4:0] cfg_tokens=0;
  logic [15:0] cfg_input_features=0,cfg_intermediate_features=0;
  logic [16:0] cfg_output_features=0;
  logic [63:0] cfg_activation_base=0,cfg_gate_base=0,cfg_up_base=0,cfg_down_base=0,cfg_intermediate_base=0;
  logic [31:0] cfg_activation_stride=0;
  logic [95:0] cfg_gate_shifts=0,cfg_up_shifts=0,cfg_down_shifts=0;
  localparam logic [63:0] ROW_UNITS_BASE=64'h00000011fffff000;
  logic cfg_row_enable=0,cfg_correction_enable=0;
  logic [63:0] cfg_row_units_base=0;
  bit metadata_committed[GATE_GROUPS];
  bit read_error_seen=0;
  int metadata_requests=0,transfer_epoch=0;

  localparam logic [63:0] GATE_SIGN_BASE=64'h0000000bffffff00;
  localparam logic [63:0] UP_SIGN_BASE=64'h0000000dffffff00;
  logic [63:0] cfg_gate_sign_base=0,cfg_up_sign_base=0;
  logic [31:0] cfg_epsilon_q16=0;
  logic stats_valid,stats_last,replay_valid,replay_last;
  wire stats_ready,replay_ready;
  wire [3:0] residual_token;
  logic [127:0] stats_data,replay_data,replay_gamma;
  logic [95:0] cfg_activation_shifts=0;
  localparam int ACT_STRIDE=HIDDEN+64;
  localparam int ACT_SPAN=(TOKENS-1)*ACT_STRIDE+HIDDEN;
  byte unsigned activation_memory[TOKENS*HIDDEN];
  bit activation_committed[TOKENS*HIDDEN];
  int activation_golden[TOKENS][HIDDEN];
  int activation_bytes=0,activation_acks=0,activation_requests=0,normalizer_starts=0;
  bit write_is_activation=0;
  int sign_requests=0,contended_cycles=0,valid_masks=0,abort_masks=0;
  bit verify_held_second=0,held_second_retired=0;
  logic [1279:0] held_second;
  localparam int SIGN_BYTES=INTERMEDIATE*HIDDEN/8;
  wire out_valid,out_last;
  wire [31:0] out_tag,done_tag;
  wire [3:0] out_token;
  wire [15:0] out_start;
  wire [7:0] out_count;
  wire [5119:0] out_data;
  int cycle=0,seen=0,stalls=0,first_hold=0;
  bit hold_done=0,inject_fault=FAULT!=0,fault_seen=0;
  wire out_ready=ff_result_ready;
  always_comb begin
    ff_down_valid=out_valid;ff_result_last=out_last;ff_result_tag=out_tag;
    ff_result_token=out_token;ff_result_start=out_start;ff_result_count=out_count;
    ff_result_data=out_data;
    ff_sink_ready=hold_done && (FAST || cycle%11>=5);
  end
  wire req_valid,rsp_ready;
  wire [63:0] req_address;
  wire [4:0] req_length;
  bit read_active=0,read_bubble=0;
  logic [63:0] read_address=0;
  int read_beat=0,read_length=0,read_requests=0,read_beats=0;
  wire req_ready=start_ff ? client_r_req_ready:raw_req_ready;
  wire rsp_valid=start_ff ? client_r_rsp_valid:raw_rsp_valid;
  wire rsp_last=start_ff ? client_r_rsp_last:raw_rsp_last;
  wire rsp_error=start_ff ? client_r_rsp_error:raw_rsp_error;
  wire[63:0] rsp_data=start_ff ? client_r_rsp_data:raw_rsp_data;
  wire memory_req_ready=!read_active && (FAST || cycle%7>=3);
  wire memory_rsp_valid=read_active && !read_bubble;
  wire memory_rsp_last=read_beat+1==read_length;
  wire memory_rsp_error=(inject_fault && !fault_seen &&
     ((FAULT==2 && read_address>=DOWN_BASE && read_address<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE)) ||
      (FAULT==3 && read_address>=DOWN_BASE+64'(160*INTERMEDIATE) && read_address<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE)) ||
      sign_fault_address(read_address) || (FAULT==17 && metadata_address(read_address) && read_beat==3)));
  logic[63:0] memory_rsp_data;
  wire wr_req_valid,wr_data_valid,wr_data_last,wr_rsp_ready;
  wire [63:0] wr_address,wr_data;
  wire [4:0] wr_length;
  wire [7:0] wr_strobe;
  bit write_active=0,write_response=0;
  logic [63:0] write_address=0;
  int write_beat=0,write_length=0,response_delay=0,write_requests=0,write_bytes=0;
  wire wr_req_ready=client_w_req_ready;
  wire wr_data_ready=client_w_data_ready;
  wire wr_rsp_valid=client_w_rsp_valid;
  wire wr_rsp_error=client_w_rsp_error;
  wire memory_wr_req_ready=!write_active && !write_response && response_delay==0 && (FAST || cycle%5>=2);
  wire memory_wr_data_ready=write_active && (FAST || cycle%7!=0);
  wire memory_wr_rsp_valid=write_response &&
    (write_is_activation || !(inject_fault && FAULT==11) || fault_seen);
  wire memory_wr_rsp_error=inject_fault && !fault_seen &&
    ((!write_is_activation && FAULT==1) ||
     (write_is_activation && ((FAULT==12 && activation_requests==1) ||
                               (FAULT==13 && activation_bytes==TOKENS*HIDDEN))));
  byte unsigned scratch[PLANES*TOKENS*INTERMEDIATE];
  bit committed[PLANES*TOKENS*INTERMEDIATE];
  int writes[PLANES*TOKENS*INTERMEDIATE],scratch_reads[PLANES*TOKENS*INTERMEDIATE/8];
  int golden_down[TOKENS][INTERMEDIATE],golden_correction[TOKENS][INTERMEDIATE],golden[TOKENS][OUTPUTS];
  byte unsigned fixture_activation[TOKENS*HIDDEN],fixture_gate[INTERMEDIATE*HIDDEN],fixture_up[INTERMEDIATE*HIDDEN];
  byte unsigned fixture_down[OUTPUTS*INTERMEDIATE],fixture_keep[TOKENS*INTERMEDIATE],fixture_shifts[TOKENS*3];
  byte unsigned fixture_intermediate[PLANES*TOKENS*INTERMEDIATE];
  logic [31:0] fixture_output[TOKENS*OUTPUTS];
  string fixture,learned_fixture,observations,gate_file,up_file,down_file,metadata_file,gate_sign_file,up_sign_file;
  localparam int SIGN_EXPECTED=10560;
  byte unsigned fixture_metadata[GATE_GROUPS*64];
  byte unsigned fixture_gate_signs[SIGN_BYTES],fixture_up_signs[SIGN_BYTES];
  logic [15:0] fixture_gamma[HIDDEN],fixture_norm[TOKENS*HIDDEN];
  logic [15:0] fixture_gate_margin[TOKENS*INTERMEDIATE],fixture_up_margin[TOKENS*INTERMEDIATE];
  logic [15:0] fixture_outlier_counts[TOKENS],fixture_gated[TOKENS*INTERMEDIATE];
  logic [31:0] fixture_epsilon[1],fixture_gate_raw[TOKENS*INTERMEDIATE],fixture_up_raw[TOKENS*INTERMEDIATE];
  logic [5:0] fixture_affine[TOKENS];
  logic [63:0] fixture_sign_requests[SIGN_EXPECTED];
  int norm_values=0,prediction_packets=0,raw_dot_values=0,gated_values=0;
  int native_stats_reads=0,native_replay_reads=0;

  bit held_read_req=0,held_write_req=0,held_write_data=0,held_output=0;
  logic [68:0] prior_read_req,prior_write_req;
  logic [72:0] prior_write_data;
  logic [5280:0] prior_output;

  always_comb begin
    stats_valid=external_stats_valid;stats_last=external_stats_last;stats_data=external_stats_data;
    replay_valid=external_replay_valid;replay_last=external_replay_last;replay_data=external_replay_data;
    for(int lane=0;lane<8;lane++)replay_gamma[lane*16+:16]=16'(gamma_value(int'(external_strip)*8+lane));
    external_stats_ready=stats_ready;external_replay_ready=replay_ready;external_consumer_token=residual_token;
    external_cfg_accepted=cfg_valid && cfg_ready;
    client_r_req_valid=start_ff && req_valid;client_r_req_address=req_address;client_r_req_length=req_length;
    client_r_rsp_ready=start_ff && rsp_ready;
    server_r_req_ready=memory_req_ready;server_r_rsp_valid=memory_rsp_valid;
    server_r_rsp_last=memory_rsp_last;server_r_rsp_error=memory_rsp_error;server_r_rsp_data=memory_rsp_data;
    client_w_req_valid=start_ff && wr_req_valid;client_w_address=wr_address;client_w_length=wr_length;
    client_w_data_valid=start_ff && wr_data_valid;client_w_data_last=wr_data_last;
    client_w_data=wr_data;client_w_strobe=wr_strobe;client_w_rsp_ready=start_ff && wr_rsp_ready;
    server_w_req_ready=memory_wr_req_ready;server_w_data_ready=memory_wr_data_ready;
    server_w_rsp_valid=memory_wr_rsp_valid;server_w_rsp_error=memory_wr_rsp_error;
  end

  parameter bit CORE_STRIP=1;
  tri_oracle_attention_tensor437 attention();
  wire ff_cfg_ready=cfg_ready;
  wire ff_write_request=wr_req_valid,ff_write_data=wr_data_valid;
  wire ff_result_valid=out_valid,ff_terminal_valid=done_valid;
  always_comb begin
    attention.cfg_valid=raw_cfg_valid && !start_ff;
    attention.cfg_tag=raw_cfg_tag;attention.cfg_activation_stride=raw_cfg_activation_stride;
    attention.cfg_tokens=raw_cfg_tokens;attention.cfg_feature_words=raw_cfg_feature_words;
    attention.cfg_dense_rows=raw_cfg_dense_rows;attention.cfg_count=raw_cfg_count;
    attention.cfg_channels=raw_cfg_channels;attention.cfg_keep=raw_cfg_keep;
    attention.cfg_activation_base=raw_cfg_activation_base;attention.cfg_weight_base=raw_cfg_weight_base;
    attention.out_ready=raw_out_ready;attention.done_ready=raw_done_ready;
    raw_cfg_ready=attention.cfg_ready && !start_ff;
    raw_out_valid=attention.out_valid;raw_out_tag=attention.out_tag;raw_out_token=attention.out_token;
    raw_out_last=attention.out_last;raw_out_count=attention.out_count;
    raw_out_channels=attention.out_channels;raw_out_data=attention.out_data;
    raw_done_valid=attention.done_valid;raw_done_error=attention.done_error;raw_done_tag=attention.done_tag;
    raw_req_valid=req_valid && !start_ff;raw_req_address=req_address;raw_req_length=req_length;
    raw_rsp_ready=rsp_ready && !start_ff;
  end
  tri_oracle_external_metadata_row_learned #(.CORE_STRIP_PREDICTOR(CORE_STRIP)) dut (
    .metadata_block,.metadata_idle,.metadata_rebuilt,.metadata_ce_n,.metadata_we_n,
    .metadata_address(shared_metadata_address),.metadata_write_data,.metadata_read_data,
    .attention,.strip_request,.strip_response,.softmax_request('0),
    .backend_request,.backend_response,.cfg_valid(cfg_valid || (!start_ff && metadata_block)),.*
  );
  function automatic int gate_offset(input int channel);return ROW_UNITS ? channel%8 : 0;endfunction
  function automatic int up_offset(input int channel);return ROW_UNITS ? (3*channel+1)%8 : 0;endfunction
  function automatic bit metadata_address(input logic [63:0] address);
    return address>=ROW_UNITS_BASE && address<ROW_UNITS_BASE+64'(GATE_GROUPS*64);
  endfunction
  function automatic logic [511:0] metadata_record(input int group);
    metadata_record=0;
    if(TRAINED)begin
      for(int b=0;b<64;b++)metadata_record[b*8+:8]=fixture_metadata[group*64+b];
    end else for(int channel=0;channel<80;channel++)if(group*80+channel<INTERMEDIATE)
      metadata_record[channel*6+:6]=6'(gate_offset(group*80+channel) | (up_offset(group*80+channel)<<3));
  endfunction

  function automatic int activation(input int token,feature);
    return activation_golden[token][feature];
  endfunction
  function automatic int gate_weight(input int channel,feature);
    if(TRAINED)return int'($signed(fixture_gate[channel*HIDDEN+feature]));
    return ((channel*3+feature*5)%23-11)*WEIGHT_GAIN;
  endfunction
  function automatic int up_weight(input int channel,feature);
    if(TRAINED)return int'($signed(fixture_up[channel*HIDDEN+feature]));
    return ((channel*5+feature*7)%29-14)*WEIGHT_GAIN;
  endfunction
  function automatic int down_weight(input int output_row,channel);
    if(TRAINED)return int'($signed(fixture_down[output_row*INTERMEDIATE+channel]));
    return (output_row*7+channel*11)%17-8;
  endfunction
  function automatic bit kept(input int token,channel);
    int gate_margin,up_margin,positive,negative;
    if(TRAINED)return fixture_keep[token*INTERMEDIATE+channel]!=0;
    // Two equal, opposite nonzero residuals have normalized magnitude
    // sqrt(HIDDEN/2), above three in this literal fixture.
    positive=token+1;
    negative=HIDDEN-token-1;
    gate_margin=2*(int'(gate_weight(channel,positive)>=0)+int'(gate_weight(channel,negative)<0))-2;
    up_margin=2*(int'(up_weight(channel,positive)>=0)+int'(up_weight(channel,negative)<0))-2;
    return !(gate_margin<=0 && up_margin==0);
  endfunction
  function automatic bit sign_address(input logic [63:0] address);
    return (address>=GATE_SIGN_BASE && address<GATE_SIGN_BASE+64'(SIGN_BYTES)) ||
           (address>=UP_SIGN_BASE && address<UP_SIGN_BASE+64'(SIGN_BYTES));
  endfunction
  function automatic bit sign_fault_address(input logic [63:0] address);
    return (FAULT==4 && sign_address(address)) ||
           ((FAULT==7 || FAULT==11) && address>=GATE_SIGN_BASE+64'((FAULT==7 ? 12 : 20)*HIDDEN) &&
            address<GATE_SIGN_BASE+64'(SIGN_BYTES));
  endfunction
  function automatic int residual_value(input int token,feature);
    if(feature==token+1)return 1200;
    if(feature==HIDDEN-token-1)return -1200;
    return (token*29+feature*11)%61-30;
  endfunction
  function automatic int gamma_value(input int feature);
    if(TRAINED)return int'($signed(fixture_gamma[feature]));
    return ((feature*13)%23-11)*97+1024;
  endfunction
  function automatic bit activation_address(input logic [63:0] address);
    return address>=ACT_BASE && address<ACT_BASE+64'(ACT_SPAN);
  endfunction
  function automatic int shift_gate(input int token);return TRAINED ? int'(fixture_shifts[token*3]) : token;endfunction
  function automatic int shift_up(input int token);return TRAINED ? int'(fixture_shifts[token*3+1]) : token==0 ? 2 : token==1 ? 3 : 1;endfunction
  function automatic int shift_down(input int token);return TRAINED ? int'(fixture_shifts[token*3+2]) : token==0 ? 2 : token==1 ? 0 : 4;endfunction
  function automatic int quant(input longint signed value,input int shift,bits);
    longint signed magnitude,rounded,limit;
    magnitude=value<0 ? -value : value;
    rounded=shift==0 ? magnitude : (magnitude+(64'sd1<<(shift-1)))>>shift;
    if(value<0)rounded=-rounded;
    limit=64'sd1<<(bits-1);
    return int'(rounded>=limit ? limit-1 : rounded< -limit ? -limit : rounded);
  endfunction
  function automatic int sample(input int index);
    real x,y;
    x=-8.0+real'(index)/16.0;y=256.0*x/(1.0+$exp(-x));
    return y>=0 ? $rtoi(y+0.5) : -$rtoi(-y+0.5);
  endfunction
  function automatic int silu(input int value);
    int position,index,remainder;
    if(value<=-2048)return 0;
    if(value>=2048)return value;
    position=value+2048;index=position/16;remainder=position%16;
    return quant(sample(index)*(16-remainder)+sample(index+1)*remainder,4,16);
  endfunction
  always_comb begin: read_word
    logic [63:0] current;
    int offset,token,row,feature;
    current=read_address+64'(read_beat*8);memory_rsp_data=0;
    if(metadata_address(current))begin
      offset=int'(current-ROW_UNITS_BASE);
      memory_rsp_data=64'(metadata_record(offset/64)>>((offset%64)*8));
      if(inject_fault && !fault_seen && FAULT==18 && read_beat==7)memory_rsp_data[63]=1;
    end else if(sign_address(current))begin
      if(TRAINED)begin
        offset=int'(current-(current>=UP_SIGN_BASE ? UP_SIGN_BASE : GATE_SIGN_BASE));
        for(int b=0;b<8;b++)memory_rsp_data[b*8+:8]=current>=UP_SIGN_BASE ? (CORRUPT_UP_SIGNS ? 8'b0 : fixture_up_signs[offset+b]) : fixture_gate_signs[offset+b];
      end else begin
      offset=int'(current-(current>=UP_SIGN_BASE ? UP_SIGN_BASE : GATE_SIGN_BASE))/8;
      row=(offset/(HIDDEN/2))*32;
      feature=2*(offset%(HIDDEN/2));
      for(int b=0;b<64;b++)
        memory_rsp_data[b]=current>=UP_SIGN_BASE ? up_weight(row+b%32,feature+b/32)<0 :
                                          gate_weight(row+b%32,feature+b/32)<0;
      end
    end else if(activation_address(current))begin
      offset=int'(current-ACT_BASE);token=offset/ACT_STRIDE;feature=offset%ACT_STRIDE;
      for(int b=0;b<8;b++)memory_rsp_data[b*8+:8]=activation_memory[token*HIDDEN+feature+b];
    end else if(current>=GATE_BASE && current<GATE_BASE+64'(INTERMEDIATE*HIDDEN))begin
      offset=int'(current-GATE_BASE);row=offset/HIDDEN;feature=offset%HIDDEN;
      for(int b=0;b<8;b++)memory_rsp_data[b*8+:8]=8'(gate_weight(row,feature+b));
    end else if(current>=UP_BASE && current<UP_BASE+64'(INTERMEDIATE*HIDDEN))begin
      offset=int'(current-UP_BASE);row=offset/HIDDEN;feature=offset%HIDDEN;
      for(int b=0;b<8;b++)memory_rsp_data[b*8+:8]=8'(up_weight(row,feature+b));
    end else if(current>=DOWN_BASE && current<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE))begin
      offset=int'(current-DOWN_BASE);row=offset/INTERMEDIATE;feature=offset%INTERMEDIATE;
      for(int b=0;b<8;b++)memory_rsp_data[b*8+:8]=8'(down_weight(row,feature+b));
    end else if(current>=SCRATCH_BASE && current<SCRATCH_BASE+64'(PLANES*TOKENS*INTERMEDIATE))begin
      offset=int'(current-SCRATCH_BASE);
      for(int b=0;b<8;b++)memory_rsp_data[b*8+:8]=scratch[offset+b];
    end
  end
  task automatic configure;
    @(negedge clk);cfg_tag=32'h39300001;cfg_tokens=TOKENS;cfg_input_features=HIDDEN;
    cfg_intermediate_features=INTERMEDIATE;cfg_output_features=OUTPUTS;
    cfg_activation_base=ACT_BASE;cfg_gate_base=GATE_BASE;cfg_up_base=UP_BASE;cfg_down_base=DOWN_BASE;
    cfg_intermediate_base=SCRATCH_BASE;cfg_activation_stride=ACT_STRIDE;
    cfg_row_enable=ROW_UNITS;cfg_correction_enable=CORRECTION;cfg_row_units_base=ROW_UNITS_BASE;
    metadata_requests=0;transfer_epoch++;foreach(metadata_committed[i])metadata_committed[i]=0;
    if(inject_fault && FAULT==19)cfg_row_units_base=ROW_UNITS_BASE+1;
    if(inject_fault && FAULT==20)cfg_row_units_base=ACT_BASE;
    if(inject_fault && FAULT==21)cfg_row_units_base=SCRATCH_BASE;
    if(inject_fault && FAULT==22)cfg_row_units_base=GATE_BASE;
    cfg_gate_sign_base=GATE_SIGN_BASE;cfg_up_sign_base=UP_SIGN_BASE;cfg_epsilon_q16=TRAINED ? fixture_epsilon[0] : 0;
    if(inject_fault && FAULT==8)cfg_intermediate_base=GATE_SIGN_BASE;
    if(inject_fault && FAULT==9)cfg_output_features=0;
    if(inject_fault && FAULT==10)cfg_activation_stride=HIDDEN+1;
    if(inject_fault && FAULT==14)cfg_activation_base=GATE_BASE;
    if(inject_fault && FAULT==15)cfg_activation_base=GATE_SIGN_BASE;
    for(int token=0;token<TOKENS;token++)cfg_activation_shifts[6*token+:6]=TRAINED ? fixture_affine[token] : 6'(14+token%2);
    if(inject_fault && FAULT==5)cfg_intermediate_base=ACT_BASE;
    if(inject_fault && FAULT==6)cfg_intermediate_base=64'hffffffffffffff80;
    for(int token=0;token<TOKENS;token++)begin
      cfg_gate_shifts[token*6+:6]=6'(shift_gate(token));cfg_up_shifts[token*6+:6]=6'(shift_up(token));
      cfg_down_shifts[token*6+:6]=6'(shift_down(token));
    end
    cfg_valid=1;@(posedge clk);if(!cfg_ready)$fatal(1,"BATCH406_CONFIG_NOT_ACCEPTED");
    @(negedge clk);cfg_valid=0;cfg_tag='1;cfg_tokens='1;cfg_input_features='1;cfg_intermediate_features='1;
    cfg_output_features='1;cfg_activation_base='1;cfg_gate_base='1;cfg_up_base='1;cfg_down_base='1;
    cfg_gate_sign_base='1;cfg_up_sign_base='1;cfg_epsilon_q16='1;cfg_activation_shifts='1;
    cfg_intermediate_base='1;cfg_activation_stride='1;cfg_gate_shifts='1;cfg_up_shifts='1;cfg_down_shifts='1;
    cfg_row_enable=~ROW_UNITS;cfg_correction_enable=~CORRECTION;cfg_row_units_base='1;
  endtask
  task automatic send_residuals;
    // Delivery is now driven only by the external-memory replay link.
    while(!done_valid && (native_stats_reads<TOKENS*(HIDDEN/8) || native_replay_reads<TOKENS*(HIDDEN/8)))
      @(negedge clk);
  endtask
  always @(posedge clk)if(rst_n && start_ff)begin: bus_and_scoreboard
    logic [63:0] current;
    int offset,row,token,expected_start,expected_token,expected_count;
    cycle<=cycle+1;
    if(stats_valid && stats_ready)begin
      $display("CONNECTED_RESIDUAL_STATS index=%0d token=%0d last=%0d data=%032h",native_stats_reads,residual_token,stats_last,stats_data);
      native_stats_reads++;
    end
    if(replay_valid && replay_ready)begin
      $display("CONNECTED_RESIDUAL_REPLAY index=%0d token=%0d last=%0d data=%032h",native_replay_reads,residual_token,replay_last,replay_data);
      native_replay_reads++;
    end
    if(dut.predictor.activation_path.norm_valid && dut.predictor.activation_path.norm_ready)begin
      int token,strip;
      token=norm_values/HIDDEN;strip=(norm_values%HIDDEN)/8;
      if(dut.predictor.activation_path.norm_tag!==32'h39300001 || dut.predictor.activation_path.norm_index!==10'(strip) ||
         dut.predictor.activation_path.norm_count!==4'd8 || dut.predictor.activation_path.norm_error ||
         dut.predictor.activation_path.norm_last!==(strip==HIDDEN/8-1))$fatal(1,"LEARNED_NORM_DESCRIPTOR");
      for(int lane=0;lane<8;lane++)begin
        int norm;
        norm=int'($signed(fixture_norm[token*HIDDEN+strip*8+lane]));
        if(dut.predictor.activation_path.norm_data[lane*16+:16]!==16'(norm) ||
           dut.predictor.activation_path.norm_outliers[lane]!==1'(norm>768 || norm< -768))$fatal(1,"LEARNED_NORM_VALUE");
      end
      norm_values+=8;
    end
    if(dut.prediction_valid && dut.prediction_ready)begin
      int group,token,channel,gm,um;
      group=prediction_packets/TOKENS;token=prediction_packets%TOKENS;
      if(dut.prediction_tag!==32'h39300001 || dut.prediction_group!==8'(group) || dut.prediction_token!==4'(token) ||
         dut.prediction_last!==(group==INTERMEDIATE/32-1 && token==TOKENS-1) ||
         dut.unused_outlier_count!==13'(fixture_outlier_counts[token]))$fatal(1,"LEARNED_PREDICTION_DESCRIPTOR");
      for(int c=0;c<32;c++)begin
        channel=group*32+c;gm=int'($signed(fixture_gate_margin[token*INTERMEDIATE+channel]));
        um=int'($signed(fixture_up_margin[token*INTERMEDIATE+channel]));
        if(dut.unused_gate_mask[c]!==1'(gm<=0) || dut.unused_up_mask[c]!==1'(um==0) ||
           dut.prediction_skip[c]!==1'(gm<=0 && um==0))$fatal(1,"LEARNED_PREDICTION_VALUE");
      end
      prediction_packets++;
    end
    if(dut.compute.compute.raw_valid && dut.compute.compute.raw_out_ready && dut.compute.compute.paired)begin
      int token,channel,gr,ur,prior_channel;
      logic [31:0] observed_gate,observed_up,prior_gate,prior_up;
      token=int'(dut.compute.compute.raw_token);prior_channel=0;prior_gate=0;prior_up=0;
      for(int c=0;c<int'(dut.compute.compute.raw_count);c++)begin
        channel=int'(dut.compute.compute.raw_channels[c*16+:16]);gr=(c/16)*32+c%16;ur=gr+16;
        observed_gate=dut.compute.compute.raw_data[gr*32+:32];observed_up=dut.compute.compute.raw_data[ur*32+:32];
        // Replay the preceding genuine observation in place of channel1.
        // Aggregate counts stay unchanged; a missing coordinate must fail.
        if(DUPLICATE_RAW_COORDINATE && token==0 && channel==1)begin
          channel=prior_channel;observed_gate=prior_gate;observed_up=prior_up;
        end
        if(token<0 || token>=TOKENS || channel<0 || channel>=INTERMEDIATE)$fatal(1,"LEARNED_RAW_COORDINATE_RANGE");
        if(raw_seen[token*INTERMEDIATE+channel])$fatal(1,"LEARNED_DUPLICATE_RAW_COORDINATE");
        raw_seen[token*INTERMEDIATE+channel]=1;
        if(observed_gate!==fixture_gate_raw[token*INTERMEDIATE+channel] ||
           observed_up!==fixture_up_raw[token*INTERMEDIATE+channel])$fatal(1,"LEARNED_RAW_DOT");
        prior_channel=channel;prior_gate=observed_gate;prior_up=observed_up;raw_dot_values+=2;
      end
    end
    if(dut.compute.compute_out_valid && dut.compute.compute_out_ready && dut.compute.compute.paired)begin
      int token,channel,prior_channel;
      logic [15:0] observed,prior;
      token=int'(dut.compute.compute_token);prior_channel=0;prior=0;
      for(int c=0;c<int'(dut.compute.compute_count);c++)begin
        channel=int'(dut.compute.compute_channels[c*16+:16]);observed=dut.compute.compute_data[c*32+:16];
        if(DUPLICATE_GATED_COORDINATE && token==0 && channel==1)begin channel=prior_channel;observed=prior;end
        if(token<0 || token>=TOKENS || channel<0 || channel>=INTERMEDIATE)$fatal(1,"LEARNED_GATED_COORDINATE_RANGE");
        if(gated_seen[token*INTERMEDIATE+channel])$fatal(1,"LEARNED_DUPLICATE_GATED_COORDINATE");
        gated_seen[token*INTERMEDIATE+channel]=1;
        if(observed!==fixture_gated[token*INTERMEDIATE+channel])$fatal(1,"LEARNED_GATED_VALUE");
        prior_channel=channel;prior=observed;gated_values++;
      end
    end
    if(dut.predictor.activation_path.cfg_valid && dut.predictor.activation_path.cfg_ready)normalizer_starts++;
    if(dut.compute_started && (dut.predict_wr_req_valid || dut.predict_wr_data_valid || dut.predict_wr_rsp_ready))
      $fatal(1,"BATCH406_WRITE_OWNER_CHANGED");
    if(!dut.compute_started && (dut.compute_wr_req_valid || dut.compute_wr_data_valid || dut.compute_wr_rsp_ready))
      $fatal(1,"BATCH406_COMPUTE_WROTE_BEFORE_ACTIVATION");
    if(dut.compute_req_valid && dut.predict_req_valid)contended_cycles++;
    if(verify_held_second)begin
      if(!dut.compute_mask_valid || dut.compute_mask_count!=80 || dut.packet_mask_start!=80 ||
         dut.packet_mask_bits!==held_second)$fatal(1,"BATCH406_HELD_SECOND_CHANGED");
      if(dut.compute_mask_ready)begin verify_held_second=0;held_second_retired=1;end
    end
    if(dut.compute_mask_valid && dut.compute_mask_ready)begin
      if(dut.compute_mask_count==0)abort_masks++;
      else begin
        if(dut.packet_mask_start!=16'(valid_masks*80))$fatal(1,"BATCH406_MASK_ORDER");
        for(int token=0;token<TOKENS;token++)
          for(int row=0;row<int'(dut.compute_mask_count);row++)
            if(dut.packet_mask_bits[token*80+row]!==kept(token,valid_masks*80+row))
              $fatal(1,"BATCH406_MASK_BIT token=%0d channel=%0d",token,valid_masks*80+row);
        valid_masks++;
      end
    end
    if(dut.compute_rsp_valid && dut.predict_rsp_valid)$fatal(1,"BATCH406_DUAL_RESPONSE");
    if(read_active && read_bubble)read_bubble<=0;
    if(server_r_req_valid && server_r_req_ready)begin
      if(read_active || server_r_req_length==0 || server_r_req_length>16 || server_r_req_address[2:0]!=0)$fatal(1,"BATCH406_READ_REQUEST");
      if(activation_acks!=TOKENS*HIDDEN)$fatal(1,"BATCH406_READ_BEFORE_ACTIVATION_ACK");
      if((server_r_req_address>=GATE_BASE && server_r_req_address<GATE_BASE+64'(INTERMEDIATE*HIDDEN)) ||
         (server_r_req_address>=UP_BASE && server_r_req_address<UP_BASE+64'(INTERMEDIATE*HIDDEN)))begin
        int group;
        group=int'(server_r_req_address-(server_r_req_address>=UP_BASE ? UP_BASE : GATE_BASE))/HIDDEN/80;
        if(ROW_UNITS && !metadata_committed[group])$fatal(1,"BATCH_ROW_READ_BEFORE_METADATA group=%0d",group);
      end
      if(metadata_address(server_r_req_address))begin
        offset=int'(server_r_req_address-ROW_UNITS_BASE);
        if(!ROW_UNITS || server_r_req_length!=8 || offset%64!=0 || metadata_committed[offset/64])
          $fatal(1,"BATCH_ROW_METADATA_REQUEST");
        metadata_requests++;
      end else if(activation_address(server_r_req_address))begin
        offset=int'(server_r_req_address-ACT_BASE);token=offset/ACT_STRIDE;row=offset%ACT_STRIDE;
        if(row+int'(server_r_req_length)*8>HIDDEN)$fatal(1,"BATCH406_ACTIVATION_PADDING_READ");
        for(int b=0;b<int'(server_r_req_length)*8;b++)
          if(!activation_committed[token*HIDDEN+row+b])$fatal(1,"BATCH406_UNCOMMITTED_ACTIVATION_READ");
      end else if(server_r_req_address>=SCRATCH_BASE && server_r_req_address<SCRATCH_BASE+64'(PLANES*TOKENS*INTERMEDIATE))begin
        offset=int'(server_r_req_address-SCRATCH_BASE);
        for(int b=0;b<int'(server_r_req_length)*8;b++)if(!committed[offset+b])$fatal(1,"BATCH406_READ_BEFORE_WRITE_ACK");
      end else if(sign_address(server_r_req_address))begin
        if(server_r_req_length!=1)$fatal(1,"BATCH406_SIGN_BURST");
        if(TRAINED && (sign_requests>=SIGN_EXPECTED || server_r_req_address!==fixture_sign_requests[sign_requests]))
          $fatal(1,"LEARNED_SIGN_TRAFFIC index=%0d address=%h",sign_requests,server_r_req_address);
        sign_requests++;
      end else if(!(
           (server_r_req_address>=GATE_BASE && server_r_req_address<GATE_BASE+64'(INTERMEDIATE*HIDDEN)) ||
           (server_r_req_address>=UP_BASE && server_r_req_address<UP_BASE+64'(INTERMEDIATE*HIDDEN)) ||
           (server_r_req_address>=DOWN_BASE && server_r_req_address<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE))))$fatal(1,"BATCH406_UNKNOWN_READ_ADDRESS %h",server_r_req_address);
      read_active<=1;read_address<=server_r_req_address;read_beat<=0;read_bubble<=0;read_requests++;read_error_seen<=0;
      if(inject_fault && !fault_seen && sign_fault_address(server_r_req_address))begin
        read_length<=2;
        if(FAULT==11)begin
          if(!dut.compute_mask_valid || dut.compute_mask_ready || dut.packet_mask_start!=80)
            $fatal(1,"BATCH406_NO_HELD_SECOND_AT_FAULT");
          verify_held_second=1;
          held_second=dut.packet_mask_bits;
        end
      end
      else read_length<=int'(server_r_req_length);
    end
    if(server_r_rsp_valid && server_r_rsp_ready)begin
      current=read_address+64'(read_beat*8);read_beats++;
      if(metadata_address(read_address))$display("ROW_METADATA_TRACE epoch=%0d record=%0d word=%0d data=%016h",transfer_epoch,int'(read_address-ROW_UNITS_BASE)/64,read_beat,server_r_rsp_data);$fflush();
      if(current>=SCRATCH_BASE && current<SCRATCH_BASE+64'(PLANES*TOKENS*INTERMEDIATE))scratch_reads[int'(current-SCRATCH_BASE)/8]++;
      if(server_r_rsp_error)begin fault_seen<=1;read_error_seen<=1;end
      if(metadata_address(read_address) && server_r_rsp_last)begin
        if(inject_fault && !fault_seen && FAULT==18)fault_seen<=1;
        if(!read_error_seen && !server_r_rsp_error && !(inject_fault && FAULT==18))
          metadata_committed[int'(read_address-ROW_UNITS_BASE)/64]=1;
      end
      if(server_r_rsp_last)read_active<=0;else begin read_beat<=read_beat+1;read_bubble<=!FAST && cycle%5==0;end
    end
    if(server_w_req_valid && server_w_req_ready)begin
      if(write_active || write_response || server_w_length==0 || server_w_address[2:0]!=0)
        $fatal(1,"BATCH406_WRITE_REQUEST");
      write_is_activation<=activation_address(server_w_address);
      if(activation_address(server_w_address))begin
        token=activation_bytes/HIDDEN;row=activation_bytes%HIDDEN;
        if(token>=TOKENS || server_w_address!==ACT_BASE+64'(token)*ACT_STRIDE+64'(row) ||
           int'(server_w_length)*8!=(HIDDEN-row>128 ? 128 : HIDDEN-row))
          $fatal(1,"BATCH406_ACTIVATION_WRITE_ADDRESS");
        activation_requests++;
      end else begin
        if(activation_acks!=TOKENS*HIDDEN || server_w_length>10 ||
           server_w_address<SCRATCH_BASE || server_w_address+64'(server_w_length)*8>SCRATCH_BASE+64'(PLANES*TOKENS*INTERMEDIATE))
          $fatal(1,"BATCH406_INTERMEDIATE_WRITE_ADDRESS");
        offset=int'(server_w_address-SCRATCH_BASE);row=offset%INTERMEDIATE;
        if(row%80!=0 || int'(server_w_length)*8!=(INTERMEDIATE-row>80 ? 80 : INTERMEDIATE-row))
          $fatal(1,"BATCH406_WRITE_TILE_ADDRESS");
        write_requests++;
      end
      write_active<=1;write_address<=server_w_address;write_beat<=0;write_length<=int'(server_w_length);
    end
    if(server_w_data_valid && server_w_data_ready)begin
      if(!write_active || server_w_strobe!==8'hff || server_w_data_last!==(write_beat+1==write_length))
        $fatal(1,"BATCH406_WRITE_DATA_PROTOCOL");
      if(write_is_activation)begin
        for(int b=0;b<8;b++)begin
          token=(activation_bytes+b)/HIDDEN;row=(activation_bytes+b)%HIDDEN;
          if(server_w_data[b*8+:8]!==8'(activation_golden[token][row]))
            $fatal(1,"BATCH406_GENERATED_ACTIVATION token=%0d feature=%0d got=%h expected=%h",
              token,row,server_w_data[b*8+:8],8'(activation_golden[token][row]));
          activation_memory[activation_bytes+b]=server_w_data[b*8+:8];
        end
        activation_bytes+=8;
      end else begin
        offset=int'(write_address-SCRATCH_BASE)+write_beat*8;
        for(int b=0;b<8;b++)begin
          token=((offset+b)%(TOKENS*INTERMEDIATE))/INTERMEDIATE;row=(offset+b)%INTERMEDIATE;
          if(server_w_data[b*8+:8]!==8'((offset+b)/ (TOKENS*INTERMEDIATE)==0 ? golden_down[token][row] : golden_correction[token][row]))
            $fatal(1,"BATCH406_GATED_INTERMEDIATE token=%0d channel=%0d",token,row);
          $display("ROW_PLANE_TRACE epoch=%0d plane=%0d token=%0d channel=%0d code=%0d",transfer_epoch,(offset+b)/(TOKENS*INTERMEDIATE),token,row,$signed(server_w_data[b*8+:8]));$fflush();
          scratch[offset+b]=server_w_data[b*8+:8];writes[offset+b]++;write_bytes++;
        end
      end
      if(server_w_data_last)begin write_active<=0;response_delay<=3;end
      else write_beat<=write_beat+1;
    end
    if(response_delay>0)begin response_delay<=response_delay-1;if(response_delay==1)write_response<=1;end
    if(server_w_rsp_valid && server_w_rsp_ready)begin
      if(server_w_rsp_error)fault_seen<=1;
      else if(write_is_activation)begin
        for(int b=0;b<write_length*8;b++)activation_committed[activation_acks+b]=1;
        activation_acks+=write_length*8;
      end else for(int b=0;b<write_length*8;b++)committed[int'(write_address-SCRATCH_BASE)+b]=1;
      write_response<=0;
    end
    if(held_read_req && (!req_valid || {req_address,req_length}!==prior_read_req))$fatal(1,"BATCH406_READ_REQUEST_CHANGED");
    held_read_req=req_valid && !req_ready;if(held_read_req)prior_read_req={req_address,req_length};
    if(held_write_req && (!wr_req_valid || {wr_address,wr_length}!==prior_write_req))$fatal(1,"BATCH406_WRITE_REQUEST_CHANGED");
    held_write_req=wr_req_valid && !wr_req_ready;if(held_write_req)prior_write_req={wr_address,wr_length};
    if(held_write_data && (!wr_data_valid || {wr_data,wr_strobe,wr_data_last}!==prior_write_data))$fatal(1,"BATCH406_WRITE_DATA_CHANGED");
    held_write_data=wr_data_valid && !wr_data_ready;if(held_write_data)prior_write_data={wr_data,wr_strobe,wr_data_last};
    if(out_valid && !hold_done)begin first_hold<=first_hold+1;if(first_hold==3)hold_done<=1;end
    if(held_output && (!out_valid || {out_tag,out_token,out_start,out_count,out_last,out_data}!==prior_output))$fatal(1,"BATCH406_OUTPUT_CHANGED");
    held_output=out_valid && !out_ready;
    if(held_output)begin prior_output={out_tag,out_token,out_start,out_count,out_last,out_data};stalls++;end
    if(out_valid && out_ready)begin
      expected_start=(seen/TOKENS)*160;expected_token=seen%TOKENS;expected_count=OUTPUTS-expected_start>160 ? 160 : OUTPUTS-expected_start;
      if(seen>=OUTPUT_GROUPS*TOKENS || out_tag!==32'h39300001 || out_token!==4'(expected_token) || out_start!==16'(expected_start) || out_count!==8'(expected_count) ||
         out_last!==(expected_start+expected_count==OUTPUTS && expected_token==TOKENS-1))$fatal(1,"BATCH406_OUTPUT_METADATA");
      for(int column=0;column<expected_count;column++)
        if(out_data[column*32+:32]!==32'(golden[expected_token][expected_start+column]))
          $fatal(1,"BATCH406_OUTPUT_INTEGER token=%0d row=%0d got=%0d expected=%0d",expected_token,expected_start+column,$signed(out_data[column*32+:32]),golden[expected_token][expected_start+column]);
      for(int column=expected_count;column<160;column++)if(out_data[column*32+:32]!==0)$fatal(1,"BATCH406_NONZERO_PADDED_OUTPUT");
      if(expected_token==TOKENS-1)$display("BATCH406_OUTPUT_TILE start=%0d count=%0d",expected_start,expected_count);$fflush();
      for(int column=0;column<expected_count;column++)$display("ROW_OUTPUT_TRACE epoch=%0d token=%0d row=%0d raw=%0d",transfer_epoch,expected_token,expected_start+column,$signed(out_data[column*32+:32]));$fflush();
      seen++;
    end
    if($isunknown({cfg_ready,stats_ready,replay_ready,req_valid,rsp_ready,wr_req_valid,wr_data_valid,wr_rsp_ready,out_valid,done_valid}))$fatal(1,"BATCH406_UNKNOWN_PROTOCOL");
    if(PREFIX_ONLY && !ff_done && norm_values==TOKENS*HIDDEN && raw_dot_values>=320 && gated_values>=160 &&
       exact_margin_values>=384 && write_bytes>=320 && !read_active && !write_active && !write_response &&
       response_delay==0 && !req_valid && !wr_req_valid && !wr_data_valid && !rsp_valid && !wr_rsp_valid)begin
      for(int t=0;t<TOKENS;t++)for(int c=0;c<80;c++)if(!raw_seen[t*INTERMEDIATE+c] || !gated_seen[t*INTERMEDIATE+c])
        $fatal(1,"LEARNED_PREFIX_MISSING_COORDINATE");
      $display("LEARNED_PREFIX_PASS norm_values=%0d raw_dot_values=%0d gated_values=%0d exact_margin_values=%0d",norm_values,raw_dot_values,gated_values,exact_margin_values);$fflush();ff_done=1;
    end
  end
  initial begin: stimulus
    int gate_dot,up_dot,gated,norm_code;
    real energy,scaled;
    if(FAULT!=0 || !TRAINED || !ROW_UNITS || !CORRECTION || !CORE_STRIP)
      $fatal(1,"LEARNED_UNQUALIFIED_RUN_PARAMETERS");
    foreach(committed[i])begin committed[i]=0;writes[i]=0;end
    foreach(scratch_reads[i])scratch_reads[i]=0;
    if(TRAINED)begin
      if(!$value$plusargs("FIXTURE=%s",fixture))$fatal(1,"BATCH406_FIXTURE_REQUIRED");
      if(!$value$plusargs("LEARNED=%s",learned_fixture) || !$value$plusargs("OBSERVATIONS=%s",observations) ||
         !$value$plusargs("GATE=%s",gate_file) || !$value$plusargs("UP=%s",up_file) || !$value$plusargs("DOWN=%s",down_file) ||
         !$value$plusargs("METADATA=%s",metadata_file) || !$value$plusargs("GATE_SIGNS=%s",gate_sign_file) ||
         !$value$plusargs("UP_SIGNS=%s",up_sign_file))$fatal(1,"LEARNED_FIXTURE_ARGUMENTS");
      `LEARNED_READ_BYTES(fixture_activation,{fixture,"/activation.bin"},0,TOKENS*HIDDEN)
      `LEARNED_READ_BYTES(fixture_gate,gate_file,0,INTERMEDIATE*HIDDEN)
      `LEARNED_READ_BYTES(fixture_up,up_file,0,INTERMEDIATE*HIDDEN)
      `LEARNED_READ_BYTES(fixture_down,down_file,0,OUTPUTS*INTERMEDIATE)
      `LEARNED_READ_BYTES(fixture_metadata,metadata_file,0,GATE_GROUPS*64)
      `LEARNED_READ_BYTES(fixture_gate_signs,gate_sign_file,0,SIGN_BYTES)
      `LEARNED_READ_BYTES(fixture_up_signs,up_sign_file,0,SIGN_BYTES)
      `LEARNED_READ_BYTES(fixture_intermediate,{fixture,"/coarse.bin"},0,TOKENS*INTERMEDIATE)
      `LEARNED_READ_BYTES(fixture_intermediate,{fixture,"/correction.bin"},TOKENS*INTERMEDIATE,TOKENS*INTERMEDIATE)
      $readmemh({fixture,"/keep.hex"},fixture_keep);$readmemh({fixture,"/shifts.hex"},fixture_shifts);
      $readmemh({fixture,"/expected.hex"},fixture_output);$readmemh({fixture,"/gate_raw.hex"},fixture_gate_raw);
      $readmemh({fixture,"/up_raw.hex"},fixture_up_raw);$readmemh({fixture,"/gated.hex"},fixture_gated);
      $readmemh({learned_fixture,"/gamma.hex"},fixture_gamma);$readmemh({learned_fixture,"/affine_shifts.hex"},fixture_affine);
      $readmemh({learned_fixture,"/norm_codes.hex"},fixture_norm);$readmemh({learned_fixture,"/gate_margin.hex"},fixture_gate_margin);
      $readmemh({learned_fixture,"/up_margin.hex"},fixture_up_margin);$readmemh({observations,"/epsilon.hex"},fixture_epsilon);
      $readmemh({observations,"/outlier_counts.hex"},fixture_outlier_counts);$readmemh({observations,"/expected_sign_requests.hex"},fixture_sign_requests);
      for(int t=0;t<TOKENS;t++)for(int f=0;f<HIDDEN;f++)activation_golden[t][f]=int'($signed(fixture_activation[t*HIDDEN+f]));
      for(int token=0;token<TOKENS;token++)begin
        for(int channel=0;channel<INTERMEDIATE;channel++)begin
          golden_down[token][channel]=int'($signed(fixture_intermediate[token*INTERMEDIATE+channel]));
          golden_correction[token][channel]=CORRECTION ? int'($signed(fixture_intermediate[TOKENS*INTERMEDIATE+token*INTERMEDIATE+channel])) : 0;
        end
        for(int row=0;row<OUTPUTS;row++)golden[token][row]=int'($signed(fixture_output[token*OUTPUTS+row]));
      end
    end else for(int token=0;token<TOKENS;token++)begin
      energy=0.0;
      for(int feature=0;feature<HIDDEN;feature++)energy+=real'(residual_value(token,feature)**2);
      for(int feature=0;feature<HIDDEN;feature++)begin
        scaled=256.0*residual_value(token,feature)/$sqrt(energy/HIDDEN);
        norm_code=scaled>=0.0 ? $rtoi(scaled+0.5) : -$rtoi(-scaled+0.5);
        if((norm_code>768 || norm_code< -768)!=(feature==token+1 || feature==HIDDEN-token-1))
          $fatal(1,"BATCH406_LITERAL_OUTLIER_FIXTURE");
        activation_golden[token][feature]=quant(norm_code*gamma_value(feature),14+token%2,8);
      end
      for(int channel=0;channel<INTERMEDIATE;channel++)begin
        gate_dot=0;up_dot=0;
        for(int feature=0;feature<HIDDEN;feature++)begin
          gate_dot+=activation(token,feature)*gate_weight(channel,feature);up_dot+=activation(token,feature)*up_weight(channel,feature);
        end
        gated=quant(silu(quant(gate_dot,shift_gate(token)+gate_offset(channel),16))*quant(up_dot,shift_up(token)+up_offset(channel),16),8,16);
        golden_down[token][channel]=kept(token,channel) ? quant(gated,shift_down(token),8) : 0;
        golden_correction[token][channel]=0;
        if(CORRECTION && kept(token,channel))begin
          int delta;
          delta=quant(gated,shift_down(token),16)-golden_down[token][channel];
          golden_correction[token][channel]=delta>127 ? 127 : delta< -128 ? -128 : delta;
        end
      end
      for(int row=0;row<OUTPUTS;row++)begin
        golden[token][row]=0;
        for(int channel=0;channel<INTERMEDIATE;channel++)golden[token][row]+=(golden_down[token][channel]+golden_correction[token][channel])*down_weight(row,channel);
      end
    end
    fixture_loaded=1;wait(start_ff);
    if(!external_frame_available)$fatal(1,"CONNECTED_RESIDUAL_FRAME_INCOMPLETE");
    configure();
    fork send_residuals();wait(done_valid);join
    if(inject_fault)begin
      repeat(4)begin
        @(negedge clk);if(done_valid!==1'b1 || done_error!==1'b1 || done_tag!==32'h39300001 || read_active || write_active || write_response || response_delay!=0)
          $fatal(1,"BATCH406_FAULT_OWNERSHIP");
      end
      if(((FAULT<=4 || FAULT==7 || FAULT==11) && !fault_seen) || seen!=(FAULT==3 ? TOKENS : 0) ||
          (FAULT==4 && (sign_requests!=1 || read_beats!=2 || valid_masks!=0)) ||
          ((FAULT==5 || FAULT==6 || FAULT==8 || FAULT==9 || FAULT==10) &&
            (read_requests!=0 || write_requests!=0)) ||
          (FAULT==7 && (valid_masks!=1 || abort_masks!=1 || write_requests!=PLANES*TOKENS)) ||
          (FAULT==11 && (!held_second_retired || valid_masks!=2 || abort_masks!=1 || write_requests!=2*PLANES*TOKENS)))
        $fatal(1,"BATCH406_EXPECTED_FAULT_PHASE");
      if((FAULT==12 && (!fault_seen || activation_requests!=1 || activation_acks!=0 ||
           sign_requests!=0 || write_requests!=0 || valid_masks!=0)) ||
         (FAULT==13 && (!fault_seen || activation_bytes!=TOKENS*HIDDEN ||
           activation_acks!=TOKENS*HIDDEN-((HIDDEN-1)%128+1) || sign_requests!=0 || write_requests!=0 || valid_masks!=0)) ||
         (FAULT==16 && (activation_requests!=1 || activation_acks!=128 ||
           sign_requests!=0 || write_requests!=0 || valid_masks!=0)) ||
         ((FAULT==5 || FAULT==6 || FAULT==8 || FAULT==9 || FAULT==10 || FAULT==14 || FAULT==15 || FAULT>=19) &&
           (activation_requests!=0 || read_requests!=0 || normalizer_starts!=0)))
        $fatal(1,"BATCH406_ACTIVATION_FAULT_INVENTORY");
      if((FAULT==17 || FAULT==18) && (!fault_seen || metadata_requests!=1 || write_requests!=0 || seen!=0))
        $fatal(1,"BATCH_ROW_METADATA_FAULT_INVENTORY");
      if(FAULT>=19 && (activation_requests!=0 || normalizer_starts!=0 || read_requests!=0 || write_requests!=0))
        $fatal(1,"BATCH_ROW_DESCRIPTOR_FAULT_INVENTORY");
      $display("BATCH406_ACTIVATION_FAULT fault=%0d activation_acks=%0d activation_requests=%0d sign_reads=%0d",
        FAULT,activation_acks,activation_requests,sign_requests);$fflush();
      if(FAULT==11)$display("BATCH406_HELD_SECOND_RETIRED_BEFORE_ABORT");$fflush();
      $display("BATCH406_FAULT fault=%0d sign_requests=%0d valid_masks=%0d abort_masks=%0d writes=%0d",
        FAULT,sign_requests,valid_masks,abort_masks,write_requests);$fflush();
      $display("BATCH406_FAULT_DRAINED fault=%0d output_prefix_packets=%0d",FAULT,seen);$fflush();
      done_ready=1;@(posedge clk);@(negedge clk);done_ready=0;
      inject_fault=0;seen=0;read_requests=0;read_beats=0;write_requests=0;write_bytes=0;
      sign_requests=0;valid_masks=0;abort_masks=0;contended_cycles=0;
      activation_bytes=0;activation_acks=0;activation_requests=0;normalizer_starts=0;
      foreach(activation_committed[i])begin activation_committed[i]=0;activation_memory[i]='x;end
      foreach(committed[i])begin committed[i]=0;writes[i]=0;end
      foreach(scratch_reads[i])scratch_reads[i]=0;
      configure();fork send_residuals();wait(done_valid);join
    end
    repeat(4)begin
      @(negedge clk);if(done_valid!==1'b1 || done_error!==1'b0 || done_tag!==32'h39300001 || read_active || write_active || write_response || response_delay!=0)
        $fatal(1,"BATCH406_DONE_METADATA");
    end
    if(seen!=OUTPUT_GROUPS*TOKENS || write_requests!=PLANES*GATE_GROUPS*TOKENS || write_bytes!=PLANES*TOKENS*INTERMEDIATE || first_hold!=4 || stalls<4)$fatal(1,"BATCH406_FINAL_INVENTORY");
    foreach(committed[i])if(!committed[i] || writes[i]!=1)$fatal(1,"BATCH406_INTERMEDIATE_WRITE_COUNT");
    foreach(scratch_reads[i])if(scratch_reads[i]!=OUTPUT_GROUPS)$fatal(1,"BATCH406_INTERMEDIATE_READ_COUNT");
    done_ready=1;@(posedge clk);@(negedge clk);done_ready=0;if(!cfg_ready)$fatal(1,"BATCH406_OWNER_NOT_RELEASED");
    if(sign_requests!=SIGN_EXPECTED || valid_masks!=GATE_GROUPS || abort_masks!=0 ||
        (INTERMEDIATE>=192 && contended_cycles==0))$fatal(1,"BATCH406_SHARED_BUS_INVENTORY");
    if(activation_bytes!=TOKENS*HIDDEN || activation_acks!=activation_bytes ||
       activation_requests!=TOKENS*((HIDDEN+127)/128) || normalizer_starts!=TOKENS)
      $fatal(1,"BATCH406_ACTIVATION_FINAL_INVENTORY");
    $display("BATCH406_ACTIVATION_PASS bytes=%0d bursts=%0d normalizations=%0d",
      activation_acks,activation_requests,normalizer_starts);$fflush();
    $display("BATCH406_SHARED_BUS sign_requests=%0d valid_masks=%0d contended_cycles=%0d",
      sign_requests,valid_masks,contended_cycles);$fflush();
    if(metadata_requests!=(ROW_UNITS ? GATE_GROUPS : 0))$fatal(1,"BATCH_ROW_WRONG_METADATA_TOTAL");
    if(done_valid && $isunknown({done_error,done_tag}))$fatal(1,"BATCH_ROW_UNKNOWN_COMPLETION");
    if(norm_values!=TOKENS*HIDDEN || prediction_packets!=TOKENS*(INTERMEDIATE/32) ||
       raw_dot_values!=2*TOKENS*INTERMEDIATE || gated_values!=TOKENS*INTERMEDIATE || exact_margin_values!=2*TOKENS*INTERMEDIATE)$fatal(1,"LEARNED_FINAL_INVENTORY");
    foreach(raw_seen[i])if(!raw_seen[i] || !gated_seen[i])$fatal(1,"LEARNED_MISSING_COORDINATE");
    $display("LEARNED_EXACT_MARGIN_PASS values=%0d",exact_margin_values);$fflush();
    $display("LEARNED_FULL_METHOD_PASS norm_values=%0d prediction_packets=%0d sign_requests=%0d raw_dot_values=%0d gated_values=%0d",norm_values,prediction_packets,sign_requests,raw_dot_values,gated_values);$fflush();
    $display("BATCH_ROW_METHOD_PASS row_units=%0d correction=%0d metadata_requests=%0d",ROW_UNITS,CORRECTION,metadata_requests);$fflush();
    $display("BATCH406_PASS tokens=%0d hidden=%0d intermediate=%0d outputs=%0d exact_outputs=%0d intermediate_bytes=%0d output_packets=%0d read_requests=%0d read_bytes=%0d fault=%0d trained=%0d",TOKENS,HIDDEN,INTERMEDIATE,OUTPUTS,TOKENS*OUTPUTS,write_bytes,seen,read_requests,read_beats*8,FAULT,TRAINED);$fflush();ff_done=1;
  end
  initial begin #(TRAINED ? 300000000 : 15000000);$fatal(1,"BATCH406_WATCHDOG");end
endmodule

`undef LEARNED_READ_BYTES
