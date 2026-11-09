`timescale 1ns/1ps
// Eight signed16 learned-scale products, rounded ties away and saturated to signed8.
// norm_code*gamma_code / 2^shift is the local represented output-code contract.
// Two elastic stages retain data and metadata under arbitrary output backpressure.
module tri_oracle_affine_quantizer (
    input logic clk,rst_n,in_valid,
    output logic in_ready,
    input logic in_last,in_error,
    input logic [31:0] in_tag,
    input logic [9:0] in_index,
    input logic [3:0] in_count,
    input logic [127:0] in_norm_q8,in_gamma,
    input logic [5:0] in_shift,
    input logic [7:0] in_outlier_mask,
    output logic out_valid,
    input logic out_ready,
    output logic out_last,out_error,
    output logic [31:0] out_tag,
    output logic [9:0] out_index,
    output logic [3:0] out_count,
    output logic [127:0] out_norm_q8,
    output logic [7:0] out_outlier_mask,
    output logic [63:0] out_activation
);
    logic product_valid,product_ready,output_ready;
    logic product_last,product_error;
    logic [31:0] product_tag;
    logic [9:0] product_index;
    logic [3:0] product_count;
    logic [127:0] product_norm;
    logic [7:0] product_outliers;
    logic [5:0] product_shift;
    logic signed [31:0] product [0:7];

    function automatic logic signed [31:0] multiply16(
        input logic signed [15:0] normalized,gamma
    );
        logic signed [31:0] left,right;
        begin
            left={{16{normalized[15]}},normalized};
            right={{16{gamma[15]}},gamma};
            // The full signed16 product lies within[-2^30,2^30].
            multiply16=left*right;
        end
    endfunction
    function automatic logic [7:0] quantize8(
        input logic signed [31:0] value,
        input logic [5:0] shift
    );
        logic negative;
        logic [63:0] magnitude,bias,rounded;
        begin
            negative=value<0;
            magnitude=negative ? -64'($signed(value)) : 64'($signed(value));
            bias=shift==0 ? 64'd0 : (64'd1 << (shift-6'd1));
            // For shift<=63, bias<=2^62; the bounded product cannot overflow64 bits.
            rounded=(magnitude+bias) >> shift;
            if(negative && rounded>=64'd128) quantize8=8'h80;
            else if(!negative && rounded>64'd127) quantize8=8'h7f;
            else if(negative) quantize8=-8'(rounded);
            else quantize8=8'(rounded);
        end
    endfunction
    always_comb begin
        output_ready=!out_valid || out_ready;
        product_ready=!product_valid || output_ready;
        in_ready=product_ready;
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            product_valid<=0;product_last<=0;product_error<=0;product_tag<='0;
            product_index<='0;product_count<='0;product_norm<='0;
            product_outliers<='0;product_shift<='0;
            out_valid<=0;out_last<=0;out_error<=0;out_tag<='0;out_index<='0;
            out_count<='0;out_norm_q8<='0;out_outlier_mask<='0;out_activation<='0;
            for(int lane=0;lane<8;lane++) product[lane]<='0;
        end else begin
            if(output_ready) begin
                out_valid<=product_valid;
                if(product_valid) begin
                    out_last<=product_last;
                    out_error<=product_error;
                    out_tag<=product_tag;
                    out_index<=product_index;
                    out_count<=product_count;
                    out_norm_q8<=product_norm;
                    out_outlier_mask<=product_outliers;
                    for(int lane=0;lane<8;lane++)
                        out_activation[lane*8+:8]<=product_error ? 8'b0 :
                            quantize8(product[lane],product_shift);
                end
            end
            if(product_ready) begin
                product_valid<=in_valid;
                if(in_valid) begin
                    product_tag<=in_tag;
                    product_index<=in_index;
                    product_last<=in_last || in_error || in_count!=4'd8;
                    product_error<=in_error || in_count!=4'd8;
                    product_count<=in_error || in_count!=4'd8 ? 4'd0 : 4'd8;
                    product_norm<=in_error || in_count!=4'd8 ? 128'b0 : in_norm_q8;
                    product_outliers<=in_error || in_count!=4'd8 ? 8'b0 : in_outlier_mask;
                    product_shift<=in_shift;
                    for(int lane=0;lane<8;lane++) begin
                        product[lane]<=multiply16($signed(in_norm_q8[lane*16+:16]),
                            $signed(in_gamma[lane*16+:16]));
                    end
                end
            end
        end
    end
endmodule
