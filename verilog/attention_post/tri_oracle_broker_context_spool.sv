`timescale 1ns/1ps
`default_nettype none

// One real complete-head broker and one context spool. The caller exclusively
// owns the broker's existing fabric/softmax/tensor ports and both external
// allocations. Reset all peers together; this wrapper creates no fabric/bank.
//
// All 32 heads are required. cfg_value_exponents packs four signed9 V-group
// units, group h/8 for head h. Only the actual low8 travels through the legacy
// broker; full9 metadata is captured here and checked at accepted V responses.
// A broker context is compared, never relabelled, before its full9 unit reaches
// the spool. Scratch and code writes remain provisional until successful Done.
//
// Cancellation is accepted during Active, poisons the job and drains both real
// children. After broker completion, the spool may finish provisional conversion
// because it has no abort port. A registered/offered completion is immutable;
// cancellation at that point is too late. An active-job failure requires coupled
// reset after failed Done. A locally rejected configuration launches no child
// and can return to Idle after its failed Done is acknowledged.
module tri_oracle_broker_context_spool (
    input wire logic clk, rst_n,
    input wire logic cfg_valid,
    output logic cfg_ready, cfg_error,
    input wire logic [31:0] cfg_heads, cfg_streaming,
    input wire logic [10:0] cfg_total_keys, cfg_visible_keys,
    input wire logic [223:0] cfg_score_shifts,
    input wire logic [35:0] cfg_value_exponents,
    input wire logic [15:0] cfg_query, cfg_epoch,
    input wire logic [31:0] cfg_tag,
    input wire logic [63:0] cfg_spool_base, cfg_code_base,
    input wire logic [287:0] cfg_weight_units, cfg_output_units,
    input wire logic cancel,

    output logic tensor_req_valid,
    input wire logic tensor_req_ready,
    output logic [1:0] tensor_req_kind,
    output logic [4:0] tensor_req_head,
    output logic [9:0] tensor_req_key,
    output logic [15:0] tensor_req_query, tensor_req_epoch,
    output logic [31:0] tensor_req_tag,
    input wire logic tensor_rsp_valid,
    output logic tensor_rsp_ready,
    input wire logic tensor_rsp_error,
    input wire logic [1:0] tensor_rsp_kind,
    input wire logic [4:0] tensor_rsp_head,
    input wire logic [9:0] tensor_rsp_key, tensor_rsp_size,
    input wire logic [15:0] tensor_rsp_query, tensor_rsp_epoch,
    input wire logic [31:0] tensor_rsp_tag,
    input wire logic signed [8:0] tensor_rsp_value_exponent,
    input wire logic [511:0] tensor_rsp_data,

    output logic all_contexts_collected,
    output logic done_valid,
    input wire logic done_ready,
    output logic done_error, reset_required, busy,
    output logic [7:0] error_code,
    output logic [31:0] done_tag,
    output logic [15:0] done_query, done_epoch,
    output logic signed [9:0] done_unit,

    output logic fabric_load_valid,
    input wire logic fabric_load_error,
    output logic [4:0] fabric_load_core,
    output logic [1:0] fabric_load_kind,
    output logic [9:0] fabric_load_addr,
    output logic [2047:0] fabric_load_data,
    output logic [31:0] fabric_load_rows,
    output logic [4:0] fabric_activation_reloaded,
    output logic fabric_cmd_valid,
    input wire logic fabric_cmd_ready,
    output logic [4:0] fabric_cmd_clusters, fabric_cmd_weight, fabric_cmd_mask,
    output logic [9:0] fabric_cmd_activation,
    output logic [3:0] fabric_cmd_output,
    output logic fabric_cmd_accumulate,
    output logic [1:0] fabric_cmd_reduce,
    output logic [2:0] fabric_core_select,
    input wire logic [4:0] fabric_out_valid,
    output logic [4:0] fabric_out_ready,
    input wire logic [19:0] fabric_out_slot,
    input wire logic [5119:0] fabric_out_data,
    output tri_oracle_wac_softmax_types::request_t softmax_request,
    input tri_oracle_wac_softmax_types::response_t softmax_response,

    output logic wr_req_valid,
    input wire logic wr_req_ready,
    output logic [63:0] wr_address,
    output logic [4:0] wr_length,
    output logic wr_data_valid,
    input wire logic wr_data_ready,
    output logic [63:0] wr_data,
    output logic wr_last, wr_rsp_ready,
    input wire logic wr_rsp_valid, wr_error,
    output logic rd_req_valid,
    input wire logic rd_req_ready,
    output logic [63:0] rd_address,
    output logic [4:0] rd_length,
    input wire logic rd_rsp_valid,
    output logic rd_rsp_ready,
    input wire logic [63:0] rd_data,
    input wire logic rd_last, rd_error
);
    typedef enum logic [1:0] {Idle, Active, Complete, Poisoned} state_t;
    state_t state;
    logic [35:0] saved_value_exponents;
    logic [31:0] saved_tag;
    logic [15:0] saved_query, saved_epoch;
    logic job_failed, terminal_seen, completion_needs_reset;
    logic config_accept, child_config_valid, config_bad, cancel_now;
    logic broker_cfg_ready, spool_cfg_ready, spool_cfg_error;
    logic [255:0] broker_value_exponents;
    logic broker_cancel, broker_busy, broker_reset_required;
    logic broker_done_valid, broker_done_ready, broker_done_error;
    logic [7:0] broker_error_code;
    logic broker_context_valid, broker_context_ready;
    logic [4:0] broker_context_head;
    logic [31:0] broker_context_tag;
    logic [15:0] broker_context_query, broker_context_epoch;
    logic signed [7:0] broker_context_value_exponent;
    logic [2047:0] broker_context_data;
    logic signed [8:0] context_full_unit, response_full_unit;
    logic context_metadata_bad, tensor_metadata_bad, broker_tensor_error;
    logic spool_done_valid, spool_done_ready, spool_done_error;
    logic [31:0] spool_done_tag;
    logic [15:0] spool_done_query, spool_done_epoch;
    logic signed [9:0] spool_done_unit;
    logic spool_terminal_error, spool_metadata_bad, completion_bad;
    logic spool_context_ready, spool_terminal_ready;
    logic config_unknown, context_unknown, tensor_unknown, tensor_unit_unknown, broker_code_unknown;

    // Simulation detects four-state protocol violations. Physical inputs are
    // two-state; Genus must not replace $isunknown with constant-true failures.
    // All ordinary range, identity and full-width equality checks remain live.
    always_comb begin
        config_unknown = 0;
        context_unknown = 0;
        tensor_unknown = 0;
        tensor_unit_unknown = 0;
        broker_code_unknown = 0;
        // synthesis translate_off
        config_unknown = $isunknown({cfg_heads,cfg_streaming,cfg_total_keys,cfg_visible_keys,
                                      cfg_score_shifts,cfg_value_exponents,cfg_query,cfg_epoch,cfg_tag});
        context_unknown = $isunknown({broker_context_head,broker_context_tag,broker_context_query,
                                       broker_context_epoch,broker_context_value_exponent});
        tensor_unknown = $isunknown({tensor_rsp_kind,tensor_rsp_head,tensor_rsp_key,tensor_rsp_size,
                                      tensor_rsp_query,tensor_rsp_epoch,tensor_rsp_tag,tensor_rsp_data});
        tensor_unit_unknown = $isunknown(tensor_rsp_value_exponent);
        broker_code_unknown = $isunknown(broker_error_code);
        // synthesis translate_on
    end

    always_comb begin
        config_bad = spool_cfg_error !== 1'b0 ||
            config_unknown ||
            cfg_heads != 32'hffff_ffff || cfg_total_keys == 0 ||
            cfg_total_keys > 1024 || cfg_visible_keys == 0 ||
            cfg_visible_keys > cfg_total_keys || cfg_query > 2047;
        for (int head = 0; head < 32; head++) begin
            broker_value_exponents[head*8+:8] = cfg_value_exponents[(head/8)*9+:8];
            if ($signed(cfg_score_shifts[head*7+:7]) < -31 ||
                $signed(cfg_score_shifts[head*7+:7]) > 31) config_bad = 1;
        end
    end

    assign cfg_error = config_bad;
    assign cancel_now = cancel !== 1'b0;
    assign cfg_ready = rst_n && state == Idle && cancel === 1'b0 &&
                       broker_cfg_ready === 1'b1 && spool_cfg_ready === 1'b1;
    assign config_accept = cfg_valid === 1'b1 && cfg_ready === 1'b1;
    assign child_config_valid = config_accept && config_bad === 1'b0;
    assign broker_cancel = state == Active && (cancel_now || job_failed);
    assign busy = state != Idle;
    assign done_valid = rst_n && state == Complete;
    assign reset_required = state == Poisoned || job_failed ||
                            completion_needs_reset || broker_reset_required;

    assign context_full_unit = $signed(saved_value_exponents[broker_context_head[4:3]*9+:9]);
    assign response_full_unit = $signed(saved_value_exponents[tensor_rsp_head[4:3]*9+:9]);
    assign context_metadata_bad =
        context_unknown ||
        broker_context_tag !== saved_tag || broker_context_query !== saved_query ||
        broker_context_epoch !== saved_epoch ||
        broker_context_value_exponent !== context_full_unit[7:0];

    // No rsp_ready term: this checker cannot form an error/ready feedback cone.
    // Q/K exponent bits are unused. V is checked at full signed9 width before
    // the actual low8 and error reach the unchanged broker's accepted response.
    assign tensor_metadata_bad = tensor_rsp_valid === 1'b1 && state == Active && (
        tensor_unknown ||
        tensor_rsp_kind == 2'd3 || tensor_rsp_tag !== saved_tag ||
        tensor_rsp_query !== saved_query || tensor_rsp_epoch !== saved_epoch ||
        (tensor_rsp_kind === 2'd2 &&
         (tensor_unit_unknown || tensor_rsp_value_exponent !== response_full_unit)));
    assign broker_tensor_error = tensor_rsp_error !== 1'b0 || tensor_metadata_bad;

    assign broker_context_ready = state == Active && broker_context_valid === 1'b1 &&
                                  spool_context_ready;
    assign broker_done_ready = state == Active && !terminal_seen && spool_terminal_ready;
    assign spool_terminal_error = broker_done_error !== 1'b0 || job_failed || cancel_now;
    assign spool_done_ready = state == Active && terminal_seen;
    assign spool_metadata_bad = spool_done_tag !== saved_tag ||
                               spool_done_query !== saved_query || spool_done_epoch !== saved_epoch;
    assign completion_bad = job_failed || cancel_now || spool_done_error !== 1'b0 || spool_metadata_bad;

    tri_oracle_complete_head_broker broker (
        .clk,.rst_n,.cfg_valid(child_config_valid),.cfg_ready(broker_cfg_ready),
        .cfg_heads,.cfg_streaming,.cfg_total_keys,.cfg_visible_keys,.cfg_score_shifts,
        .cfg_value_exponents(broker_value_exponents),.cfg_query,.cfg_epoch,.cfg_tag,
        .cancel(broker_cancel),.tensor_req_valid,.tensor_req_ready,.tensor_req_kind,
        .tensor_req_head,.tensor_req_key,.tensor_req_query,.tensor_req_epoch,.tensor_req_tag,
        .tensor_rsp_valid,.tensor_rsp_ready,.tensor_rsp_error(broker_tensor_error),
        .tensor_rsp_kind,.tensor_rsp_head,.tensor_rsp_key,.tensor_rsp_size,
        .tensor_rsp_query,.tensor_rsp_epoch,.tensor_rsp_tag,
        .tensor_rsp_value_exponent(tensor_rsp_value_exponent[7:0]),.tensor_rsp_data,
        .context_valid(broker_context_valid),.context_ready(broker_context_ready),
        .context_head(broker_context_head),.context_query(broker_context_query),
        .context_epoch(broker_context_epoch),.context_tag(broker_context_tag),
        .context_value_exponent(broker_context_value_exponent),.context_data(broker_context_data),
        .all_contexts_collected,.done_valid(broker_done_valid),.done_ready(broker_done_ready),
        .done_error(broker_done_error),.reset_required(broker_reset_required),.busy(broker_busy),
        .error_code(broker_error_code),.fabric_load_valid,.fabric_load_error,.fabric_load_core,
        .fabric_load_kind,.fabric_load_addr,.fabric_load_data,.fabric_load_rows,.fabric_activation_reloaded,
        .fabric_cmd_valid,.fabric_cmd_ready,.fabric_cmd_clusters,.fabric_cmd_weight,.fabric_cmd_mask,
        .fabric_cmd_activation,.fabric_cmd_output,.fabric_cmd_accumulate,.fabric_cmd_reduce,
        .fabric_core_select,.fabric_out_valid,.fabric_out_ready,.fabric_out_slot,.fabric_out_data,
        .softmax_request,.softmax_response
    );

    tri_oracle_context_spool spool (
        .clk,.rst_n,.cfg_valid(child_config_valid),.cfg_ready(spool_cfg_ready),
        .cfg_tag,.cfg_query,.cfg_epoch,.cfg_spool_base,.cfg_code_base,
        .cfg_weight_units,.cfg_output_units,
        .context_valid(broker_context_valid && state == Active),.context_ready(spool_context_ready),
        .context_tag(broker_context_tag),.context_query(broker_context_query),
        .context_epoch(broker_context_epoch),.context_head(broker_context_head),
        .context_unit(context_full_unit),.context_data(broker_context_data),
        .broker_done_valid(broker_done_valid && state == Active && !terminal_seen),
        .broker_done_ready(spool_terminal_ready),.broker_done_error(spool_terminal_error),
        .done_valid(spool_done_valid),.done_ready(spool_done_ready),.done_error(spool_done_error),
        .done_tag(spool_done_tag),.done_query(spool_done_query),.done_epoch(spool_done_epoch),
        .done_unit(spool_done_unit),.wr_req_valid,.wr_req_ready,.wr_address,.wr_length,
        .wr_data_valid,.wr_data_ready,.wr_data,.wr_last,.wr_rsp_ready,.wr_rsp_valid,.wr_error,
        .rd_req_valid,.rd_req_ready,.rd_address,.rd_length,.rd_rsp_valid,.rd_rsp_ready,
        .rd_data,.rd_last,.rd_error,.cfg_error(spool_cfg_error)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            saved_value_exponents <= 0;
            saved_tag <= 0;
            saved_query <= 0;
            saved_epoch <= 0;
            job_failed <= 0;
            terminal_seen <= 0;
            completion_needs_reset <= 0;
            done_error <= 0;
            done_tag <= 0;
            done_query <= 0;
            done_epoch <= 0;
            done_unit <= 0;
            error_code <= 0;
        end else begin
            case (state)
                Idle: if (config_accept) begin
                    saved_value_exponents <= cfg_value_exponents;
                    saved_tag <= cfg_tag;
                    saved_query <= cfg_query;
                    saved_epoch <= cfg_epoch;
                    done_tag <= cfg_tag;
                    done_query <= cfg_query;
                    done_epoch <= cfg_epoch;
                    done_unit <= 0;
                    done_error <= config_bad;
                    job_failed <= 0;
                    terminal_seen <= 0;
                    completion_needs_reset <= 0;
                    error_code <= config_bad ? 8'h80 : 8'h00;
                    state <= config_bad ? Complete : Active;
                end
                Active: begin
                    if (cancel_now ||
                        (broker_context_valid === 1'b1 && broker_context_ready === 1'b1 && context_metadata_bad) ||
                        (tensor_rsp_valid === 1'b1 && tensor_rsp_ready === 1'b1 && tensor_metadata_bad)) begin
                        job_failed <= 1;
                        if (error_code == 0) begin
                            if (cancel_now) error_code <= 8'h01;
                            else if (broker_context_valid === 1'b1 && broker_context_ready === 1'b1 && context_metadata_bad)
                                error_code <= 8'h81;
                            else error_code <= tensor_rsp_kind === 2'd2 ? 8'h31 : 8'h10;
                        end
                    end
                    if (broker_done_valid === 1'b1 && broker_done_ready === 1'b1) begin
                        terminal_seen <= 1;
                        if (broker_done_error !== 1'b0) begin
                            job_failed <= 1;
                            if (error_code == 0)
                                error_code <= broker_code_unknown || broker_error_code == 0 ?
                                              8'hff : broker_error_code;
                        end
                    end
                    if (spool_done_valid === 1'b1 && spool_done_ready === 1'b1) begin
                        done_error <= completion_bad;
                        done_unit <= spool_done_unit;
                        completion_needs_reset <= completion_bad;
                        if (completion_bad) begin
                            job_failed <= 1;
                            if (error_code == 0) error_code <= cancel_now ? 8'h01 : 8'h83;
                        end
                        state <= Complete;
                    end
                end
                Complete: if (done_ready === 1'b1)
                    state <= completion_needs_reset ? Poisoned : Idle;
                Poisoned: ;
                default: begin
                    job_failed <= 1;
                    error_code <= 8'hff;
                    state <= Poisoned;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
