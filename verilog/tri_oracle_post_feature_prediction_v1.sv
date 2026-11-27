`timescale 1ns / 1ps
// One POST row replayed across176 original32-channel groups. This module
// owns no fabric, SRAM, normalizer, TMU or physical-lease release endpoint.
module tri_oracle_post_feature_prediction_v1 (
  input logic clk, rst_n, abort_valid,
  input logic next_context_owned, strip_fabric_owned,
  input logic cfg_valid,
  output logic cfg_ready,
  input logic cfg_archive_committed, cfg_scalar_weight_units,
  input logic [1:0] cfg_normalization_role,
  input logic [31:0] cfg_tag,
  input logic [4:0] cfg_layer,
  input logic [15:0] cfg_epoch,
  input logic [9:0] cfg_original_root, cfg_input_rank, cfg_kept_rank,
  input logic signed [8:0] cfg_exponent,
  input logic [127:0] cfg_bundle_id,
  input logic [63:0] cfg_feature_base, cfg_feature_bytes,
  input logic [63:0] cfg_gate_sign_base, cfg_gate_sign_bytes,
  input logic [63:0] cfg_up_sign_base, cfg_up_sign_bytes,
  output logic req_valid,
  input logic req_ready,
  output logic [63:0] req_address,
  output logic [4:0] req_length,
  input logic rsp_valid,
  output logic rsp_ready,
  input logic rsp_last, rsp_error,
  input logic [63:0] rsp_data,
  output logic [533:0] strip_request,
  input logic [111:0] strip_response,
  output logic mask_valid,
  input logic mask_ready,
  output logic mask_last,
  output logic [31:0] mask_tag,
  output logic [15:0] mask_start,
  output logic [6:0] mask_count,
  output logic [1279:0] mask_bits,
  output logic done_valid,
  input logic done_ready,
  output logic done_error,
  output logic [31:0] done_tag,
  output logic [4:0] done_layer,
  output logic [15:0] done_epoch,
  output logic [9:0] done_original_root, done_input_rank, done_kept_rank,
  output logic signed [8:0] done_exponent,
  output logic [127:0] done_bundle_id,
  output logic [7:0] completed_groups,
  output logic [15:0] accepted_strips,
  output logic [6:0] accepted_masks,
  output logic epoch_fault, active, port_idle, strip_quiet, idle
);
  typedef enum logic [3:0] {
    Idle, StartRow, StartGroup, RunGroup, JoinGroup, FinishRow,
    FaultDrain, SuccessHeld, ErrorHeld, FaultLock
  } state_t;
  typedef enum logic [1:0] {BusIdle, BusOffer, BusOwned} bus_state_t;
  state_t state;
  bus_state_t bus_state;
  logic job_active, fault_latched, bus_quarantined, predictor_quarantined;
  logic [31:0] tag;
  logic [4:0] layer;
  logic [15:0] epoch;
  logic [9:0] root, input_rank, kept_rank;
  logic signed [8:0] exponent;
  logic [127:0] bundle_id;
  logic [63:0] feature_base, feature_bytes, gate_base, up_base;
  logic committed;
  logic [7:0] group_index;
  logic [2:0] cluster;
  logic [8:0] reader_inputs, group_inputs;
  logic [12:0] group_outliers;
  logic reader_started, reader_success_seen, packet_started, packet_done_seen;
  logic fetch_busy, predictor_offer, predictor_engaged, last_prediction_accepted;
  logic final_fetch_seen, result_accepted;
  logic [9:0] pending_index;
  logic [7:0] pending_mask, pending_negative;
  logic bus_sign_owner;
  logic [63:0] bus_address;
  logic [4:0] bus_length, bus_beat;
  logic cfg_fire, cfg_bad, external_fault, base_fault, fault_now;
  logic bus_request_fire, bus_response_fire, bus_unexpected, bus_response_bad;
  logic raw_result_valid, result_owner, result_bad, result_fire, predictor_unexpected;
  logic result_ready, predictor_fire, group_fire, mask_fire, known_quiet;
  logic [64:0] feature_last, gate_last, up_last, selected_last;
  logic [64:0] gate_required_last, up_required_last;

  logic r_cfg_valid, r_cfg_ready, r_abort, r_valid, r_ready, r_last, r_error;
  logic [31:0] r_tag, r_done_tag;
  logic [4:0] r_layer, r_done_layer;
  logic [15:0] r_epoch, r_done_epoch;
  logic [9:0] r_root, r_input, r_kept, r_index, r_done_root, r_done_input, r_done_kept;
  logic [3:0] r_count;
  logic signed [8:0] r_exponent, r_done_exponent;
  logic [7:0] r_mask, r_full_negative, r_negative;
  logic r_req, r_req_ready, r_rsp_valid, r_rsp_ready;
  logic [63:0] r_address;
  logic [4:0] r_length;
  logic r_done, r_done_ready, r_done_error, r_fault, r_active, r_port_idle, r_idle;
  logic [8:0] r_accepted;
  logic [3:0] r_lines;
  logic [6:0] r_beats;
  logic r_cfg_fire, r_fire, r_good, r_done_good, r_done_fire;

  logic f_in_valid, f_in_ready, f_valid, f_ready, f_last, f_error;
  logic [31:0] f_tag;
  logic [10:0] f_group;
  logic [9:0] f_index;
  logic [127:0] f_data, incoming_proxy, expected_proxy;
  logic [255:0] f_gate_signs, f_up_signs;
  logic f_req, f_req_ready, f_rsp_valid, f_rsp_ready;
  logic [63:0] f_address;
  logic [4:0] f_length;
  logic f_in_fire, f_fire, f_bad;

  logic p_cfg_valid, p_cfg_ready, p_valid, p_ready, p_last, p_cancel;
  logic [31:0] p_done_tag;
  logic p_done, p_done_ready, p_done_error, p_cfg_fire, p_done_fire, p_done_bad;

  function automatic logic overlaps(input logic [63:0] a, b, input logic [64:0] ae, be);
    return {1'b0,a} <= be && {1'b0,b} <= ae;
  endfunction
  function automatic logic [127:0] classified_proxy(input logic [7:0] flags, negative);
    logic [127:0] value;
    value = 0;
    for (integer lane=0;lane<8;lane++)
      if (flags[lane]) value[lane*16+:16] = negative[lane] ? -16'sd769 : 16'sd769;
    return value;
  endfunction
  function automatic logic [3:0] count8(input logic [7:0] bits);
    logic [3:0] value;
    value = 0;
    for(integer lane=0;lane<8;lane++)value=value+4'(bits[lane]);
    return value;
  endfunction

  always_comb begin
    feature_last={1'b0,cfg_feature_base}+{1'b0,cfg_feature_bytes}-65'd1;
    gate_last={1'b0,cfg_gate_sign_base}+{1'b0,cfg_gate_sign_bytes}-65'd1;
    up_last={1'b0,cfg_up_sign_base}+{1'b0,cfg_up_sign_bytes}-65'd1;
    selected_last={1'b0,cfg_feature_base}+65'(cfg_kept_rank)*65'd768+65'd767;
    gate_required_last={1'b0,cfg_gate_sign_base}+65'd1441791;
    up_required_last={1'b0,cfg_up_sign_base}+65'd1441791;
    cfg_bad=cfg_normalization_role!=1 || !cfg_scalar_weight_units || cfg_layer>=22 ||
      cfg_original_root>=576 || cfg_input_rank>=576 || cfg_kept_rank>=576 || cfg_input_rank!=cfg_kept_rank ||
      cfg_feature_base[5:0]!=0 || cfg_feature_bytes==0 || cfg_feature_bytes[5:0]!=0 ||
      cfg_gate_sign_base[2:0]!=0 || cfg_gate_sign_bytes[2:0]!=0 || cfg_gate_sign_bytes<1441792 ||
      cfg_up_sign_base[2:0]!=0 || cfg_up_sign_bytes[2:0]!=0 || cfg_up_sign_bytes<1441792 ||
      feature_last[64] || gate_last[64] || up_last[64] || selected_last[64] || selected_last>feature_last ||
      gate_required_last[64] || up_required_last[64] || gate_required_last>gate_last || up_required_last>up_last ||
      overlaps(cfg_feature_base,cfg_gate_sign_base,feature_last,gate_last) ||
      overlaps(cfg_feature_base,cfg_up_sign_base,feature_last,up_last) ||
      overlaps(cfg_gate_sign_base,cfg_up_sign_base,gate_last,up_last);

    // The backend load/command owner mux DOES NOT grant these predictor ports.
    external_fault=job_active && (abort_valid || !next_context_owned || !strip_fabric_owned);
    cfg_ready=rst_n && state==Idle && !job_active && !fault_latched && !bus_quarantined &&
      !predictor_quarantined && !abort_valid && next_context_owned && strip_fabric_owned &&
      cfg_archive_committed && !rsp_valid && !strip_response[110] && bus_state==BusIdle &&
      !r_active && r_port_idle && !r_valid && !r_done && f_in_ready && p_cfg_ready;
    cfg_fire=cfg_valid && cfg_ready;

    // Arbitration captures an OFFER owner/payload, then retains the accepted
    // response owner through actual LAST. A request cannot retro-associate an
    // already present response, including on its own acceptance edge.
    req_valid=rst_n && bus_state==BusOffer;
    req_address=bus_address; req_length=bus_length;
    r_req_ready=req_valid && !bus_sign_owner && req_ready;
    f_req_ready=req_valid && bus_sign_owner && req_ready;
    r_rsp_valid=rst_n && bus_state==BusOwned && !bus_sign_owner && !bus_quarantined && rsp_valid;
    f_rsp_valid=rst_n && bus_state==BusOwned && bus_sign_owner && !bus_quarantined && rsp_valid;
    rsp_ready=rst_n && bus_state==BusOwned && !bus_quarantined && (bus_sign_owner ? f_rsp_ready : r_rsp_ready);
    bus_request_fire=req_valid && req_ready;
    bus_response_fire=rsp_valid && rsp_ready;
    bus_unexpected=rst_n && rsp_valid && bus_state!=BusOwned;
    bus_response_bad=bus_response_fire && (rsp_error || rsp_last!=(bus_beat+5'd1==bus_length));

    raw_result_valid=strip_response[110];
    result_owner=job_active && predictor_engaged && last_prediction_accepted && !predictor_quarantined;
    predictor_unexpected=rst_n && raw_result_valid && !result_owner;
    base_fault=fault_latched || external_fault || bus_quarantined || predictor_quarantined ||
      bus_unexpected || predictor_unexpected;
    result_bad=raw_result_valid && result_owner &&
      (strip_response[109] || strip_response[12:0]!=group_outliers || group_inputs!=256 || reader_inputs!=256);

    r_cfg_valid=state==StartGroup && !base_fault;
    r_cfg_fire=r_cfg_valid && r_cfg_ready;
    r_good=!r_error && r_tag==tag && r_layer==layer && r_epoch==epoch && r_root==root &&
      r_input==input_rank && r_kept==kept_rank && r_exponent==exponent && reader_inputs<256 &&
      r_index=={1'b0,reader_inputs} && r_count==8 && r_last==(reader_inputs==255) && (r_negative & ~r_mask)==0;
    incoming_proxy=classified_proxy(r_mask,r_negative);
    expected_proxy=classified_proxy(pending_mask,pending_negative);
    f_in_valid=state==RunGroup && !base_fault && !fetch_busy && !predictor_offer && !last_prediction_accepted && r_valid && r_good;
    r_ready=reader_started && (base_fault ? 1'b1 :
      (state==RunGroup && !fetch_busy && !predictor_offer && !last_prediction_accepted && f_in_ready));
    r_fire=r_valid && r_ready;
    f_in_fire=f_in_valid && f_in_ready;
    f_bad=f_valid && (!fetch_busy || f_error || f_tag!=tag || f_group!={3'b0,group_index} ||
      f_index!=pending_index || f_last!=(pending_index==255) || f_data!=expected_proxy);
    r_done_good=!r_done_error && r_done_tag==tag && r_done_layer==layer && r_done_epoch==epoch &&
      r_done_root==root && r_done_input==input_rank && r_done_kept==kept_rank && r_done_exponent==exponent &&
      r_accepted==256 && r_lines==12 && r_beats==96 && reader_inputs==256;
    r_done_ready=reader_started && (base_fault || (result_accepted && final_fetch_seen && !fetch_busy && !predictor_offer));
    r_done_fire=r_done && r_done_ready;

    p_cfg_valid=state==StartRow;
    p_cfg_fire=p_cfg_valid && p_cfg_ready;
    p_done_bad=p_done && (p_done_tag!=tag || (!base_fault && (p_done_error || accepted_masks!=71)));
    p_done_ready=packet_started && (state==FinishRow || state==FaultDrain || state==FaultLock);
    p_done_fire=p_done && p_done_ready;

    fault_now=external_fault || bus_unexpected || predictor_unexpected || bus_response_bad ||
      (cfg_fire && cfg_bad) || (r_fire && !r_good) || (r_done && reader_started && !r_done_good) ||
      f_bad || result_bad || p_done_bad;
    // No combinational feedback through the reader's immediate row_fault.
    // Its additional internal fault is observed/latching at the clock below.
    r_abort=fault_latched || fault_now || bus_quarantined || predictor_quarantined;
    p_valid=state==RunGroup && raw_result_valid && result_owner && !base_fault && !fault_now && !r_fault && !result_bad;
    result_ready=result_owner && (base_fault || fault_now || r_fault || result_bad || (state==RunGroup && p_ready));
    result_fire=raw_result_valid && result_ready;
    group_fire=p_valid && p_ready;
    p_last=group_index==175;

    // The qualified sign fetcher sees only a classification proxy. Nothing
    // here treats its amplitude as a normalization output. Full post-gamma
    // sign remains distinct in the immutable archive; it is not the FF sign.
    strip_request={cluster,predictor_offer,(pending_index==255),result_ready,
      pending_negative,pending_mask,f_gate_signs,f_up_signs};
    predictor_fire=predictor_offer && strip_response[111];
    f_ready=predictor_fire || (base_fault && fetch_busy && f_valid && !predictor_offer);
    f_fire=f_valid && f_ready;
    mask_fire=mask_valid && mask_ready;

    done_valid=rst_n && (state==SuccessHeld || state==ErrorHeld);
    done_error=state==ErrorHeld;
    done_tag=tag; done_layer=layer; done_epoch=epoch; done_original_root=root;
    done_input_rank=input_rank; done_kept_rank=kept_rank; done_exponent=exponent; done_bundle_id=bundle_id;
    epoch_fault=rst_n && (fault_latched || fault_now || r_fault);
    active=rst_n && job_active;
    port_idle=rst_n && bus_state==BusIdle && !rsp_valid && !bus_quarantined && !r_req && !f_req;
    strip_quiet=rst_n && !predictor_offer && !predictor_engaged && !raw_result_valid && !predictor_quarantined;
    known_quiet=port_idle && !reader_started && !fetch_busy && !f_valid && !predictor_offer &&
      !packet_started && !mask_valid && !r_valid && !r_done;
    idle=rst_n && state==Idle && !job_active && !fault_latched && !cfg_valid && !abort_valid && port_idle && strip_quiet;
  end

  tri_oracle_post_feature_reader_v1 reader (
    .clk,.rst_n,.abort_valid(r_abort),.next_context_owned,
    .cfg_valid(r_cfg_valid),.cfg_ready(r_cfg_ready),.cfg_archive_committed(committed),.cfg_normalization_role(2'd1),
    .cfg_tag(tag),.cfg_layer(layer),.cfg_epoch(epoch),.cfg_original_root(root),.cfg_input_rank(input_rank),.cfg_kept_rank(kept_rank),
    .cfg_exponent(exponent),.cfg_feature_base(feature_base),.cfg_feature_bytes(feature_bytes),
    .req_valid(r_req),.req_ready(r_req_ready),.req_address(r_address),.req_length(r_length),
    .rsp_valid(r_rsp_valid),.rsp_ready(r_rsp_ready),.rsp_last,.rsp_error,.rsp_data,
    .out_valid(r_valid),.out_ready(r_ready),.out_last(r_last),.out_error(r_error),.out_tag(r_tag),.out_layer(r_layer),.out_epoch(r_epoch),
    .out_original_root(r_root),.out_input_rank(r_input),.out_kept_rank(r_kept),.out_index(r_index),.out_count(r_count),
    .out_exponent(r_exponent),.out_outlier_mask(r_mask),.out_normalized_negative(r_full_negative),.out_outlier_negative(r_negative),
    .done_valid(r_done),.done_ready(r_done_ready),.done_error(r_done_error),.done_tag(r_done_tag),.done_layer(r_done_layer),.done_epoch(r_done_epoch),
    .done_original_root(r_done_root),.done_input_rank(r_done_input),.done_kept_rank(r_done_kept),.done_exponent(r_done_exponent),
    .accepted_strips(r_accepted),.completed_lines(r_lines),.received_beats(r_beats),.epoch_fault(r_fault),.active(r_active),.port_idle(r_port_idle),.idle(r_idle)
  );
  tri_oracle_sign_fetch sign_fetch (
    .clk,.rst_n,.in_valid(f_in_valid),.in_ready(f_in_ready),.in_tag(tag),.in_group({3'b0,group_index}),
    .in_strips(10'd256),.in_index(r_index),.in_last(r_last),.in_error(1'b0),.in_norm_q8(incoming_proxy),
    .in_gate_base(gate_base),.in_up_base(up_base),.out_valid(f_valid),.out_ready(f_ready),.out_last(f_last),.out_error(f_error),
    .out_tag(f_tag),.out_group(f_group),.out_index(f_index),.out_norm_q8(f_data),.out_gate_signs(f_gate_signs),.out_up_signs(f_up_signs),
    .req_valid(f_req),.req_ready(f_req_ready),.req_address(f_address),.req_length(f_length),
    .rsp_valid(f_rsp_valid),.rsp_ready(f_rsp_ready),.rsp_last,.rsp_error,.rsp_data
  );
  tri_oracle_batched_mask_packet399 packetizer (
    .clk,.rst_n,.cfg_valid(p_cfg_valid),.cfg_ready(p_cfg_ready),.cfg_tag(tag),.cfg_tokens(5'd1),.cfg_channels(16'd5632),
    .in_valid(p_valid),.in_ready(p_ready),.in_tag(tag),.in_group(group_index),.in_token(4'd0),.in_last(p_last),.in_skip_mask(strip_response[44:13]),
    .cancel_valid(p_cancel),.cancel_tag(tag),.mask_valid,.mask_ready,.mask_tag,.mask_start,.mask_count,.mask_last,.mask_bits,
    .done_valid(p_done),.done_ready(p_done_ready),.done_error(p_done_error),.done_tag(p_done_tag)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state<=Idle; bus_state<=BusIdle; job_active<=0; fault_latched<=0; bus_quarantined<=0; predictor_quarantined<=0;
      tag<=0;layer<=0;epoch<=0;root<=0;input_rank<=0;kept_rank<=0;exponent<=0;bundle_id<=0;
      feature_base<=0;feature_bytes<=0;gate_base<=0;up_base<=0;committed<=0;
      group_index<=0;cluster<=0;reader_inputs<=0;group_inputs<=0;group_outliers<=0;
      reader_started<=0;reader_success_seen<=0;packet_started<=0;packet_done_seen<=0;
      fetch_busy<=0;predictor_offer<=0;predictor_engaged<=0;last_prediction_accepted<=0;
      final_fetch_seen<=0;result_accepted<=0;pending_index<=0;pending_mask<=0;pending_negative<=0;
      bus_sign_owner<=0;bus_address<=0;bus_length<=0;bus_beat<=0;p_cancel<=0;
      completed_groups<=0;accepted_strips<=0;accepted_masks<=0;
    end else begin
      p_cancel<=0;
      if (fault_now || r_fault) fault_latched<=1;
      if (bus_unexpected) bus_quarantined<=1;
      if (predictor_unexpected) predictor_quarantined<=1;

      case(bus_state)
        BusIdle: if(!bus_quarantined && !bus_unexpected) begin
          // The sign fetcher may finish ALL internal subreads belonging to an
          // already accepted strip after fault. The reader likewise drains any
          // prior request offer; no child is locally reset or transport-faked.
          if(f_req && fetch_busy)begin
            bus_sign_owner<=1;bus_address<=f_address;bus_length<=f_length;bus_state<=BusOffer;
          end else if(r_req && reader_started)begin
            bus_sign_owner<=0;bus_address<=r_address;bus_length<=r_length;bus_state<=BusOffer;
          end
        end
        BusOffer: if(bus_request_fire)begin bus_state<=BusOwned;bus_beat<=0;end
        BusOwned: if(bus_response_fire)begin
          if(rsp_last)begin bus_state<=BusIdle;bus_beat<=0;end
          else if(bus_beat!=31)bus_beat<=bus_beat+5'd1;
        end
        default:begin bus_quarantined<=1;fault_latched<=1;end
      endcase

      if(p_cfg_fire)packet_started<=1;
      if(p_done_fire)begin packet_started<=0;packet_done_seen<=1;end
      if(r_cfg_fire)reader_started<=1;
      if(r_done_fire)begin reader_started<=0;reader_success_seen<=r_done_good;end
      if(f_in_fire)begin
        fetch_busy<=1;pending_index<=r_index;pending_mask<=r_mask;pending_negative<=r_negative;
        reader_inputs<=reader_inputs+9'd1;
        group_outliers<=group_outliers+13'(count8(r_mask));
      end
      if(f_fire)begin
        fetch_busy<=0;
        if(pending_index==255 && predictor_fire)final_fetch_seen<=1;
      end
      if(f_valid && fetch_busy && !predictor_offer && !f_bad && !fault_now && !base_fault && !r_fault)
        predictor_offer<=1;
      if(predictor_fire)begin
        predictor_offer<=0;predictor_engaged<=1;
        accepted_strips<=accepted_strips+16'd1;group_inputs<=group_inputs+9'd1;
        if(pending_index==255)last_prediction_accepted<=1;
      end
      if(result_fire)begin
        predictor_engaged<=0;
        if(group_fire)begin completed_groups<=completed_groups+8'd1;result_accepted<=1;end
      end
      if(mask_fire)accepted_masks<=accepted_masks+7'd1;

      // The child's cancel can withdraw its Offer state, so NEVER cancel on
      // raw abort. Register cancel only after an observed edge with no public
      // KEEP offer AND no new group input. For5632channels there is no private
      // remaining96 carry auto-offer that can race this deferred cancellation.
      if(fault_latched && packet_started && !p_done && !mask_valid && !p_valid)p_cancel<=1;

      case(state)
        Idle: if(cfg_fire)begin
          job_active<=1;tag<=cfg_tag;layer<=cfg_layer;epoch<=cfg_epoch;root<=cfg_original_root;
          input_rank<=cfg_input_rank;kept_rank<=cfg_kept_rank;exponent<=cfg_exponent;bundle_id<=cfg_bundle_id;
          feature_base<=cfg_feature_base;feature_bytes<=cfg_feature_bytes;gate_base<=cfg_gate_sign_base;up_base<=cfg_up_sign_base;
          committed<=cfg_archive_committed;group_index<=0;cluster<=0;
          completed_groups<=0;accepted_strips<=0;accepted_masks<=0;packet_done_seen<=0;
          if(cfg_bad)state<=FaultDrain;else state<=StartRow;
        end
        StartRow: if(p_cfg_fire)state<=StartGroup;
        StartGroup: if(r_cfg_fire)begin
          reader_inputs<=0;group_inputs<=0;group_outliers<=0;reader_success_seen<=0;
          last_prediction_accepted<=0;final_fetch_seen<=0;result_accepted<=0;state<=RunGroup;
        end
        RunGroup: if(group_fire)state<=JoinGroup;
        JoinGroup: if(!base_fault && !fault_now && !r_fault && reader_success_seen && result_accepted &&
                      final_fetch_seen && !fetch_busy && !predictor_offer && !predictor_engaged && r_idle)begin
          if(group_index==175)state<=FinishRow;
          else begin
            group_index<=group_index+8'd1;cluster<=cluster==4 ? 3'd0 : cluster+3'd1;
            state<=StartGroup;
          end
        end
        FinishRow: if(!base_fault && !fault_now && !r_fault && packet_done_seen && known_quiet && strip_quiet &&
                       completed_groups==176 && accepted_strips==45056 && accepted_masks==71)state<=SuccessHeld;
        FaultDrain: if(known_quiet)begin
          // A current unknown result is already unassociated on this edge;
          // the sticky quarantine flag is not updated until after the edge.
          if(predictor_engaged || predictor_quarantined || bus_quarantined || predictor_unexpected)state<=FaultLock;
          else state<=ErrorHeld;
        end
        SuccessHeld: if(done_ready)begin
          if(base_fault || fault_now || r_fault)state<=FaultLock;
          else begin job_active<=0;state<=Idle;end
        end
        ErrorHeld: if(done_ready)state<=FaultLock;
        FaultLock:begin end
        default:begin fault_latched<=1;state<=FaultDrain;end
      endcase
      // Hold already offered success/error status. All earlier active states
      // stop launching fresh work, while the independent transport drains.
      if(job_active && (fault_now || r_fault || fault_latched) &&
         state!=SuccessHeld && state!=ErrorHeld && state!=FaultLock && state!=FaultDrain)state<=FaultDrain;
      if(!job_active && (bus_unexpected || predictor_unexpected))state<=FaultLock;
    end
  end
endmodule
