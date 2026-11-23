`timescale 1ns/1ps
// Complete feedforward reference through one native compute fabric. Literal
// controls check both tails and errors; trained mode uses all original rows.
module tri_oracle_external_row_ff_tb;
  parameter int FAULT=0,HIDDEN=64,INTERMEDIATE=96,OUTPUTS=173,TOKENS=3;
  parameter bit TRAINED=0,ROW_UNITS=1,CORRECTION=1,FAST=0;
  parameter int WEIGHT_GAIN=1;
  localparam int PLANES=CORRECTION ? 2 : 1;
  localparam int GATE_GROUPS=(INTERMEDIATE+79)/80,OUTPUT_GROUPS=(OUTPUTS+159)/160;
  localparam logic [63:0] ACT_BASE=64'h00000001ffffffc0;
  localparam logic [63:0] GATE_BASE=64'h00000003fffff000;
  localparam logic [63:0] UP_BASE=64'h00000005fffff000;
  localparam logic [63:0] DOWN_BASE=64'h00000007fffff000;
  localparam logic [63:0] SCRATCH_BASE=64'h00000009ffffff80;
  logic clk=0;always #5 clk=~clk;
  logic rst_n=0,cfg_valid=0,done_ready=0;
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
  logic stats_valid=0,stats_last=0,replay_valid=0,replay_last=0;
  wire stats_ready,replay_ready;
  wire [3:0] residual_token;
  logic [127:0] stats_data=0,replay_data=0,replay_gamma=0;
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
  wire out_ready=hold_done && (FAST || cycle%11>=5);
  wire req_valid,rsp_ready;
  wire [63:0] req_address;
  wire [4:0] req_length;
  bit read_active=0,read_bubble=0;
  logic [63:0] read_address=0;
  int read_beat=0,read_length=0,read_requests=0,read_beats=0;
  wire req_ready=!read_active && (FAST || cycle%7>=3);
  wire rsp_valid=read_active && !read_bubble;
  wire rsp_last=read_beat+1==read_length;
  wire rsp_error=inject_fault && !fault_seen &&
     ((FAULT==2 && read_address>=DOWN_BASE && read_address<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE)) ||
      (FAULT==3 && read_address>=DOWN_BASE+64'(160*INTERMEDIATE) && read_address<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE)) ||
      sign_fault_address(read_address) || (FAULT==17 && metadata_address(read_address) && read_beat==3));
  logic [63:0] rsp_data;
  wire wr_req_valid,wr_data_valid,wr_data_last,wr_rsp_ready;
  wire [63:0] wr_address,wr_data;
  wire [4:0] wr_length;
  wire [7:0] wr_strobe;
  bit write_active=0,write_response=0;
  logic [63:0] write_address=0;
  int write_beat=0,write_length=0,response_delay=0,write_requests=0,write_bytes=0;
  wire wr_req_ready=!write_active && !write_response && response_delay==0 && (FAST || cycle%5>=2);
  wire wr_data_ready=write_active && (FAST || cycle%7!=0);
  wire wr_rsp_valid=write_response &&
    (write_is_activation || !(inject_fault && FAULT==11) || fault_seen);
  wire wr_rsp_error=inject_fault && !fault_seen &&
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
  string fixture;
  bit held_read_req=0,held_write_req=0,held_write_data=0,held_output=0;
  logic [68:0] prior_read_req,prior_write_req;
  logic [72:0] prior_write_data;
  logic [5280:0] prior_output;

  parameter bit CORE_STRIP=1;
  tri_oracle_attention_tensor437 attention();
  assign {attention.cfg_valid,attention.cfg_tag,attention.cfg_activation_stride,
    attention.cfg_tokens,attention.cfg_feature_words,attention.cfg_dense_rows,
    attention.cfg_count,attention.cfg_channels,attention.cfg_keep,
    attention.cfg_activation_base,attention.cfg_weight_base,
    attention.out_ready,attention.done_ready}='0;
  tri_oracle_fabric_owner_types::request_t backend_request;
  tri_oracle_fabric_owner_types::response_t backend_response;
  logic [533:0] strip_request;
  logic [111:0] strip_response;
  tri_oracle_external_row_learned #(.CORE_STRIP_PREDICTOR(CORE_STRIP)) dut (
    .attention,.strip_request,.strip_response,.softmax_request('0),
    .backend_request,.backend_response,.*
  );
  tri_oracle_compute_fabric #(
    .AGGREGATOR_SIGN_BANK(1),.AGGREGATOR_MERGE_TABLE(1),
    .LOCAL_TOKEN_SIZES(1),.LOCAL_TOKEN_MERGE(1),
    .CORE_STRIP_PREDICTOR(CORE_STRIP),.CORE_HEAD_PREDICTOR(1)
  ) fabric (
    .clk,.rst_n(backend_request.rst_n),
    .load_valid(backend_request.load_valid),.load_core(backend_request.load_core),
    .load_kind(backend_request.load_kind),.load_addr(backend_request.load_addr),
    .load_data(backend_request.load_data),.load_row_enable(backend_request.load_rows),
    .load_error(backend_response.load_error),
    .cmd_valid(backend_request.cmd_valid),.cmd_ready(backend_response.cmd_ready),
    .cmd_clusters(backend_request.cmd_clusters),.cmd_weight(backend_request.cmd_weight),
    .cmd_mask(backend_request.cmd_mask),.cmd_activation(backend_request.cmd_activation),
    .cmd_output(backend_request.cmd_output),.cmd_accumulate(backend_request.cmd_accumulate),
    .cmd_reduce(backend_request.cmd_reduce),.core_score_select(backend_request.core_select),
    .activation_reloaded(backend_request.activation_reloaded),
    .out_valid(backend_response.out_valid),.out_ready(backend_request.out_ready),
    .out_output(backend_response.out_output),.out_data(backend_response.out_data),
    .softmax_request('0),.softmax_response(),
    .strip_rst_n(rst_n),.strip_request,.strip_response,
    .merge_sign_data('0),.merge_sign_control('0),.merge_sign_counts(),
    .merge_table_request('0),.merge_table_word(),
    .token_sizes_request('0),.token_sizes_response(),
    .merge_request('0),.merge_response(),.head_request('0),.head_response()
  );


  function automatic int gate_offset(input int channel);return ROW_UNITS ? channel%8 : 0;endfunction
  function automatic int up_offset(input int channel);return ROW_UNITS ? (3*channel+1)%8 : 0;endfunction
  function automatic bit metadata_address(input logic [63:0] address);
    return address>=ROW_UNITS_BASE && address<ROW_UNITS_BASE+64'(GATE_GROUPS*64);
  endfunction
  function automatic logic [511:0] metadata_record(input int group);
    metadata_record=0;
    for(int channel=0;channel<80;channel++)if(group*80+channel<INTERMEDIATE)
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
  function automatic logic [127:0] raw_strip(input int token,strip);
    for(int lane=0;lane<8;lane++)raw_strip[16*lane+:16]=16'(residual_value(token,strip*8+lane));
  endfunction
  function automatic int residual_value(input int token,feature);
    if(feature==token+1)return 1200;
    if(feature==HIDDEN-token-1)return -1200;
    return (token*29+feature*11)%61-30;
  endfunction
  function automatic int gamma_value(input int feature);
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
    current=read_address+64'(read_beat*8);rsp_data=0;
    if(metadata_address(current))begin
      offset=int'(current-ROW_UNITS_BASE);
      rsp_data=64'(metadata_record(offset/64)>>((offset%64)*8));
      if(inject_fault && !fault_seen && FAULT==18 && read_beat==7)rsp_data[63]=1;
    end else if(sign_address(current))begin
      offset=int'(current-(current>=UP_SIGN_BASE ? UP_SIGN_BASE : GATE_SIGN_BASE))/8;
      row=(offset/(HIDDEN/2))*32;
      feature=2*(offset%(HIDDEN/2));
      for(int b=0;b<64;b++)
        rsp_data[b]=current>=UP_SIGN_BASE ? up_weight(row+b%32,feature+b/32)<0 :
                                          gate_weight(row+b%32,feature+b/32)<0;
    end else if(activation_address(current))begin
      offset=int'(current-ACT_BASE);token=offset/ACT_STRIDE;feature=offset%ACT_STRIDE;
      for(int b=0;b<8;b++)rsp_data[b*8+:8]=activation_memory[token*HIDDEN+feature+b];
    end else if(current>=GATE_BASE && current<GATE_BASE+64'(INTERMEDIATE*HIDDEN))begin
      offset=int'(current-GATE_BASE);row=offset/HIDDEN;feature=offset%HIDDEN;
      for(int b=0;b<8;b++)rsp_data[b*8+:8]=8'(gate_weight(row,feature+b));
    end else if(current>=UP_BASE && current<UP_BASE+64'(INTERMEDIATE*HIDDEN))begin
      offset=int'(current-UP_BASE);row=offset/HIDDEN;feature=offset%HIDDEN;
      for(int b=0;b<8;b++)rsp_data[b*8+:8]=8'(up_weight(row,feature+b));
    end else if(current>=DOWN_BASE && current<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE))begin
      offset=int'(current-DOWN_BASE);row=offset/INTERMEDIATE;feature=offset%INTERMEDIATE;
      for(int b=0;b<8;b++)rsp_data[b*8+:8]=8'(down_weight(row,feature+b));
    end else if(current>=SCRATCH_BASE && current<SCRATCH_BASE+64'(PLANES*TOKENS*INTERMEDIATE))begin
      offset=int'(current-SCRATCH_BASE);
      for(int b=0;b<8;b++)rsp_data[b*8+:8]=scratch[offset+b];
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
    cfg_gate_sign_base=GATE_SIGN_BASE;cfg_up_sign_base=UP_SIGN_BASE;cfg_epsilon_q16=0;
    if(inject_fault && FAULT==8)cfg_intermediate_base=GATE_SIGN_BASE;
    if(inject_fault && FAULT==9)cfg_output_features=0;
    if(inject_fault && FAULT==10)cfg_activation_stride=HIDDEN+1;
    if(inject_fault && FAULT==14)cfg_activation_base=GATE_BASE;
    if(inject_fault && FAULT==15)cfg_activation_base=GATE_SIGN_BASE;
    for(int token=0;token<TOKENS;token++)cfg_activation_shifts[6*token+:6]=6'(14+token%2);
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
    if(inject_fault && (FAULT==5 || FAULT==6 || FAULT==8 || FAULT==9 || FAULT==10 || FAULT==14 || FAULT==15 || FAULT>=19))begin
      repeat(16)@(negedge clk);
      if(!done_valid || !done_error || req_valid || stats_ready || replay_ready)
        $fatal(1,"BATCH406_INVALID_DESCRIPTOR_WAITED_FOR_RESIDUAL");
      return;
    end
    for(int token=0;token<TOKENS;token++)begin
      for(int strip=0;strip<HIDDEN/8;strip++)begin
        stats_valid=1;stats_last=strip==HIDDEN/8-1;stats_data=raw_strip(token,strip);
        while(!stats_ready)begin
          if(done_valid)begin stats_valid=0;return;end
          @(negedge clk);
        end
        @(posedge clk);if(residual_token!==4'(token))$fatal(1,"BATCH406_STATS_TOKEN");
        @(negedge clk);
      end
      stats_valid=0;stats_data='1;
      for(int strip=0;strip<HIDDEN/8;strip++)begin
        replay_valid=1;replay_last=strip==HIDDEN/8-1;replay_data=raw_strip(token,strip);
        if(inject_fault && FAULT==16 && token==0 && replay_last)replay_data[15:0]=16'sd32000;
        for(int lane=0;lane<8;lane++)replay_gamma[16*lane+:16]=16'(gamma_value(strip*8+lane));
        while(!replay_ready)begin
          if(done_valid)begin replay_valid=0;return;end
          @(negedge clk);
        end
        @(posedge clk);if(residual_token!==4'(token))$fatal(1,"BATCH406_REPLAY_TOKEN");
        @(negedge clk);
      end
      replay_valid=0;replay_data='1;replay_gamma='x;
    end
  endtask
  always @(posedge clk)if(rst_n)begin: bus_and_scoreboard
    logic [63:0] current;
    int offset,row,token,expected_start,expected_token,expected_count;
    cycle<=cycle+1;
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
    if(req_valid && req_ready)begin
      if(read_active || req_length==0 || req_length>16 || req_address[2:0]!=0)$fatal(1,"BATCH406_READ_REQUEST");
      if(activation_acks!=TOKENS*HIDDEN)$fatal(1,"BATCH406_READ_BEFORE_ACTIVATION_ACK");
      if((req_address>=GATE_BASE && req_address<GATE_BASE+64'(INTERMEDIATE*HIDDEN)) ||
         (req_address>=UP_BASE && req_address<UP_BASE+64'(INTERMEDIATE*HIDDEN)))begin
        int group;
        group=int'(req_address-(req_address>=UP_BASE ? UP_BASE : GATE_BASE))/HIDDEN/80;
        if(ROW_UNITS && !metadata_committed[group])$fatal(1,"BATCH_ROW_READ_BEFORE_METADATA group=%0d",group);
      end
      if(metadata_address(req_address))begin
        offset=int'(req_address-ROW_UNITS_BASE);
        if(!ROW_UNITS || req_length!=8 || offset%64!=0 || metadata_committed[offset/64])
          $fatal(1,"BATCH_ROW_METADATA_REQUEST");
        metadata_requests++;
      end else if(activation_address(req_address))begin
        offset=int'(req_address-ACT_BASE);token=offset/ACT_STRIDE;row=offset%ACT_STRIDE;
        if(row+int'(req_length)*8>HIDDEN)$fatal(1,"BATCH406_ACTIVATION_PADDING_READ");
        for(int b=0;b<int'(req_length)*8;b++)
          if(!activation_committed[token*HIDDEN+row+b])$fatal(1,"BATCH406_UNCOMMITTED_ACTIVATION_READ");
      end else if(req_address>=SCRATCH_BASE && req_address<SCRATCH_BASE+64'(PLANES*TOKENS*INTERMEDIATE))begin
        offset=int'(req_address-SCRATCH_BASE);
        for(int b=0;b<int'(req_length)*8;b++)if(!committed[offset+b])$fatal(1,"BATCH406_READ_BEFORE_WRITE_ACK");
      end else if(sign_address(req_address))begin
        if(req_length!=1)$fatal(1,"BATCH406_SIGN_BURST");
        sign_requests++;
      end else if(!(
           (req_address>=GATE_BASE && req_address<GATE_BASE+64'(INTERMEDIATE*HIDDEN)) ||
           (req_address>=UP_BASE && req_address<UP_BASE+64'(INTERMEDIATE*HIDDEN)) ||
           (req_address>=DOWN_BASE && req_address<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE))))$fatal(1,"BATCH406_UNKNOWN_READ_ADDRESS %h",req_address);
      read_active<=1;read_address<=req_address;read_beat<=0;read_bubble<=0;read_requests++;read_error_seen<=0;
      if(inject_fault && !fault_seen && sign_fault_address(req_address))begin
        read_length<=2;
        if(FAULT==11)begin
          if(!dut.compute_mask_valid || dut.compute_mask_ready || dut.packet_mask_start!=80)
            $fatal(1,"BATCH406_NO_HELD_SECOND_AT_FAULT");
          verify_held_second=1;
          held_second=dut.packet_mask_bits;
        end
      end
      else read_length<=int'(req_length);
    end
    if(rsp_valid && rsp_ready)begin
      current=read_address+64'(read_beat*8);read_beats++;
      if(metadata_address(read_address))$display("ROW_METADATA_TRACE epoch=%0d record=%0d word=%0d data=%016h",transfer_epoch,int'(read_address-ROW_UNITS_BASE)/64,read_beat,rsp_data);$fflush();
      if(current>=SCRATCH_BASE && current<SCRATCH_BASE+64'(PLANES*TOKENS*INTERMEDIATE))scratch_reads[int'(current-SCRATCH_BASE)/8]++;
      if(rsp_error)begin fault_seen<=1;read_error_seen<=1;end
      if(metadata_address(read_address) && rsp_last)begin
        if(inject_fault && !fault_seen && FAULT==18)fault_seen<=1;
        if(!read_error_seen && !rsp_error && !(inject_fault && FAULT==18))
          metadata_committed[int'(read_address-ROW_UNITS_BASE)/64]=1;
      end
      if(rsp_last)read_active<=0;else begin read_beat<=read_beat+1;read_bubble<=!FAST && cycle%5==0;end
    end
    if(wr_req_valid && wr_req_ready)begin
      if(write_active || write_response || wr_length==0 || wr_address[2:0]!=0)
        $fatal(1,"BATCH406_WRITE_REQUEST");
      write_is_activation<=activation_address(wr_address);
      if(activation_address(wr_address))begin
        token=activation_bytes/HIDDEN;row=activation_bytes%HIDDEN;
        if(token>=TOKENS || wr_address!==ACT_BASE+64'(token)*ACT_STRIDE+64'(row) ||
           int'(wr_length)*8!=(HIDDEN-row>128 ? 128 : HIDDEN-row))
          $fatal(1,"BATCH406_ACTIVATION_WRITE_ADDRESS");
        activation_requests++;
      end else begin
        if(activation_acks!=TOKENS*HIDDEN || wr_length>10 ||
           wr_address<SCRATCH_BASE || wr_address+64'(wr_length)*8>SCRATCH_BASE+64'(PLANES*TOKENS*INTERMEDIATE))
          $fatal(1,"BATCH406_INTERMEDIATE_WRITE_ADDRESS");
        offset=int'(wr_address-SCRATCH_BASE);row=offset%INTERMEDIATE;
        if(row%80!=0 || int'(wr_length)*8!=(INTERMEDIATE-row>80 ? 80 : INTERMEDIATE-row))
          $fatal(1,"BATCH406_WRITE_TILE_ADDRESS");
        write_requests++;
      end
      write_active<=1;write_address<=wr_address;write_beat<=0;write_length<=int'(wr_length);
    end
    if(wr_data_valid && wr_data_ready)begin
      if(!write_active || wr_strobe!==8'hff || wr_data_last!==(write_beat+1==write_length))
        $fatal(1,"BATCH406_WRITE_DATA_PROTOCOL");
      if(write_is_activation)begin
        for(int b=0;b<8;b++)begin
          token=(activation_bytes+b)/HIDDEN;row=(activation_bytes+b)%HIDDEN;
          if(wr_data[b*8+:8]!==8'(activation_golden[token][row]))
            $fatal(1,"BATCH406_GENERATED_ACTIVATION token=%0d feature=%0d got=%h expected=%h",
              token,row,wr_data[b*8+:8],8'(activation_golden[token][row]));
          activation_memory[activation_bytes+b]=wr_data[b*8+:8];
        end
        activation_bytes+=8;
      end else begin
        offset=int'(write_address-SCRATCH_BASE)+write_beat*8;
        for(int b=0;b<8;b++)begin
          token=((offset+b)%(TOKENS*INTERMEDIATE))/INTERMEDIATE;row=(offset+b)%INTERMEDIATE;
          if(wr_data[b*8+:8]!==8'((offset+b)/ (TOKENS*INTERMEDIATE)==0 ? golden_down[token][row] : golden_correction[token][row]))
            $fatal(1,"BATCH406_GATED_INTERMEDIATE token=%0d channel=%0d",token,row);
          $display("ROW_PLANE_TRACE epoch=%0d plane=%0d token=%0d channel=%0d code=%0d",transfer_epoch,(offset+b)/(TOKENS*INTERMEDIATE),token,row,$signed(wr_data[b*8+:8]));$fflush();
          scratch[offset+b]=wr_data[b*8+:8];writes[offset+b]++;write_bytes++;
        end
      end
      if(wr_data_last)begin write_active<=0;response_delay<=3;end
      else write_beat<=write_beat+1;
    end
    if(response_delay>0)begin response_delay<=response_delay-1;if(response_delay==1)write_response<=1;end
    if(wr_rsp_valid && wr_rsp_ready)begin
      if(wr_rsp_error)fault_seen<=1;
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
  end
  initial begin: stimulus
    int gate_dot,up_dot,gated,norm_code;
    real energy,scaled;
    foreach(committed[i])begin committed[i]=0;writes[i]=0;end
    foreach(scratch_reads[i])scratch_reads[i]=0;
    if(TRAINED)begin
      if(!$value$plusargs("FIXTURE=%s",fixture))$fatal(1,"BATCH406_FIXTURE_REQUIRED");
      $readmemh({fixture,"/activation.hex"},fixture_activation);$readmemh({fixture,"/gate.hex"},fixture_gate);
      $readmemh({fixture,"/up.hex"},fixture_up);$readmemh({fixture,"/down.hex"},fixture_down);
      $readmemh({fixture,"/keep.hex"},fixture_keep);$readmemh({fixture,"/shifts.hex"},fixture_shifts);
      $readmemh({fixture,"/intermediate.hex"},fixture_intermediate);$readmemh({fixture,"/expected.hex"},fixture_output);
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
    repeat(3)@(negedge clk);rst_n=1;configure();
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
    if(sign_requests!=TOKENS*(INTERMEDIATE/32)*4 || valid_masks!=GATE_GROUPS || abort_masks!=0 ||
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
    $display("BATCH_ROW_METHOD_PASS row_units=%0d correction=%0d metadata_requests=%0d",ROW_UNITS,CORRECTION,metadata_requests);$fflush();
    $display("BATCH406_PASS tokens=%0d hidden=%0d intermediate=%0d outputs=%0d exact_outputs=%0d intermediate_bytes=%0d output_packets=%0d read_requests=%0d read_bytes=%0d fault=%0d trained=%0d",TOKENS,HIDDEN,INTERMEDIATE,OUTPUTS,TOKENS*OUTPUTS,write_bytes,seen,read_requests,read_beats*8,FAULT,TRAINED);$fflush();$finish;
  end
  initial begin #(TRAINED ? 300000000 : 15000000);$fatal(1,"BATCH406_WATCHDOG");end
endmodule
