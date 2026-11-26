`timescale 1ns/1ps
module tri_oracle_raw32_memory_unit_tb;
  // All journal snapshots are sampled before nonblocking assignments.
  logic clk=0, rst_n=0;
  int unit_mode=0, case_id=-1, cycle=0, active_source=0;
  bit log_active=0;
  logic cfg_valid=0;
  logic [31:0] cfg_tag=0;
  logic [9:0] cfg_strips=0;
  logic [63:0] cfg_raw_base=0, cfg_gamma_base=0, cfg_epsilon_q16=0;
  logic signed [7:0] cfg_gamma_exponent=0;
  logic abort_valid=0, stats_ready=0, replay_ready=0, out_ready=0;
  logic done_ready=0, clear_valid=0, req_ready=0;
  logic rsp_valid=0, rsp_last=0, rsp_error=0;
  logic [63:0] rsp_data=0;
  bit force_req_stall=0, force_stream_stall=0, force_out_stall=0;
  bit unsolicited=0, zero_latency=0;
  int malformed=0;
  bit pending=0, response_retired=0, check_outputs=0;
  logic [63:0] memory_address=0;
  int memory_length=0, memory_beat=0, actual_length=0;
  int requests=0, responses=0, stats=0, replays=0, outputs=0, dones=0;
  int configs=0;
  bit req_held=0, stats_held=0, replay_held=0, out_held=0, done_held=0;
  logic [68:0] req_payload=0;
  logic [448:0] stats_payload=0, replay_payload=0;
  logic [144:0] out_payload=0;
  logic [32:0] done_payload=0;
  logic [255:0] raw_words[0:1794];
  logic [191:0] gain_words[0:1794];
  logic [63:0] activation_words[0:1794];
  logic [7:0] sign_words[0:1794],outlier_words[0:1794],outlier_negative_words[0:1794];
  logic [31:0] row_offsets[0:8],row_tags[0:8];
  logic [9:0] row_strips[0:8];
  logic [63:0] row_epsilon[0:8];
  logic signed [7:0] row_gamma_exponent[0:8];
  logic signed [8:0] row_out_exponent[0:8];
  string data_root;
  logic a_clk;
  logic a_rst_n;
  logic a_cfg_valid;
  logic a_cfg_ready;
  logic [31:0] a_cfg_tag;
  logic [9:0] a_cfg_strips;
  logic [63:0] a_cfg_raw_base;
  logic [63:0] a_cfg_gamma_base;
  logic a_abort_valid;
  logic a_stats_valid;
  logic a_stats_ready;
  logic a_stats_last;
  logic [255:0] a_stats_data;
  logic [191:0] a_stats_gamma;
  logic a_replay_valid;
  logic a_replay_ready;
  logic a_replay_last;
  logic [255:0] a_replay_data;
  logic [191:0] a_replay_gamma;
  logic a_req_valid;
  logic a_req_ready;
  logic [63:0] a_req_address;
  logic [4:0] a_req_length;
  logic a_rsp_valid;
  logic a_rsp_ready;
  logic a_rsp_last;
  logic a_rsp_error;
  logic [63:0] a_rsp_data;
  logic a_port_idle;
  logic a_idle;
  logic a_row_fault;
  logic a_done_valid;
  logic a_done_ready;
  logic a_done_error;
  logic [31:0] a_done_tag;
  logic a_clear_valid;
  logic a_clear_ready;
  logic b_clk;
  logic b_rst_n;
  logic b_cfg_valid;
  logic b_cfg_ready;
  logic [31:0] b_cfg_tag;
  logic [9:0] b_cfg_strips;
  logic [63:0] b_cfg_raw_base;
  logic [63:0] b_cfg_gamma_base;
  logic b_abort_valid;
  logic [63:0] b_cfg_epsilon_q16;
  logic signed [7:0] b_cfg_gamma_exponent;
  logic b_out_valid;
  logic b_out_ready;
  logic b_out_last;
  logic b_out_error;
  logic [31:0] b_out_tag;
  logic [9:0] b_out_index;
  logic [3:0] b_out_count;
  logic [63:0] b_out_activation;
  logic signed [8:0] b_out_exponent;
  logic [7:0] b_out_outlier_mask;
  logic [7:0] b_out_outlier_negative;
  logic [7:0] b_out_normalized_negative;
  logic b_req_valid;
  logic b_req_ready;
  logic [63:0] b_req_address;
  logic [4:0] b_req_length;
  logic b_rsp_valid;
  logic b_rsp_ready;
  logic b_rsp_last;
  logic b_rsp_error;
  logic [63:0] b_rsp_data;
  logic b_port_idle;
  logic b_idle;
  logic b_row_fault;
  logic b_done_valid;
  logic b_done_ready;
  logic b_done_error;
  logic [31:0] b_done_tag;
  logic m_cfg_ready;
  logic m_req_valid;
  logic [63:0] m_req_address;
  logic [4:0] m_req_length;
  logic m_rsp_ready;
  logic m_port_idle;
  logic m_idle;
  logic m_row_fault;
  logic m_done_valid;
  logic m_done_error;
  logic [31:0] m_done_tag;
  wire m_stats_valid;
  wire m_stats_ready;
  wire m_replay_valid;
  wire m_replay_ready;
  assign a_clk = clk;
  assign a_rst_n = (rst_n && unit_mode==0);
  assign a_cfg_valid = cfg_valid;
  assign a_cfg_tag = cfg_tag;
  assign a_cfg_strips = cfg_strips;
  assign a_cfg_raw_base = cfg_raw_base;
  assign a_cfg_gamma_base = cfg_gamma_base;
  assign a_abort_valid = abort_valid;
  assign a_stats_ready = stats_ready;
  assign a_replay_ready = replay_ready;
  assign a_req_ready = req_ready;
  assign a_rsp_valid = rsp_valid;
  assign a_rsp_last = rsp_last;
  assign a_rsp_error = rsp_error;
  assign a_rsp_data = rsp_data;
  assign a_done_ready = done_ready;
  assign a_clear_valid = clear_valid;
  tri_oracle_raw32_gamma24_reader_v1 dut_a (
    .clk(a_clk),
    .rst_n(a_rst_n),
    .cfg_valid(a_cfg_valid),
    .cfg_ready(a_cfg_ready),
    .cfg_tag(a_cfg_tag),
    .cfg_strips(a_cfg_strips),
    .cfg_raw_base(a_cfg_raw_base),
    .cfg_gamma_base(a_cfg_gamma_base),
    .abort_valid(a_abort_valid),
    .stats_valid(a_stats_valid),
    .stats_ready(a_stats_ready),
    .stats_last(a_stats_last),
    .stats_data(a_stats_data),
    .stats_gamma(a_stats_gamma),
    .replay_valid(a_replay_valid),
    .replay_ready(a_replay_ready),
    .replay_last(a_replay_last),
    .replay_data(a_replay_data),
    .replay_gamma(a_replay_gamma),
    .req_valid(a_req_valid),
    .req_ready(a_req_ready),
    .req_address(a_req_address),
    .req_length(a_req_length),
    .rsp_valid(a_rsp_valid),
    .rsp_ready(a_rsp_ready),
    .rsp_last(a_rsp_last),
    .rsp_error(a_rsp_error),
    .rsp_data(a_rsp_data),
    .port_idle(a_port_idle),
    .idle(a_idle),
    .row_fault(a_row_fault),
    .done_valid(a_done_valid),
    .done_ready(a_done_ready),
    .done_error(a_done_error),
    .done_tag(a_done_tag),
    .clear_valid(a_clear_valid),
    .clear_ready(a_clear_ready)
  );
  assign b_clk = clk;
  assign b_rst_n = (rst_n && unit_mode==1);
  assign b_cfg_valid = cfg_valid;
  assign b_cfg_tag = cfg_tag;
  assign b_cfg_strips = cfg_strips;
  assign b_cfg_raw_base = cfg_raw_base;
  assign b_cfg_gamma_base = cfg_gamma_base;
  assign b_abort_valid = abort_valid;
  assign b_cfg_epsilon_q16 = cfg_epsilon_q16;
  assign b_cfg_gamma_exponent = cfg_gamma_exponent;
  assign b_out_ready = out_ready;
  assign b_req_ready = req_ready;
  assign b_rsp_valid = rsp_valid;
  assign b_rsp_last = rsp_last;
  assign b_rsp_error = rsp_error;
  assign b_rsp_data = rsp_data;
  assign b_done_ready = done_ready;
  tri_oracle_memory_input_normalizer_wide_v1 dut_b (
    .clk(b_clk),
    .rst_n(b_rst_n),
    .cfg_valid(b_cfg_valid),
    .cfg_ready(b_cfg_ready),
    .cfg_tag(b_cfg_tag),
    .cfg_strips(b_cfg_strips),
    .cfg_raw_base(b_cfg_raw_base),
    .cfg_gamma_base(b_cfg_gamma_base),
    .abort_valid(b_abort_valid),
    .cfg_epsilon_q16(b_cfg_epsilon_q16),
    .cfg_gamma_exponent(b_cfg_gamma_exponent),
    .out_valid(b_out_valid),
    .out_ready(b_out_ready),
    .out_last(b_out_last),
    .out_error(b_out_error),
    .out_tag(b_out_tag),
    .out_index(b_out_index),
    .out_count(b_out_count),
    .out_activation(b_out_activation),
    .out_exponent(b_out_exponent),
    .out_outlier_mask(b_out_outlier_mask),
    .out_outlier_negative(b_out_outlier_negative),
    .out_normalized_negative(b_out_normalized_negative),
    .req_valid(b_req_valid),
    .req_ready(b_req_ready),
    .req_address(b_req_address),
    .req_length(b_req_length),
    .rsp_valid(b_rsp_valid),
    .rsp_ready(b_rsp_ready),
    .rsp_last(b_rsp_last),
    .rsp_error(b_rsp_error),
    .rsp_data(b_rsp_data),
    .port_idle(b_port_idle),
    .idle(b_idle),
    .row_fault(b_row_fault),
    .done_valid(b_done_valid),
    .done_ready(b_done_ready),
    .done_error(b_done_error),
    .done_tag(b_done_tag)
  );
  assign m_cfg_ready=unit_mode==0 ? a_cfg_ready : b_cfg_ready;
  assign m_req_valid=unit_mode==0 ? a_req_valid : b_req_valid;
  assign m_req_address=unit_mode==0 ? a_req_address : b_req_address;
  assign m_req_length=unit_mode==0 ? a_req_length : b_req_length;
  assign m_rsp_ready=unit_mode==0 ? a_rsp_ready : b_rsp_ready;
  assign m_port_idle=unit_mode==0 ? a_port_idle : b_port_idle;
  assign m_idle=unit_mode==0 ? a_idle : b_idle;
  assign m_row_fault=unit_mode==0 ? a_row_fault : b_row_fault;
  assign m_done_valid=unit_mode==0 ? a_done_valid : b_done_valid;
  assign m_done_error=unit_mode==0 ? a_done_error : b_done_error;
  assign m_done_tag=unit_mode==0 ? a_done_tag : b_done_tag;
  assign m_stats_valid=unit_mode==0 ? a_stats_valid : dut_b.reader.stats_valid;
  assign m_stats_ready=unit_mode==0 ? a_stats_ready : dut_b.reader.stats_ready;
  assign m_replay_valid=unit_mode==0 ? a_replay_valid : dut_b.reader.replay_valid;
  assign m_replay_ready=unit_mode==0 ? a_replay_ready : dut_b.reader.replay_ready;
  always #5 clk=~clk;

  function automatic logic [255:0] raw_at(input int index);
    logic [255:0] value;
    if(unit_mode==1) return raw_words[row_offsets[active_source]+index];
    value=0;
    for(int lane=0;lane<8;lane++) value[lane*32+:32]=32'h81234567 ^ (32'(index*8+lane)*32'h01020305);
    return value;
  endfunction
  function automatic logic [191:0] gain_at(input int index);
    logic [191:0] value;
    if(unit_mode==1) return gain_words[row_offsets[active_source]+index];
    value=0;
    for(int lane=0;lane<8;lane++) value[lane*24+:24]=24'h800001 ^ (24'(index*8+lane)*24'h031703);
    return value;
  endfunction
  function automatic logic [63:0] memory_word(input logic [63:0] address,input int beat);
    logic [63:0] delta;
    logic [255:0] raw;
    logic [191:0] gain;
    if(address>=cfg_raw_base && address-cfg_raw_base<64'(cfg_strips)*32)begin
      delta=address-cfg_raw_base;raw=raw_at(int'(delta/32));
      if(malformed==4 && requests>2*int'(cfg_strips) && delta==0)raw[0]=~raw[0];
      if(beat<4)return raw[beat*64+:64];
      return 64'hbad04bad04bad04b;
    end
    if(address>=cfg_gamma_base && address-cfg_gamma_base<64'(cfg_strips)*24)begin
      delta=address-cfg_gamma_base;gain=gain_at(int'(delta/24));
      if(beat<3)return gain[beat*64+:64];
      return 64'hbad03bad03bad03b;
    end
    $fatal(1,"R32_MEMORY_OUTSIDE_ALLOCATION");
    return 0;
  endfunction

  // The endpoint owns at most one burst. Response creation occurs on the
  // negative edge AFTER request acceptance, never on its acceptance edge.
  always @(negedge clk)begin
    if(!rst_n)begin
      req_ready=0;rsp_valid=0;rsp_last=0;rsp_error=0;rsp_data=0;
      stats_ready=0;replay_ready=0;out_ready=0;
    end else begin
      req_ready=!force_req_stall && cycle%7!=1;
      stats_ready=!force_stream_stall && cycle%11!=3;
      replay_ready=!force_stream_stall && cycle%13!=4;
      out_ready=!force_out_stall && !(cycle%11>=2 && cycle%11<=4);
      if(unsolicited || (zero_latency && m_req_valid && req_ready && !pending))begin
        rsp_valid=1;rsp_last=1;rsp_error=0;rsp_data=64'hdecafbad12345678;
      end else if(rsp_valid && !response_retired)begin
        // Retain an offered legitimate response until accepted.
      end else if(pending && cycle%5!=1)begin
        rsp_valid=1;rsp_last=memory_beat==actual_length-1;
        rsp_error=(malformed==3 && memory_beat==0);
        rsp_data=memory_word(memory_address,memory_beat);
      end else begin
        rsp_valid=0;rsp_last=0;rsp_error=0;rsp_data=0;
      end
    end
  end
  always @(posedge clk)begin
    cycle++;
    if(cycle>1000000)$fatal(1,"R32_GLOBAL_WATCHDOG");
    response_retired=rsp_valid&&m_rsp_ready;
    if(!rst_n)begin
      response_retired=0;pending=0;memory_address=0;memory_length=0;memory_beat=0;actual_length=0;
      requests=0;responses=0;stats=0;replays=0;outputs=0;dones=0;configs=0;
      req_held=0;stats_held=0;replay_held=0;out_held=0;done_held=0;
    end else if(log_active)begin
      if(req_held && (!m_req_valid || {m_req_address,m_req_length}!==req_payload))$fatal(1,"R32_REQUEST_WITHDRAWN");
      req_held=m_req_valid&&!req_ready;req_payload={m_req_address,m_req_length};
      if(unit_mode==0)begin
        if(stats_held && !(clear_valid&&a_clear_ready) && (!a_stats_valid || {a_stats_last,a_stats_data,a_stats_gamma}!==stats_payload))$fatal(1,"R32_STATS_WITHDRAWN");
        if(replay_held && !(clear_valid&&a_clear_ready) && (!a_replay_valid || {a_replay_last,a_replay_data,a_replay_gamma}!==replay_payload))$fatal(1,"R32_REPLAY_WITHDRAWN");
        stats_held=a_stats_valid&&!stats_ready&&!(clear_valid&&a_clear_ready);stats_payload={a_stats_last,a_stats_data,a_stats_gamma};
        replay_held=a_replay_valid&&!replay_ready&&!(clear_valid&&a_clear_ready);replay_payload={a_replay_last,a_replay_data,a_replay_gamma};
      end else begin
        if(out_held && (!b_out_valid || {b_out_last,b_out_error,b_out_tag,b_out_index,b_out_count,b_out_activation,b_out_exponent,b_out_outlier_mask,b_out_outlier_negative,b_out_normalized_negative}!==out_payload))$fatal(1,"R32_OUTPUT_WITHDRAWN");
        out_held=b_out_valid&&!out_ready;
        out_payload={b_out_last,b_out_error,b_out_tag,b_out_index,b_out_count,b_out_activation,b_out_exponent,b_out_outlier_mask,b_out_outlier_negative,b_out_normalized_negative};
        if(b_out_valid&&out_ready)begin
          if(b_out_error)$fatal(1,"R32_PUBLIC_CORE_ERROR");
          if(check_outputs)begin
            if(outputs>=int'(cfg_strips)||b_out_tag!==cfg_tag||b_out_index!==10'(outputs)||b_out_count!==4'd8||b_out_last!==(outputs==int'(cfg_strips)-1)||b_out_exponent!==row_out_exponent[active_source])$fatal(1,"R32_OUTPUT_METADATA");
            if(b_out_activation!==activation_words[row_offsets[active_source]+outputs]||b_out_normalized_negative!==sign_words[row_offsets[active_source]+outputs]||b_out_outlier_mask!==outlier_words[row_offsets[active_source]+outputs]||b_out_outlier_negative!==outlier_negative_words[row_offsets[active_source]+outputs])$fatal(1,"R32_OUTPUT_DATA");
          end
          outputs++;
        end
      end
      if(done_held && (!m_done_valid || {m_done_error,m_done_tag}!==done_payload))$fatal(1,"R32_DONE_CHANGED");
      done_held=m_done_valid&&!done_ready;done_payload={m_done_error,m_done_tag};
      if(cfg_valid&&m_cfg_ready)configs++;
      if(m_done_valid&&done_ready)dones++;
      if(m_stats_valid&&m_stats_ready)stats++;
      if(m_replay_valid&&m_replay_ready)replays++;
      if(rsp_valid&&m_rsp_ready)begin
        responses++;
        if(pending)begin
          memory_beat++;
          if(rsp_last)pending=0;
        end
      end
      if(m_req_valid&&req_ready)begin
        if(pending)$fatal(1,"R32_ENDPOINT_OVERLAPPING_REQUEST");
        memory_address=m_req_address;memory_length=int'(m_req_length);memory_beat=0;
        actual_length=(malformed==1)?1:(malformed==2)?memory_length+2:memory_length;
        pending=1;requests++;
      end
    end
  end

  task automatic ticks(input int count);
    repeat(count)@(negedge clk);
  endtask
  task automatic begin_case(input int id,input int which,input int source);
    @(negedge clk);log_active=0;rst_n=0;
    unit_mode=which;case_id=id;active_source=source;
    cfg_valid=0;abort_valid=0;clear_valid=0;done_ready=0;
    force_req_stall=0;force_stream_stall=0;force_out_stall=0;
    malformed=0;unsolicited=0;zero_latency=0;check_outputs=0;
    cfg_tag=32'h52320000+32'(id);cfg_strips=1;
    cfg_raw_base=64'h10000008;cfg_gamma_base=64'h30000008;
    cfg_epsilon_q16=1;cfg_gamma_exponent=0;
    if(which==1)begin
      cfg_tag=row_tags[source];cfg_strips=row_strips[source];
      cfg_epsilon_q16=row_epsilon[source];cfg_gamma_exponent=row_gamma_exponent[source];
    end
    log_active=1;
    $display("R32_BEGIN case=%0d unit=%s",id,(which==0)?"A":"B");
    ticks(4);rst_n=1;ticks(1);
  endtask
  task automatic configure_row;
    @(negedge clk);cfg_valid=1;
    do @(posedge clk);while(!m_cfg_ready);
    @(negedge clk);cfg_valid=0;
  endtask
  task automatic await_done(input bit error_expected);
    int wait_cycles;
    wait_cycles=0;
    while(!m_done_valid)begin
      @(negedge clk);wait_cycles++;
      if(wait_cycles>200000)$fatal(1,"R32_DONE_TIMEOUT case=%0d",case_id);
    end
    if(m_done_error!==error_expected || m_done_tag!==cfg_tag)$fatal(1,"R32_BAD_DONE case=%0d",case_id);
    ticks(5);
    @(negedge clk);abort_valid=0;done_ready=1;
    @(posedge clk);
    @(negedge clk);done_ready=0;
    wait_cycles=0;
    while(!m_idle)begin
      @(negedge clk);wait_cycles++;
      if(wait_cycles>100)$fatal(1,"R32_IDLE_TIMEOUT case=%0d",case_id);
    end
  endtask
  task automatic end_case;
    ticks(6);
    $display("R32_END case=%0d requests=%0d responses=%0d stats=%0d replay=%0d outputs=%0d done=%0d",case_id,requests,responses,stats,replays,outputs,dones);
    log_active=0;
  endtask
  task automatic healthy(input int id,input int which,input int source,input int count,input int top);
    begin_case(id,which,source);
    if(which==0)cfg_strips=10'(count);
    check_outputs=which==1;
    if(top==1)cfg_raw_base=64'hffffffffffffffff-(64'(cfg_strips)*32-1);
    if(top==2)cfg_gamma_base=64'hffffffffffffffff-(64'(cfg_strips)*24-1);
    configure_row;await_done(0);
    if(requests!=4*int'(cfg_strips)||responses!=14*int'(cfg_strips)||stats!=int'(cfg_strips)||replays!=int'(cfg_strips)||dones!=1||(which==1&&outputs!=int'(cfg_strips)))$fatal(1,"R32_HEALTHY_COUNTS");
    end_case;
  endtask
  task automatic invalid_config(input int id,input int which,input int kind);
    begin_case(id,which,8);
    case(kind)
      0:cfg_strips=0;
      1:cfg_strips=513;
      2:cfg_raw_base=cfg_raw_base+1;
      3:cfg_gamma_base=cfg_gamma_base+1;
      4:begin cfg_strips=2;cfg_raw_base=64'hffffffffffffffe0;end
      5:begin cfg_strips=2;cfg_gamma_base=64'hffffffffffffffe8;end
    endcase
    configure_row;await_done(1);
    if(requests!=0||responses!=0||outputs!=0)$fatal(1,"R32_INVALID_CONFIG_READ");
    end_case;
  endtask
  task automatic memory_fault(input int id,input int which,input int kind);
    begin_case(id,which,8);malformed=kind;
    configure_row;await_done(1);
    if(requests!=1||responses!=((kind==1)?1:(kind==2)?6:4)||stats!=0||replays!=0||outputs!=0)$fatal(1,"R32_MEMORY_FAULT_COUNTS");
    end_case;
  endtask
  task automatic abort_request(input int id,input int which);
    begin_case(id,which,8);force_req_stall=1;configure_row;
    while(!m_req_valid)@(negedge clk);
    abort_valid=1;ticks(5);force_req_stall=0;
    await_done(1);
    if(requests!=1||responses!=4||stats!=0||replays!=0||outputs!=0)$fatal(1,"R32_ABORT_REQUEST_COUNTS");
    end_case;
  endtask
  task automatic abort_read(input int id,input int which);
    begin_case(id,which,8);configure_row;
    while(responses<1)@(negedge clk);
    abort_valid=1;await_done(1);
    if(requests!=1||responses!=4||stats!=0||replays!=0||outputs!=0)$fatal(1,"R32_ABORT_READ_COUNTS");
    end_case;
  endtask
  task automatic abort_pair(input int id,input bit replay_pass,input bit private_clear);
    begin_case(id,0,0);force_stream_stall=!replay_pass;configure_row;
    if(replay_pass)begin
      while(stats!=1)@(negedge clk);
      force_stream_stall=1;
      while(!a_replay_valid)@(negedge clk);
    end else while(!a_stats_valid)@(negedge clk);
    abort_valid=1;ticks(5);
    if(!a_port_idle||a_idle)$fatal(1,"R32_HELD_PAIR_IDLE");
    if(private_clear)begin
      if(!a_clear_ready)$fatal(1,"R32_CLEAR_NOT_READY");
      clear_valid=1;@(posedge clk);@(negedge clk);clear_valid=0;
    end else force_stream_stall=0;
    await_done(1);end_case;
  endtask
  task automatic quarantined(input int id,input int which,input int kind);
    begin_case(id,which,8);
    if(kind==1)begin force_req_stall=1;configure_row;while(!m_req_valid)@(negedge clk);end
    if(kind==2)begin zero_latency=1;configure_row;end
    else unsolicited=1;
    ticks(5);
    if(!m_row_fault||m_port_idle||m_idle||m_cfg_ready)$fatal(1,"R32_QUARANTINE_NOT_HELD");
    if(kind==1)begin force_req_stall=0;ticks(7);end
    unsolicited=0;zero_latency=0;ticks(5);
    if(!m_row_fault||m_port_idle||m_idle||m_cfg_ready)$fatal(1,"R32_QUARANTINE_REPAIRED_BY_LAST");
    end_case;
  endtask
  task automatic late_done_fault(input int id,input int which);
    begin_case(id,which,8);configure_row;
    while(!m_done_valid)@(negedge clk);
    if(m_done_error)$fatal(1,"R32_EXPECTED_HELD_SUCCESS");
    ticks(2);
    unsolicited=1;ticks(5);
    if(!m_done_valid||m_done_error||!m_row_fault||m_port_idle||m_cfg_ready)$fatal(1,"R32_LATE_DONE_FAULT");
    unsolicited=0;end_case;
  endtask
  task automatic wrapper_abort(input int id,input int kind);
    begin_case(id,1,(kind==2)?8:0);
    if(kind!=0 && kind!=4)force_out_stall=1;
    configure_row;
    case(kind)
      0:begin
        while(stats!=int'(cfg_strips))@(negedge clk);
        if(dut_b.normalizer.base.state!==4'd2)$fatal(1,"R32_CORE_NOT_SCALE");
      end
      1,2:while(!b_out_valid)@(negedge clk);
      3:begin
        while(!b_out_valid)@(negedge clk);
        while(!dut_b.normalizer.out_valid)@(negedge clk);
        while(!dut_b.reader.replay_valid || dut_b.reader.replay_ready)@(negedge clk);
        if(dut_b.normalizer.base.state!==4'd5)$fatal(1,"R32_CORE_NOT_LATENT_OUTPUT");
      end
      4:begin
        while(replays<1)@(negedge clk);
        if(dut_b.normalizer.base.state!==4'd4 || dut_b.normalizer.out_valid)$fatal(1,"R32_CORE_NOT_SEARCH");
      end
    endcase
    abort_valid=1;ticks(5);force_out_stall=0;
    await_done(1);end_case;
  endtask
  task automatic wrapper_replay_error(input int id);
    begin_case(id,1,8);malformed=4;configure_row;await_done(1);
    if(outputs!=0||requests!=4||responses!=14||stats!=1||replays!=1)$fatal(1,"R32_CORE_ERROR_COMPLETION");
    end_case;
  endtask
  task automatic coupled_reset(input int id,input int which,input int kind);
    begin_case(id,which,0);
    if(kind==1)begin force_stream_stall=1;force_out_stall=1;end
    configure_row;
    if(kind==0)while(responses<1)@(negedge clk);
    else if(which==0)while(!a_stats_valid)@(negedge clk);
    else while(!b_out_valid)@(negedge clk);
    if(kind==1)ticks(2);
    rst_n=0;ticks(4);rst_n=1;ticks(3);
    if(!m_idle||!m_port_idle||m_done_valid||m_row_fault||m_req_valid)$fatal(1,"R32_COUPLED_RESET_INCOMPLETE");
    end_case;
  endtask
  always @(posedge clk) if(log_active && unit_mode==0)
    $display("R32_C case=%0d cycle=%0d unit=A in=%062h out=%0253h aux=%01h",case_id,($time+5)/10,{a_rst_n,a_cfg_valid,a_cfg_tag,a_cfg_strips,a_cfg_raw_base,a_cfg_gamma_base,a_abort_valid,a_stats_ready,a_replay_ready,a_req_ready,a_rsp_valid,a_rsp_last,a_rsp_error,a_rsp_data,a_done_ready,a_clear_valid},{a_cfg_ready,a_stats_valid,a_stats_last,a_stats_data,a_stats_gamma,a_replay_valid,a_replay_last,a_replay_data,a_replay_gamma,a_req_valid,a_req_address,a_req_length,a_rsp_ready,a_port_idle,a_idle,a_row_fault,a_done_valid,a_done_error,a_done_tag,a_clear_ready},1'b0);
  always @(posedge clk) if(log_active && unit_mode==1)
    $display("R32_C case=%0d cycle=%0d unit=B in=%079h out=%064h aux=%0316h",case_id,($time+5)/10,{b_rst_n,b_cfg_valid,b_cfg_tag,b_cfg_strips,b_cfg_raw_base,b_cfg_gamma_base,b_abort_valid,b_cfg_epsilon_q16,b_cfg_gamma_exponent,b_out_ready,b_req_ready,b_rsp_valid,b_rsp_last,b_rsp_error,b_rsp_data,b_done_ready},{b_cfg_ready,b_out_valid,b_out_last,b_out_error,b_out_tag,b_out_index,b_out_count,b_out_activation,b_out_exponent,b_out_outlier_mask,b_out_outlier_negative,b_out_normalized_negative,b_req_valid,b_req_address,b_req_length,b_rsp_ready,b_port_idle,b_idle,b_row_fault,b_done_valid,b_done_error,b_done_tag},{dut_b.normalizer.rst_n,dut_b.normalizer.cfg_ready,dut_b.normalizer.out_valid,dut_b.normalizer.base.state,dut_b.normalizer.out_ready,dut_b.normalizer.out_error,dut_b.reader.rst_n,dut_b.reader.cfg_valid,dut_b.reader.cfg_ready,dut_b.reader.cfg_tag,dut_b.reader.cfg_strips,dut_b.reader.cfg_raw_base,dut_b.reader.cfg_gamma_base,dut_b.reader.abort_valid,dut_b.reader.stats_valid,dut_b.reader.stats_ready,dut_b.reader.stats_last,dut_b.reader.stats_data,dut_b.reader.stats_gamma,dut_b.reader.replay_valid,dut_b.reader.replay_ready,dut_b.reader.replay_last,dut_b.reader.replay_data,dut_b.reader.replay_gamma,dut_b.reader.req_valid,dut_b.reader.req_ready,dut_b.reader.req_address,dut_b.reader.req_length,dut_b.reader.rsp_valid,dut_b.reader.rsp_ready,dut_b.reader.rsp_last,dut_b.reader.rsp_error,dut_b.reader.rsp_data,dut_b.reader.port_idle,dut_b.reader.idle,dut_b.reader.row_fault,dut_b.reader.done_valid,dut_b.reader.done_ready,dut_b.reader.done_error,dut_b.reader.done_tag,dut_b.reader.clear_valid,dut_b.reader.clear_ready});
  initial begin
    if(!$value$plusargs("RAW32_ROOT=%s",data_root))$fatal(1,"R32_ROOT_REQUIRED");
    $readmemh({data_root,"/data/raw_words.hex"},raw_words);
    $readmemh({data_root,"/data/gain_words.hex"},gain_words);
    $readmemh({data_root,"/data/activation_words.hex"},activation_words);
    $readmemh({data_root,"/data/sign_words.hex"},sign_words);
    $readmemh({data_root,"/data/outlier_words.hex"},outlier_words);
    $readmemh({data_root,"/data/outlier_negative_words.hex"},outlier_negative_words);
    $readmemh({data_root,"/data/row_offsets.hex"},row_offsets);
    $readmemh({data_root,"/data/row_tags.hex"},row_tags);
    $readmemh({data_root,"/data/row_strips.hex"},row_strips);
    $readmemh({data_root,"/data/row_epsilon.hex"},row_epsilon);
    $readmemh({data_root,"/data/row_gamma_exponent.hex"},row_gamma_exponent);
    $readmemh({data_root,"/data/row_out_exponent.hex"},row_out_exponent);
    healthy(0,0,0,1,0);
    healthy(1,0,0,256,0);
    healthy(2,0,0,512,0);
    healthy(3,0,0,1,1);
    healthy(4,0,0,512,2);
    invalid_config(5,0,0);
    invalid_config(6,0,1);
    invalid_config(7,0,2);
    invalid_config(8,0,3);
    invalid_config(9,0,4);
    invalid_config(10,0,5);
    abort_request(11,0);
    abort_read(12,0);
    abort_pair(13,0,0);
    abort_pair(14,1,0);
    memory_fault(15,0,1);
    memory_fault(16,0,2);
    memory_fault(17,0,3);
    quarantined(18,0,0);
    quarantined(19,0,1);
    quarantined(20,0,2);
    late_done_fault(21,0);
    coupled_reset(22,0,0);
    coupled_reset(23,0,1);
    abort_pair(24,0,1);
    abort_pair(25,1,1);
    healthy(26,1,0,0,0);
    healthy(27,1,1,0,0);
    healthy(28,1,2,0,0);
    healthy(29,1,3,0,0);
    healthy(30,1,4,0,0);
    healthy(31,1,5,0,0);
    healthy(32,1,6,0,0);
    healthy(33,1,7,0,0);
    healthy(34,1,8,0,0);
    invalid_config(35,1,0);
    invalid_config(36,1,1);
    invalid_config(37,1,2);
    invalid_config(38,1,3);
    invalid_config(39,1,4);
    invalid_config(40,1,5);
    abort_request(41,1);
    abort_read(42,1);
    wrapper_abort(43,0);
    wrapper_abort(44,1);
    wrapper_abort(45,2);
    wrapper_abort(46,3);
    wrapper_abort(47,4);
    wrapper_replay_error(48);
    memory_fault(49,1,1);
    memory_fault(50,1,2);
    memory_fault(51,1,3);
    quarantined(52,1,0);
    quarantined(53,1,1);
    quarantined(54,1,2);
    late_done_fault(55,1);
    coupled_reset(56,1,0);
    coupled_reset(57,1,1);
    $display("R32_PASS cases=58");
    $finish;
  end
endmodule
