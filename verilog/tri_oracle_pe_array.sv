`timescale 1ns/1ps
// Compute-array basis for Tri-Oracle Figure 31.6.2: 32 lines x 8 products.
// Signed eight-bit products, one dot product per line and accepted cycle.
// Local implementation choices: balanced registered reduction tree,
// full-precision sum, packed operand interface and global pipeline stall.
// The paper does not specify this pipeline, interface or accumulator format.
// Dual-mode output mapping, memories and cluster accumulation are separate
// integration requirements; this module does not implement a complete core.
module tri_oracle_pe_array #(
    parameter integer LINES=32,
    parameter integer LANES=8,
    parameter integer DATA_W=8,
    parameter integer STAGES=$clog2(LANES),
    parameter integer SUM_W=2*DATA_W+STAGES
) (
    input wire clk,
    input wire rst_n,
    input wire in_valid,
    output wire in_ready,
    input wire [LINES*LANES*DATA_W-1:0] operand_a,
    input wire [LINES*LANES*DATA_W-1:0] operand_b,
    input wire [LINES*LANES-1:0] lane_enable,
    output wire out_valid,
    input wire out_ready,
    output wire [LINES*SUM_W-1:0] out_sums
);
    reg [STAGES:0] valid;
    assign out_valid=valid[STAGES];
    assign in_ready=!valid[STAGES] || out_ready;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) valid <= {(STAGES+1){1'b0}};
        else if(in_ready) valid <= {valid[STAGES-1:0],in_valid};
    end
    for(genvar p=0;p<LINES*LANES;p=p+1) begin: product
        reg signed [2*DATA_W-1:0] value;
        always @(posedge clk)
            if(in_ready && in_valid) begin
                if(lane_enable[p])
                    value <= $signed(operand_a[p*DATA_W +: DATA_W]) *
                             $signed(operand_b[p*DATA_W +: DATA_W]);
                else value <= {(2*DATA_W){1'b0}};
            end
    end
    for(genvar level=0;level<STAGES;level=level+1) begin: reduction
        localparam integer COUNT=LANES>>(level+1);
        for(genvar line=0;line<LINES;line=line+1) begin: row
            for(genvar lane=0;lane<COUNT;lane=lane+1) begin: sum
                reg signed [2*DATA_W+level:0] value;
                if(level==0) begin: leaf
                    always @(posedge clk)
                        if(in_ready && valid[level])
                            value <= $signed({product[line*LANES+2*lane].value[2*DATA_W-1],
                                              product[line*LANES+2*lane].value}) +
                                     $signed({product[line*LANES+2*lane+1].value[2*DATA_W-1],
                                              product[line*LANES+2*lane+1].value});
                end else begin: branch
                    always @(posedge clk)
                        if(in_ready && valid[level])
                            value <= $signed({reduction[level-1].row[line].sum[2*lane].value[2*DATA_W+level-1],
                                              reduction[level-1].row[line].sum[2*lane].value}) +
                                     $signed({reduction[level-1].row[line].sum[2*lane+1].value[2*DATA_W+level-1],
                                              reduction[level-1].row[line].sum[2*lane+1].value});
                end
            end
        end
    end
    for(genvar line=0;line<LINES;line=line+1) begin: result
        assign out_sums[line*SUM_W +: SUM_W]=reduction[STAGES-1].row[line].sum[0].value;
    end
endmodule
