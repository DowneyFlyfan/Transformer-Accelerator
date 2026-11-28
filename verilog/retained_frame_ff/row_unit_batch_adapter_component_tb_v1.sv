`timescale 1ns/1ps
// Component regression only. Size and descriptor memory are explicit mocks.
// There is no physical C, real owner, full-frame counter or trained arithmetic.
module row_unit_batch_adapter_component_tb_v1;
  import tri_oracle_FF_frame_types_v2::*;
  localparam logic [31:0] TAG_BASE=32'h504f0000;
  logic clk,rst_n,abort_valid,owner_held;
  logic cfg_valid,cfg_ready;
  frame_t cfg_frame;
  logic [9:0] cfg_batch_start;
  logic [4:0] cfg_batch_tokens;
  logic [31:0] cfg_batch_tag;
  logic root_valid,root_last,root_ready;
  logic [9:0] root_origin,root_count;
  logic next_req_valid,next_req_write,next_req_ready;
  logic [9:0] next_req_word;
  logic [63:0] next_req_data;
  logic next_rsp_valid,next_rsp_error,next_rsp_ready;
  logic [63:0] next_rsp_data;
  logic batch_valid,batch_ready,epoch_fault,idle,port_idle;
  batch_t batch_context;
  integer case_id,cases_passed;
  integer cfg_acks,root_acks,request_acks,response_acks,batch_acks;
  integer active_start,active_tokens;
  logic prior_request_hold,prior_batch_hold;
  logic [74:0] prior_request_tuple;
  batch_t prior_batch_tuple;

  tri_oracle_row_unit_batch_adapter_v1 dut (
    .clk,.rst_n,.abort_valid,.owner_held,.cfg_valid,.cfg_ready,.cfg_frame,
    .cfg_batch_start,.cfg_batch_tokens,.cfg_batch_tag,
    .root_valid,.root_last,.root_origin,.root_count,.root_ready,
    .next_req_valid,.next_req_write,.next_req_ready,.next_req_word,.next_req_data,
    .next_rsp_valid,.next_rsp_error,.next_rsp_data,.next_rsp_ready,
    .batch_valid,.batch_ready,.batch_context,.epoch_fault,.idle,.port_idle
  );

  task automatic check(input logic condition,input string reason);
    if(condition!==1'b1)$fatal(1,"BATCH_ADAPTER_COMPONENT_FAIL case=%0d reason=%s",case_id,reason);
  endtask
  // Independent declared fixture: archive rank, upstream raw rank and canonical
  // root deliberately differ. No expected tuple is read from DUT internals.
  function automatic integer fixture_root(input integer start_rank,slot);
    return start_rank>=256 ? 500+5*slot : 11+3*slot;
  endfunction
  function automatic integer fixture_upstream(input integer start_rank,slot);
    return start_rank>=256 ? 200+3*slot : 30+2*slot;
  endfunction
  function automatic integer fixture_unit(input integer slot);
    if(slot==0)return -256;
    if(slot==1)return 255;
    return slot-11;
  endfunction
  function automatic frame_t fixture_frame();
    frame_t frame;
    frame='0;
    frame.common.source_tag=TAG_BASE;
    frame.common.source_layer=1;
    frame.common.source_epoch=2;
    frame.common.image_start=5;
    frame.common.input_count=264;
    frame.common.kept_count=264;
    frame.common.phase=1;
    frame.common.normalization_role=1;
    frame.upstream_input_count=576;
    return frame;
  endfunction
  function automatic logic [63:0] fixture_descriptor(input integer start_rank,slot);
    logic [8:0] unit_bits;
    logic [9:0] rank_bits,root_bits;
    logic [31:0] tag_bits;
    unit_bits=9'(fixture_unit(slot));rank_bits=10'(start_rank+slot);
    root_bits=10'(fixture_root(start_rank,slot));
    tag_bits=TAG_BASE+32'(fixture_upstream(start_rank,slot));
    return {3'b010,unit_bits,rank_bits,root_bits,tag_bits};
  endfunction
  function automatic batch_t expected_batch(input integer start_rank,tokens,input logic [31:0] tag);
    batch_t expected;
    expected='0;expected.tag=tag;expected.start_rank=10'(start_rank);expected.tokens=5'(tokens);
    for(integer slot=0;slot<16;slot++)if(slot<tokens)begin
      expected.rows[slot].source_tag=TAG_BASE+32'(fixture_upstream(start_rank,slot));
      expected.rows[slot].frame_rank=10'(start_rank+slot);
      expected.rows[slot].original_root=10'(fixture_root(start_rank,slot));
      expected.rows[slot].upstream_input_rank=10'(fixture_upstream(start_rank,slot));
      expected.rows[slot].raw_input_rank=10'(fixture_upstream(start_rank,slot));
      expected.rows[slot].activation_unit=9'(fixture_unit(slot));
    end
    return expected;
  endfunction

  // Counts are real public ready/valid handshakes, not supplied DUT counters.
  // A pending request/batch is irrevocable across ready stalls and late poison.
  always @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      cfg_acks=0;root_acks=0;request_acks=0;response_acks=0;batch_acks=0;
      prior_request_hold=0;prior_batch_hold=0;prior_request_tuple=0;prior_batch_tuple='0;
    end else begin
      check(!$isunknown({cfg_ready,root_ready,next_req_valid,next_rsp_ready,batch_valid,epoch_fault,idle,port_idle}),"KNOWN_PUBLIC_CONTROL");
      if(prior_request_hold)check(next_req_valid===1'b1 &&
        {next_req_write,next_req_word,next_req_data}===prior_request_tuple,"HELD_REQUEST_CHANGED");
      if(prior_batch_hold)check(batch_valid===1'b1 && batch_context===prior_batch_tuple,"HELD_BATCH_CHANGED");
      if(cfg_valid===1'b1 && cfg_ready===1'b1)cfg_acks=cfg_acks+1;
      if(root_valid===1'b1 && root_ready===1'b1)root_acks=root_acks+1;
      if(next_req_valid===1'b1 && next_req_ready===1'b1)begin
        check(next_req_write===1'b0 && next_req_data===64'd0 &&
          next_req_word===10'(256+active_start+request_acks),"EXACT_DESCRIPTOR_WORD_ORDER");
        request_acks=request_acks+1;
      end
      if(next_rsp_valid===1'b1 && next_rsp_ready===1'b1)response_acks=response_acks+1;
      if(batch_valid===1'b1 && batch_ready===1'b1)batch_acks=batch_acks+1;
      prior_request_hold=next_req_valid===1'b1 && next_req_ready!==1'b1;
      prior_request_tuple={next_req_write,next_req_word,next_req_data};
      prior_batch_hold=batch_valid===1'b1 && batch_ready!==1'b1;
      prior_batch_tuple=batch_context;
    end
  end

  task automatic reset_case(input integer number);
    @(negedge clk);rst_n=0;case_id=number;
    cfg_valid=0;cfg_frame=fixture_frame();cfg_batch_start=0;cfg_batch_tokens=1;cfg_batch_tag=32'hba7c0000+32'(number);
    root_valid=0;root_last=0;root_origin=0;root_count=0;
    next_req_ready=0;next_rsp_valid=0;next_rsp_error=0;next_rsp_data=0;batch_ready=0;
    owner_held=1;abort_valid=0;active_start=0;active_tokens=1;
    repeat(3)@(negedge clk);rst_n=1;
    repeat(2)@(negedge clk);
    check(cfg_ready===1'b1 && epoch_fault===1'b0,"RESET_COUPLED_UNIT_READY");
  endtask
  task automatic send_configuration(input integer start_rank,tokens);
    @(negedge clk);active_start=start_rank;active_tokens=tokens;
    cfg_batch_start=10'(start_rank);cfg_batch_tokens=5'(tokens);cfg_valid=1;
    check(cfg_ready===1'b1,"CONFIGURATION_READY");
    @(posedge clk);#1ps;
    check(cfg_acks==1,"ONE_CONFIGURATION_ACK");
    @(negedge clk);cfg_valid=0;
  endtask
  task automatic send_root(input integer slot,input integer corrupt);
    integer waits;
    @(negedge clk);root_valid=1;root_origin=10'(fixture_root(active_start,slot));
    root_count=10'(slot+1);root_last=(active_start+slot==263);
    if(corrupt==1)root_count=0;
    if(corrupt==2)root_last=!root_last;
    waits=0;
    while(root_ready!==1'b1)begin @(negedge clk);waits=waits+1;check(waits<100,"ROOT_READY_TIMEOUT");end
    @(posedge clk);#1ps;
    check(root_acks==slot+1,"EXACT_ROOT_ACK_COUNT");
    @(negedge clk);root_valid=0;
  endtask
  task automatic accept_request(input integer stall_cycles);
    integer waits,prior;
    logic [74:0] held;
    waits=0;
    while(next_req_valid!==1'b1)begin @(negedge clk);waits=waits+1;check(waits<100,"REQUEST_OFFER_TIMEOUT");end
    held={next_req_write,next_req_word,next_req_data};prior=request_acks;
    repeat(stall_cycles)begin @(posedge clk);#1ps;
      check(next_req_valid===1'b1 && {next_req_write,next_req_word,next_req_data}===held &&
        request_acks==prior,"REQUEST_STALL_STABLE_UNACCEPTED");
    end
    @(negedge clk);next_req_ready=1;
    @(posedge clk);#1ps;check(request_acks==prior+1,"ONE_REQUEST_ACK");
    @(negedge clk);next_req_ready=0;
  endtask
  task automatic send_response(input integer slot,input integer corrupt,input logic error_bit);
    logic [63:0] value;
    integer prior;
    value=fixture_descriptor(active_start,slot);
    case(corrupt)
      1:value[63:61]=3'b011;
      2:value[51:42]=10'(active_start+slot+1);
      3:value[41:32]=10'(fixture_root(active_start,slot)+1);
      4:value[31:0]=TAG_BASE-32'd1;
      5:value[31:0]=TAG_BASE+32'd264;
      default:begin end
    endcase
    prior=response_acks;
    // The endpoint delays valid while the real accepted request remains owned.
    repeat(2)begin @(posedge clk);#1ps;
      check(next_rsp_ready===1'b1 && next_req_valid===1'b0 &&
        response_acks==prior && batch_valid===1'b0,"OWNED_RESPONSE_LATENCY");
    end
    @(negedge clk);next_rsp_data=value;next_rsp_error=error_bit;next_rsp_valid=1;
    #1ps;check(next_rsp_ready===1'b1,"KNOWN_OWNED_RESPONSE_DRAINS");
    @(posedge clk);#1ps;check(response_acks==prior+1,"ONE_RESPONSE_ACK");
    @(negedge clk);next_rsp_valid=0;next_rsp_error=0;next_rsp_data=0;
  endtask
  task automatic collect_good_rows(input integer tokens);
    for(integer slot=0;slot<tokens;slot++)begin
      send_root(slot,0);accept_request(slot%4+1);send_response(slot,0,1'b0);
    end
  endtask
  task automatic check_sticky(input integer reqs,rsps,batches);
    repeat(5)begin @(posedge clk);#1ps;
      check(epoch_fault===1'b1 && cfg_ready===1'b0 && idle===1'b0,"KNOWN_STICKY_FAULT");
      check(request_acks==reqs && response_acks==rsps && batch_acks==batches,"FAULT_NO_EXTRA_ACK");
    end
  endtask
  task automatic pass_case(input string name);
    cases_passed=cases_passed+1;
    $display("BATCH_ADAPTER_COMPONENT_CASE_PASS case=%0d name=%s cfg=%0d roots=%0d requests=%0d responses=%0d batches=%0d mocked_endpoints=1 full_owner_verified=0",
      case_id,name,cfg_acks,root_acks,request_acks,response_acks,batch_acks);
  endtask
  task automatic healthy_batch(input integer number,start_rank,tokens);
    batch_t expected;
    reset_case(number);send_configuration(start_rank,tokens);collect_good_rows(tokens);
    expected=expected_batch(start_rank,tokens,cfg_batch_tag);
    #1ps;check(batch_valid===1'b1 && batch_context===expected,"FULL_BATCH_CONTEXT_AND_ZERO_UNUSED_ROWS");
    repeat(7)begin @(posedge clk);#1ps;
      check(batch_valid===1'b1 && batch_context===expected && batch_acks==0 && epoch_fault===1'b0,"BATCH_STALL_STABLE");
    end
    @(negedge clk);batch_ready=1;
    @(posedge clk);#1ps;
    check(root_acks==tokens && request_acks==tokens && response_acks==tokens && batch_acks==1,"EXACT_B_REAL_ACKS");
    @(negedge clk);batch_ready=0;
    #1ps;check(idle===1'b1 && epoch_fault===1'b0 && port_idle===1'b1,"HEALTHY_COMPONENT_RETURN_IDLE");
    pass_case(tokens==16 ? "B16_DISTINCT_DOMAINS" : "B8_FINAL_TAIL");
  endtask
  task automatic bad_descriptor(input integer number,corrupt,input logic error_bit);
    reset_case(number);send_configuration(0,1);send_root(0,0);accept_request(2);
    send_response(0,corrupt,error_bit);check_sticky(1,1,0);
    check(batch_valid===1'b0 && next_req_valid===1'b0 && port_idle===1'b1,"BAD_DESCRIPTOR_STOPPED_AFTER_DRAIN");
    pass_case("BAD_DESCRIPTOR_OR_ERROR");
  endtask
  task automatic bad_configuration(input integer number,start_rank,tokens);
    reset_case(number);send_configuration(start_rank,tokens);check_sticky(0,0,0);
    check(root_ready===1'b0 && next_req_valid===1'b0 && batch_valid===1'b0,"BAD_BATCH_EXTENT_FENCED");
    pass_case("BAD_BATCH_EXTENT");
  endtask
  task automatic bad_root(input integer number,corrupt);
    reset_case(number);send_configuration(0,1);send_root(0,corrupt);check_sticky(0,0,0);
    check(next_req_valid===1'b0 && batch_valid===1'b0,"BAD_SIZE_TUPLE_FENCED");pass_case("BAD_SIZE_TUPLE");
  endtask
  task automatic held_request_poison(input integer number,input logic lose_owner);
    logic [74:0] held;
    reset_case(number);send_configuration(0,1);send_root(0,0);
    #1ps;check(next_req_valid===1'b1,"REQUEST_EXPOSED_BEFORE_POISON");
    held={next_req_write,next_req_word,next_req_data};
    @(negedge clk);if(lose_owner)owner_held=0;else abort_valid=1;
    repeat(4)begin @(posedge clk);#1ps;
      check(epoch_fault===1'b1 && next_req_valid===1'b1 &&
        {next_req_write,next_req_word,next_req_data}===held && request_acks==0,"POISON_RETAINS_REQUEST");
    end
    @(negedge clk);owner_held=1;abort_valid=0;
    accept_request(2);send_response(0,0,1'b0);check_sticky(1,1,0);
    check(batch_valid===1'b0 && port_idle===1'b1,"POISON_KNOWN_RESPONSE_DRAIN_ONLY");pass_case("HELD_REQUEST_POISON_DRAIN");
  endtask
  task automatic held_batch_poison(input integer number,input logic unknown_ready);
    batch_t held;
    reset_case(number);send_configuration(0,1);collect_good_rows(1);
    held=expected_batch(0,1,cfg_batch_tag);check(batch_valid===1'b1 && batch_context===held,"BATCH_EXPOSED_BEFORE_POISON");
    @(negedge clk);if(unknown_ready)batch_ready=1'bx;else abort_valid=1;
    repeat(4)begin @(posedge clk);#1ps;
      check(epoch_fault===1'b1 && batch_valid===1'b1 && batch_context===held && batch_acks==0,"POISON_RETAINS_BATCH");
    end
    @(negedge clk);abort_valid=0;batch_ready=1;
    @(posedge clk);#1ps;check(batch_acks==1,"POISONED_HELD_BATCH_REAL_ACK");
    @(negedge clk);batch_ready=0;check_sticky(1,1,1);
    pass_case("HELD_BATCH_POISON_ACK_LOCK");
  endtask
  task automatic ambiguous_response();
    reset_case(14);send_configuration(0,1);send_root(0,0);accept_request(1);
    @(negedge clk);next_rsp_valid=1;next_rsp_error=1'bx;next_rsp_data=fixture_descriptor(0,0);
    repeat(3)begin @(posedge clk);#1ps;
      check(epoch_fault===1'b1 && next_rsp_ready===1'b0 && response_acks==0,"AMBIGUOUS_OWNED_RESPONSE_QUARANTINE");
    end
    @(negedge clk);next_rsp_error=0;
    check_sticky(1,0,0);check(next_rsp_ready===1'b0,"RESOLUTION_DOES_NOT_RESURRECT_ASSOCIATION");
    pass_case("AMBIGUOUS_RESPONSE_STICKY_QUARANTINE");
    // The held unresolved channel is cleared ONLY by the next coupled reset.
  endtask
  task automatic foreign_response();
    reset_case(15);send_configuration(0,1);send_root(0,0);
    @(negedge clk);next_rsp_valid=1;next_rsp_error=0;next_rsp_data=fixture_descriptor(0,0);
    repeat(3)begin @(posedge clk);#1ps;
      check(epoch_fault===1'b1 && next_req_valid===1'b1 && next_rsp_ready===1'b0 && request_acks==0,"FOREIGN_RESPONSE_DURING_HELD_OFFER");
    end
    accept_request(1);check_sticky(1,0,0);
    check(next_rsp_ready===1'b0,"ACCEPTING_OLD_OFFER_CANNOT_ADOPT_FOREIGN_RESPONSE");pass_case("NO_RETROACTIVE_RESPONSE_OWNER");
  endtask
  task automatic ambiguous_request_ready();
    reset_case(16);send_configuration(0,1);send_root(0,0);
    @(negedge clk);next_req_ready=1'bx;
    repeat(3)begin @(posedge clk);#1ps;
      check(epoch_fault===1'b1 && next_req_valid===1'b1 && request_acks==0,"UNKNOWN_REQUEST_ACK_NOT_COUNTED");
    end
    @(negedge clk);next_req_ready=0;accept_request(1);
    @(negedge clk);next_rsp_valid=1;next_rsp_error=0;next_rsp_data=fixture_descriptor(0,0);
    check_sticky(1,0,0);check(next_rsp_ready===1'b0,"UNKNOWN_ACCEPTANCE_REMAINS_QUARANTINED");pass_case("UNKNOWN_REQUEST_READY_QUARANTINE");
  endtask

  initial begin clk=0;forever #5ns clk=~clk;end
  initial begin #200us;$fatal(1,"BATCH_ADAPTER_COMPONENT_WATCHDOG");end
  initial begin
    rst_n=0;case_id=-1;cases_passed=0;
    cfg_valid=0;cfg_frame='0;cfg_batch_start=0;cfg_batch_tokens=0;cfg_batch_tag=0;
    root_valid=0;root_last=0;root_origin=0;root_count=0;
    next_req_ready=0;next_rsp_valid=0;next_rsp_error=0;next_rsp_data=0;
    batch_ready=0;owner_held=1;abort_valid=0;active_start=0;active_tokens=0;
    healthy_batch(0,0,16);
    healthy_batch(1,256,8);
    bad_descriptor(2,1,1'b0); // wrong descriptor type
    bad_descriptor(3,2,1'b0); // wrong actual kept rank
    bad_descriptor(4,3,1'b0); // root does not join the real Size tuple
    bad_descriptor(5,4,1'b0); // source tag below held source base
    bad_descriptor(6,5,1'b0); // source tag-derived raw rank outside actual input extent
    bad_descriptor(7,0,1'b1); // known owned error response must drain, never publish
    bad_configuration(8,256,16);
    bad_configuration(9,0,0);
    bad_configuration(10,0,17);
    bad_root(11,1);
    bad_root(12,2);
    held_request_poison(13,1'b0);
    ambiguous_response();
    foreign_response();
    ambiguous_request_ready();
    held_request_poison(17,1'b1);
    held_batch_poison(18,1'b0);
    held_batch_poison(19,1'b1);
    check(cases_passed==20,"ALL_COMPONENT_CASES_CLOSED");
    $display("BATCH_ADAPTER_COMPONENT_PASS cases=20 B16=1 B8_tail=1 actual_ready_valid_counts_checked=1 mocked_Size_and_descriptor_memory=1 physical_C_instantiated=0 full_owner_verified=0 full264_verified=0 trained_arithmetic_verified=0 paper_matching=0");
    $finish;
  end
endmodule
