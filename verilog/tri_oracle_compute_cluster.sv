`timescale 1ns/1ps
// Four-core compute hierarchy and aggregator basis from Tri-Oracle Fig.31.6.2.
// Local choices: lockstep issue, 16 outstanding destinations, ordered output,
// 2KB aggregate bank, 32-bit wrapping sums, arithmetic-shift mean rounding.
// This is not the complete paper cluster: prediction and instruction control
// remain separate. Inferred storage still requires physical memory mapping.
module tri_oracle_compute_cluster #(
  parameter int MERGE_FEATURES=0,
  parameter bit CORE_STRIP_PREDICTOR=0,
  localparam int SIGN_WIDTH=MERGE_FEATURES==0 ? 1 : MERGE_FEATURES
) (
    input wire clk,rst_n,load_valid,
    input wire [1:0] load_core,load_kind,
    input wire [9:0] load_addr,
    input wire [2047:0] load_data,
    input wire [31:0] load_row_enable,
    output wire load_error,
    input wire cmd_valid,
    output wire cmd_ready,
    input wire [4:0] cmd_weight,cmd_mask,
    input wire [9:0] cmd_activation,
    input wire [3:0] cmd_output,
    input wire cmd_accumulate,
    input wire [1:0] cmd_reduce, // 0=sum, 1=max, 2=mean, 3=invalid
    output wire out_valid,
    input wire out_ready,
    output wire [3:0] out_output,
    output wire [1023:0] out_data,
    input wire [SIGN_WIDTH-1:0] merge_sign_data,
    input wire [12:0] merge_sign_control,
    output wire [23:0] merge_sign_counts,
    input logic strip_rst_n,
    input logic [530:0] strip_request,
    output logic [111:0] strip_response
);
    wire [587:0] core_strip_requests;
    wire [159:0] core_strip_responses;
    if (CORE_STRIP_PREDICTOR) begin : strip_group
      tri_oracle_cluster_strip448 route (
        .request(strip_request), .response(strip_response),
        .core_requests(core_strip_requests), .core_responses(core_strip_responses)
      );
    end else begin : no_strip_group
      assign core_strip_requests='0;
      assign strip_response='0;
    end

    if (MERGE_FEATURES!=0) begin : aggregator_sign
      tri_oracle_aggregator_sign447 #(
        .FEATURES(MERGE_FEATURES), .COMPILED_SIGN_BANK(1'b0)
      ) similarity (
        .clk, .sign_data(merge_sign_data), .control(merge_sign_control), .counts(merge_sign_counts)
      );
    end else begin : no_sign_bank
      assign merge_sign_counts='0;
    end

    wire [3:0] ready,done,result_valid,load_errors;
    wire [15:0] done_slots;
    wire [4095:0] result_words;
    wire done_aligned=(&done) && done_slots[7:4]==done_slots[3:0] &&
                     done_slots[11:8]==done_slots[3:0] && done_slots[15:12]==done_slots[3:0];
    reg [1023:0] aggregate_memory[0:15];
    reg [15:0] reserved,complete;
    reg [1:0] reduce_mode[0:15];
    reg [3:0] tag_queue[0:15];
    reg [3:0] head,tail,read_slot;
    reg [4:0] count;
    wire issue=cmd_valid && cmd_ready;
    wire retire=out_valid && out_ready;
    integer line;
    assign load_error=|load_errors;
    assign cmd_ready=(&ready) && !load_valid && count<16 &&
                     !reserved[cmd_output] && cmd_reduce!=3;
    assign out_output=tag_queue[head];
    assign out_valid=(count!=0) && complete[out_output];
    assign out_data=aggregate_memory[out_output];
    function automatic [31:0] reduce_four(input signed [31:0] a,b,c,d,input [1:0] mode);
        reg signed [33:0] total;
        reg signed [31:0] ab,cd;
        begin
            total=$signed({{2{a[31]}},a})+$signed({{2{b[31]}},b})+
                  $signed({{2{c[31]}},c})+$signed({{2{d[31]}},d});
            ab=a>b?a:b;cd=c>d?c:d;
            case(mode)
                1:reduce_four=ab>cd?ab:cd;
                2:reduce_four=32'(total>>>2);
                default:reduce_four=total[31:0];
            endcase
        end
    endfunction
    for(genvar core=0;core<4;core=core+1)begin: cores
        tri_oracle_inferred_strip_core448 #(.CORE_STRIP_PREDICTOR(CORE_STRIP_PREDICTOR)) unit (
        .strip_rst_n, .strip_request(core_strip_requests[147*core+:147]),
            .strip_response(core_strip_responses[40*core+:40]),
            .clk(clk),.rst_n(rst_n),.load_valid(load_valid && load_core==2'(core)),
            .load_kind(load_kind),.load_addr(load_addr),.load_data(load_data),
            .load_row_enable(load_row_enable),
            .load_error(load_errors[core]),.cmd_valid(issue),.cmd_ready(ready[core]),
            .cmd_weight(cmd_weight),.cmd_activation(cmd_activation),.cmd_mask(cmd_mask),
            .cmd_output(cmd_output),.cmd_accumulate(cmd_accumulate),
            .done_valid(done[core]),.done_output(done_slots[core*4+:4]),
            .read_valid(done_aligned),.read_output(done_slots[0+:4]),
            .result_valid(result_valid[core]),.result_data(result_words[core*1024+:1024])
        );
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin
            reserved<=0;complete<=0;head<=0;tail<=0;count<=0;read_slot<=0;
        end else begin
            case({issue,retire})
                2'b10:count<=count+1'b1;
                2'b01:count<=count-1'b1;
                default:count<=count;
            endcase
            if(issue)begin
                reserved[cmd_output]<=1;
                reduce_mode[cmd_output]<=cmd_reduce;
                tag_queue[tail]<=cmd_output;
                tail<=tail+1'b1;
            end
            if(done_aligned)read_slot<=done_slots[0+:4];
            if(&result_valid)begin
                for(line=0;line<32;line=line+1)
                    aggregate_memory[read_slot][line*32+:32]<=reduce_four(
                        $signed(result_words[line*32+:32]),
                        $signed(result_words[1024+line*32+:32]),
                        $signed(result_words[2048+line*32+:32]),
                        $signed(result_words[3072+line*32+:32]),reduce_mode[read_slot]);
                complete[read_slot]<=1;
            end
            if(retire)begin
                complete[out_output]<=0;reserved[out_output]<=0;head<=head+1'b1;
            end
        end
    end
endmodule

/* verilator lint_off DECLFILENAME */
module tri_oracle_inferred_strip_core448 #(
    parameter bit CORE_STRIP_PREDICTOR=0
) (
    input wire clk,
    input wire rst_n,
    input wire load_valid,
    input wire [1:0] load_kind, // 0=weights, 1=activation, 2=mask
    input wire [9:0] load_addr,
    input wire [2047:0] load_data,
    input wire [31:0] load_row_enable, // Weight-only 64-bit row write enables.
    output wire load_error,
    input wire cmd_valid,
    output wire cmd_ready,
    input wire [4:0] cmd_weight,
    input wire [9:0] cmd_activation,
    input wire [4:0] cmd_mask,
    input wire [3:0] cmd_output,
    input wire cmd_accumulate,
    output wire done_valid,
    output wire [3:0] done_output,
    input wire read_valid,
    input wire [3:0] read_output,
    output wire result_valid,
    output wire [1023:0] result_data,
    input logic strip_rst_n,
    input logic [146:0] strip_request,
    output logic [39:0] strip_response
);
    tri_oracle_memory_compute compute (.*);
    if (CORE_STRIP_PREDICTOR) begin : strip
        tri_oracle_core_strip448 predict (
            .clk, .rst_n(strip_rst_n), .request(strip_request), .response(strip_response)
        );
    end else begin : no_strip
        assign strip_response='0;
    end
endmodule
/* verilator lint_on DECLFILENAME */
