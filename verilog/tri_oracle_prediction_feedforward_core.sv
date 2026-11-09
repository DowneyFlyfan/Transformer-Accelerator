`timescale 1ns/1ps
// Prepared normalized prediction, packed sign reads and gate/up/down computation.
// Only normalized outlier magnitude class/sign are consumed by prediction.
// One memory transaction is outstanding; ownership lasts through actual LAST.
// Faulted tensors drain internally and publish only one terminal error packet.
// Reset requires the external memory peer to reset outstanding transactions too.
module tri_oracle_prediction_feedforward_core (
    input logic clk,rst_n,cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [63:0] cfg_activation_base,cfg_weight_base,cfg_up_weight_base,
    input logic [63:0] cfg_down_weight_base,cfg_gate_sign_base,cfg_up_sign_base,
    input logic [5:0] cfg_gate_shift,cfg_up_shift,cfg_down_shift,
    input logic [9:0] cfg_features,
    input logic [16:0] cfg_dense_features,
    input logic [15:0] cfg_output_start,
    input logic [8:0] cfg_output_count,
    input logic group_valid,
    output logic group_ready,
    input logic [10:0] group_id,
    input logic group_last,norm_valid,
    output logic norm_ready,
    input logic norm_last,norm_error,
    input logic [9:0] norm_index,
    input logic [127:0] norm_data,
    output logic out_valid,
    input logic out_ready,
    output logic out_last,out_fallback,out_error,
    output logic [31:0] out_tag,
    output logic [5:0] out_count,
    output logic [511:0] out_channels,
    output logic [1023:0] out_data,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,rsp_last,rsp_error,
    output logic rsp_ready,
    input logic [63:0] rsp_data
);
    typedef enum logic [1:0] {None, Sign, Compute} owner_t;
    owner_t owner;
    logic active, group_running, input_closed, saved_group_last;
    logic tensor_front_fault, group_fault, bus_fault, poisoned;
    logic [31:0] tag;
    logic [9:0] features;
    logic [16:0] dense_features;
    logic [10:0] saved_group;
    logic [63:0] gate_sign_base, up_sign_base;
    logic fetch_in_ready, fetch_valid, fetch_ready, fetch_last, fetch_error;
    logic [31:0] unused_fetch_tag;
    logic [10:0] unused_fetch_group;
    logic [9:0] unused_fetch_index;
    logic [127:0] fetch_data;
    logic [255:0] gate_signs, up_signs;
    logic sign_req_valid, sign_req_ready, sign_rsp_ready;
    logic [63:0] sign_req_address;
    logic [4:0] sign_req_length;
    logic core_cfg_ready, core_in_ready, core_out_valid, core_out_ready;
    logic core_out_last, core_out_fallback, core_out_error;
    logic [31:0] core_out_tag;
    logic [5:0] core_out_count;
    logic [511:0] core_out_channels;
    logic [1023:0] core_out_data;
    logic core_req_valid, core_req_ready, core_rsp_ready;
    logic [63:0] core_req_address;
    logic [4:0] core_req_length;
    logic choose_sign, selected_valid, selected_bad, internal_abort;
    logic presented_request, presented_sign, request_external;
    logic [63:0] presented_address;
    logic [4:0] presented_length;
    logic [4:0] expected_beats;
    logic [5:0] received_beats;
    logic response_valid, response_last, response_error, response_ready;
    logic [63:0] response_data;

    always_comb begin
        cfg_ready = !active && core_cfg_ready;
        group_ready = active && !group_running && !input_closed &&
            core_in_ready && !core_out_valid;
        norm_ready = active && group_running && fetch_in_ready;
        fetch_ready = active && group_running && core_in_ready;
        poisoned = tensor_front_fault || bus_fault;

        out_valid = active && !group_running && core_out_valid &&
            (!poisoned || core_out_last);
        out_last = core_out_last;
        out_error = core_out_error || poisoned;
        out_fallback = out_error ? 1'b0 : core_out_fallback;
        out_tag = core_out_tag;
        out_count = out_error ? 6'd0 : core_out_count;
        out_channels = out_error ? 512'b0 : core_out_channels;
        out_data = out_error ? 1024'b0 : core_out_data;

        // Once valid is presented externally it cannot be withdrawn or
        // preempted, including when a frontend fault arrives during a stall.
        choose_sign = presented_request ? presented_sign : sign_req_valid;
        selected_valid = presented_request || sign_req_valid || core_req_valid;
        req_address = presented_request ? presented_address :
            (choose_sign ? sign_req_address : core_req_address);
        req_length = presented_request ? presented_length :
            (choose_sign ? sign_req_length : core_req_length);
        selected_bad = req_length == 0 || req_length > 5'd16 || req_address[2:0] != 0;
        request_external = presented_request || (!poisoned && !selected_bad);
        req_valid = active && owner == None && selected_valid && request_external;
        response_valid = owner != None && (internal_abort || rsp_valid);
        response_last = internal_abort || rsp_last;
        response_error = internal_abort || rsp_error;
        response_data = internal_abort ? 64'b0 : rsp_data;
        response_ready = owner == Sign ? sign_rsp_ready :
            (owner == Compute && core_rsp_ready);
        rsp_ready = owner != None && !internal_abort && response_ready;
    end
    // Keep backpressure equations separate from produced valid/address signals.
    // Error packets must not abandon a still-pending later output tile.
    always_comb core_out_ready = active && !group_running &&
        ((poisoned && !core_out_last) || out_ready);
    always_comb sign_req_ready = active && owner == None && choose_sign &&
        (!request_external || req_ready);
    always_comb core_req_ready = active && owner == None && !choose_sign &&
        (!request_external || req_ready);

    tri_oracle_sign_fetch signs (
        .clk(clk), .rst_n(rst_n),
        .in_valid(active && group_running && norm_valid), .in_ready(fetch_in_ready),
        .in_tag(tag), .in_group(saved_group), .in_strips(features), .in_index(norm_index),
        .in_last(norm_last), .in_error(norm_error || group_fault || poisoned),
        .in_norm_q8(norm_data), .in_gate_base(gate_sign_base), .in_up_base(up_sign_base),
        .out_valid(fetch_valid), .out_ready(fetch_ready),
        .out_last(fetch_last), .out_error(fetch_error), .out_tag(unused_fetch_tag),
        .out_group(unused_fetch_group), .out_index(unused_fetch_index),
        .out_norm_q8(fetch_data), .out_gate_signs(gate_signs), .out_up_signs(up_signs),
        .req_valid(sign_req_valid), .req_ready(sign_req_ready),
        .req_address(sign_req_address), .req_length(sign_req_length),
        .rsp_valid(owner == Sign && response_valid), .rsp_ready(sign_rsp_ready),
        .rsp_last(response_last), .rsp_error(response_error), .rsp_data(response_data)
    );
    tri_oracle_feedforward_core core (
        .clk(clk), .rst_n(rst_n),
        .cfg_valid(cfg_valid && cfg_ready), .cfg_ready(core_cfg_ready),
        .cfg_tag(cfg_tag), .cfg_activation_base(cfg_activation_base),
        .cfg_weight_base(cfg_weight_base), .cfg_up_weight_base(cfg_up_weight_base),
        .cfg_gate_shift(cfg_gate_shift), .cfg_up_shift(cfg_up_shift), .cfg_features(cfg_features),
        .cfg_down_weight_base(cfg_down_weight_base), .cfg_dense_features(cfg_dense_features),
        .cfg_output_start(cfg_output_start), .cfg_output_count(cfg_output_count),
        .cfg_down_shift(cfg_down_shift),
        .in_valid(active && group_running && fetch_valid), .in_ready(core_in_ready),
        .in_last(fetch_last), .in_group_last(saved_group_last), .in_group(saved_group),
        .norm_activations(fetch_data), .gate_weight_signs(gate_signs), .up_weight_signs(up_signs),
        .out_valid(core_out_valid), .out_ready(core_out_ready), .out_last(core_out_last),
        .out_fallback(core_out_fallback), .out_error(core_out_error), .out_tag(core_out_tag),
        .out_count(core_out_count), .out_channels(core_out_channels), .out_data(core_out_data),
        .req_valid(core_req_valid), .req_ready(core_req_ready),
        .req_address(core_req_address), .req_length(core_req_length),
        .rsp_valid(owner == Compute && response_valid), .rsp_ready(core_rsp_ready),
        .rsp_last(response_last), .rsp_error(response_error), .rsp_data(response_data)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            active <= 1'b0;
            group_running <= 1'b0;
            input_closed <= 1'b0;
            saved_group_last <= 1'b0;
            tensor_front_fault <= 1'b0;
            group_fault <= 1'b0;
            bus_fault <= 1'b0;
            tag <= '0;
            features <= '0;
            dense_features <= '0;
            saved_group <= '0;
            gate_sign_base <= '0;
            up_sign_base <= '0;
            owner <= None;
            presented_request <= 1'b0;
            presented_sign <= 1'b0;
            presented_address <= '0;
            presented_length <= '0;
            internal_abort <= 1'b0;
            expected_beats <= '0;
            received_beats <= '0;
        end else begin
            if (cfg_valid && cfg_ready) begin
                active <= 1'b1;
                input_closed <= 1'b0;
                tensor_front_fault <= 1'b0;
                group_fault <= 1'b0;
                bus_fault <= 1'b0;
                tag <= cfg_tag;
                features <= cfg_features;
                dense_features <= cfg_dense_features;
                gate_sign_base <= cfg_gate_sign_base;
                up_sign_base <= cfg_up_sign_base;
            end
            if (group_valid && group_ready) begin
                group_running <= 1'b1;
                saved_group <= group_id;
                saved_group_last <= group_last;
                input_closed <= group_last;
                group_fault <= {1'b0,group_id,5'b0} >= dense_features;
                if ({1'b0,group_id,5'b0} >= dense_features) tensor_front_fault <= 1'b1;
            end
            if (fetch_valid && fetch_ready) begin
                group_fault <= group_fault || fetch_error;
                tensor_front_fault <= tensor_front_fault || fetch_error;
                if (fetch_last) group_running <= 1'b0;
            end
            if (out_valid && out_ready && out_last) active <= 1'b0;

            if (req_valid && !req_ready) begin
                presented_request <= 1'b1;
                presented_sign <= choose_sign;
                presented_address <= req_address;
                presented_length <= req_length;
            end
            if (active && owner == None && selected_valid && (!request_external || req_ready)) begin
                if (choose_sign) owner <= Sign;
                else owner <= Compute;
                internal_abort <= !request_external;
                presented_request <= 1'b0;
                expected_beats <= req_length;
                received_beats <= '0;
                if (selected_bad) bus_fault <= 1'b1;
            end
            if (response_valid && response_ready) begin
                if (response_error ||
                    response_last != (received_beats+6'd1 == {1'b0,expected_beats}))
                    bus_fault <= 1'b1;
                if (received_beats != 6'd63) received_beats <= received_beats+6'd1;
                if (response_last) begin
                    owner <= None;
                    internal_abort <= 1'b0;
                end
            end
        end
    end
endmodule
