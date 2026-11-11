`timescale 1ns/1ps
// Share the weight-attention core's input banks between matrix and vector work.
// After reset or softmax writes, the scheduler reloads the next tile before
// acknowledging activation_reloaded. Result memory is independent of the handoff.
module tri_oracle_wac_imem_owner (
    input  logic clk,
    input  logic rst_n,
    input  logic compute_accepted,
    input  logic compute_done,
    input  logic softmax_request,
    input  logic softmax_start,
    input  logic softmax_end,
    input  logic softmax_wrote_input,
    input  logic activation_reloaded,
    output logic load_ready,
    output logic compute_enabled,
    output logic softmax_configure,
    output logic softmax_owns_input,
    output logic activation_reload_required
);
    // One operand fetch, four array stages, one writeback and one completion.
    logic [2:0] outstanding;

    assign softmax_configure = rst_n && !softmax_owns_input && outstanding == 0;
    assign load_ready = rst_n && !softmax_request && !softmax_owns_input;
    assign compute_enabled = load_ready && !activation_reload_required;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            outstanding <= '0;
            softmax_owns_input <= 1'b0;
            // The memory can retain softmax scratch data across a controller reset.
            activation_reload_required <= 1'b1;
        end else begin
            case ({compute_accepted, compute_done})
                2'b10: outstanding <= outstanding + 3'd1;
                2'b01: outstanding <= outstanding - 3'd1;
                default: ;
            endcase

            if (softmax_start) softmax_owns_input <= 1'b1;
            else if (softmax_end) softmax_owns_input <= 1'b0;

            if (softmax_owns_input && softmax_wrote_input) activation_reload_required <= 1'b1;
            else if (load_ready && activation_reloaded) activation_reload_required <= 1'b0;
        end
    end
endmodule
