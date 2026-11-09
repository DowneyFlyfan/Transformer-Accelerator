`timescale 1ns/1ps
// Full-capacity memory/compute basis for the core in Tri-Oracle Fig.31.6.2.
// Capacities from paper: weights 8KB, inputs 8KB, outputs 2KB, auxiliary 1KB.
// Local choices: small hierarchical inferred banks, auxiliary mask storage,
// 32-bit wrapping accumulators, command/load ports, four-stage compute pipe.
// Inferred arrays require a real memory implementation before physical claims.
// Memory contents survive reset; load source banks and overwrite a destination
// before requesting accumulation. Completion and read results are pulse ports.
// This does not yet include prediction units, dual-mode output reduction,
// normalization, instruction fetch/decode or the interconnect.
module tri_oracle_memory_compute (
    input wire clk,
    input wire rst_n,
    input wire load_valid,
    input wire [1:0] load_kind, // 0=weights, 1=activation, 2=mask
    input wire [9:0] load_addr,
    input wire [2047:0] load_data,
    input wire [31:0] load_row_enable, // Weight-only 64-bit row write enables.
    output reg load_error,
    input wire cmd_valid,
    output wire cmd_ready,
    input wire [4:0] cmd_weight,
    input wire [9:0] cmd_activation,
    input wire [4:0] cmd_mask,
    input wire [3:0] cmd_output,
    input wire cmd_accumulate,
    output reg done_valid,
    output reg [3:0] done_output,
    input wire read_valid,
    input wire [3:0] read_output,
    output reg result_valid,
    output reg [1023:0] result_data
);
    wire [2047:0] bank_weights;
    wire [63:0] bank_inputs [0:31];
    wire [255:0] bank_mask;
    wire [1023:0] bank_accumulator,bank_output;
    wire [2047:0] unused_weight_second;
    wire [2047:0] unused_input_second;
    wire [255:0] unused_mask_second;
    reg [2047:0] read_weights;
    reg [63:0] read_activation;
    reg [255:0] read_mask;
    reg read_command_valid;
    reg [3:0] read_slot;
    reg read_accumulate;
    reg [3:0] slot_pipe [0:3];
    reg [3:0] accumulate_pipe;
    wire array_ready,array_valid;
    wire [607:0] array_sums;
    wire [2047:0] repeated_activation={32{read_activation}};
    integer stage;
    assign cmd_ready=array_ready && !load_valid;
    genvar bank;
    generate
        for(bank=0;bank<32;bank=bank+1) begin: storage
            tri_oracle_word_bank weights (
                .clk(clk),.rst_n(rst_n),
                .write_enable(load_valid && load_kind==0 && load_addr<32 && load_row_enable[bank]),
                .write_addr(load_addr[4:0]),.write_data(load_data[bank*64+:64]),
                .read_addr(cmd_weight),.read_data(bank_weights[bank*64+:64]),
                .second_addr(cmd_weight),.second_data(unused_weight_second[bank*64+:64])
            );
            tri_oracle_word_bank inputs (
                .clk(clk),.rst_n(rst_n),
                .write_enable(load_valid && load_kind==1 && load_addr[9:5]==bank),
                .write_addr(load_addr[4:0]),.write_data(load_data[63:0]),
                .read_addr(cmd_activation[4:0]),.read_data(bank_inputs[bank]),
                .second_addr(cmd_activation[4:0]),.second_data(unused_input_second[bank*64+:64])
            );
            wire [31:0] sum={{13{array_sums[bank*19+18]}},array_sums[bank*19+:19]};
            tri_oracle_word_bank #(.DATA_W(32),.ADDR_W(4)) outputs (
                .clk(clk),.rst_n(rst_n),.write_enable(array_valid),
                .write_addr(slot_pipe[3]),
                .write_data(accumulate_pipe[3] ? bank_accumulator[bank*32+:32]+sum : sum),
                .read_addr(slot_pipe[3]),.read_data(bank_accumulator[bank*32+:32]),
                .second_addr(read_output),.second_data(bank_output[bank*32+:32])
            );
        end
        for(bank=0;bank<4;bank=bank+1) begin: auxiliary
            tri_oracle_word_bank masks (
                .clk(clk),.rst_n(rst_n),
                .write_enable(load_valid && load_kind==2 && load_addr<32),
                .write_addr(load_addr[4:0]),.write_data(load_data[bank*64+:64]),
                .read_addr(cmd_mask),.read_data(bank_mask[bank*64+:64]),
                .second_addr(cmd_mask),.second_data(unused_mask_second[bank*64+:64])
            );
        end
    endgenerate
    tri_oracle_pe_array compute (
        .clk(clk),.rst_n(rst_n),.in_valid(read_command_valid),
        .in_ready(array_ready),.operand_a(repeated_activation),
        .operand_b(read_weights),.lane_enable(read_mask),
        .out_valid(array_valid),.out_ready(1'b1),.out_sums(array_sums)
    );
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            read_command_valid<=0;load_error<=0;done_valid<=0;
            done_output<=0;result_valid<=0;result_data<=0;
            read_slot<=0;read_accumulate<=0;accumulate_pipe<=0;
            for(stage=0;stage<4;stage=stage+1) slot_pipe[stage]<=0;
        end else begin
            load_error<=0;
            if(load_valid) begin
                case(load_kind)
                    0: if(load_addr>=32) load_error<=1;
                    1: begin end
                    2: if(load_addr>=32) load_error<=1;
                    default: load_error<=1;
                endcase
            end
            read_command_valid<=cmd_valid && cmd_ready;
            if(cmd_valid && cmd_ready) begin
                read_weights<=bank_weights;
                read_activation<=bank_inputs[cmd_activation[9:5]];
                read_mask<=bank_mask;
                read_slot<=cmd_output;
                read_accumulate<=cmd_accumulate;
            end
            slot_pipe[0]<=read_slot;
            accumulate_pipe[0]<=read_accumulate;
            for(stage=1;stage<4;stage=stage+1) begin
                slot_pipe[stage]<=slot_pipe[stage-1];
                accumulate_pipe[stage]<=accumulate_pipe[stage-1];
            end
            done_valid<=array_valid;
            if(array_valid) begin
                done_output<=slot_pipe[3];

            end
            // Read during a write to the same address returns the old word.
            result_valid<=read_valid;
            if(read_valid) result_data<=bank_output;
        end
    end
endmodule
