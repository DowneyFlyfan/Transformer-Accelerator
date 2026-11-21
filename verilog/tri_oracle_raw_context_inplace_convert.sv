`timescale 1ns/1ps
// Compact a complete single-token raw frame into its first256words in place.
module tri_oracle_raw_context_inplace_convert (
    input logic clk,rst_n,start_valid,
    output logic start_ready,
    input logic signed [8:0] context_exponent,
    output logic done_valid,done_error,
    input logic done_ready,
    output logic req_valid,req_write,
    input logic req_ready,
    output logic [9:0] req_word,
    output logic [63:0] req_data,
    input logic rsp_valid,rsp_error,
    output logic rsp_ready,
    input logic [63:0] rsp_data
);
    typedef enum logic [3:0] {Idle,ReadUnit,WaitUnit,ReadRaw,WaitRaw,WriteCodes,WaitWrite,Done} state_t;
    state_t state;
    logic [4:0] head,raw_count;
    logic [2:0] group_index;
    logic [8:0] fill_bits;
    logic [255:0] window;
    logic signed [8:0] unit_latched;
    logic signed [9:0] transfer;
    logic scale_right;
    logic [4:0] scale_shift;
    logic [63:0] codes;
    assign transfer=$signed({{2{rsp_data[7]}},rsp_data[7:0]})-$signed({unit_latched[8],unit_latched});
    assign start_ready=rst_n && state==Idle;
    assign done_valid=state==Done;
    assign req_valid=rst_n && (state==ReadUnit || state==ReadRaw || state==WriteCodes);
    assign req_write=state==WriteCodes;
    assign req_word=state==ReadUnit ? 10'd800+10'(head) :
                    state==WriteCodes ? {2'b0,head,group_index} : 10'(head)*10'd25+10'(raw_count);
    assign req_data=codes;
    assign rsp_ready=rst_n && (state==WaitUnit || state==WaitRaw || state==WaitWrite);
    for(genvar lane=0;lane<8;lane++)begin:scales
        tri_oracle_attention_projection_scale_quotient_first scale (
            .accumulator({{7{window[25*lane+24]}},window[25*lane+:25]}),
            .scale_right,.scale_shift,.projection_code(codes[8*lane+:8])
        );
    end
    always_ff @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            state<=Idle;head<=0;raw_count<=0;group_index<=0;fill_bits<=0;
            window<=0;unit_latched<=0;scale_right<=0;scale_shift<=0;done_error<=0;
        end else case(state)
            Idle:if(start_valid)begin
                unit_latched<=context_exponent;head<=0;raw_count<=0;group_index<=0;
                fill_bits<=0;window<=0;done_error<=0;state<=ReadUnit;
            end
            ReadUnit:if(req_ready)state<=WaitUnit;
            WaitUnit:if(rsp_valid)begin
                if(rsp_error || rsp_data[63:8]!=0 || transfer< -31 || transfer>31)begin
                    done_error<=1;state<=Done;
                end else begin
                    scale_right<=transfer<0;scale_shift<=transfer<0 ? 5'(-transfer) : 5'(transfer);
                    state<=ReadRaw;
                end
            end
            ReadRaw:if(req_ready)state<=WaitRaw;
            WaitRaw:if(rsp_valid)begin
                if(rsp_error || raw_count>=25 || fill_bits>192)begin done_error<=1;state<=Done;end
                else begin
                    window<=window | (256'(rsp_data)<<fill_bits);
                    fill_bits<=fill_bits+9'd64;raw_count<=raw_count+5'd1;
                    state<=fill_bits>=136 ? WriteCodes : ReadRaw;
                end
            end
            WriteCodes:if(req_ready)state<=WaitWrite;
            WaitWrite:if(rsp_valid)begin
                if(rsp_error || fill_bits<200)begin done_error<=1;state<=Done;end
                else begin
                    window<=window>>200;fill_bits<=fill_bits-9'd200;
                    if(group_index==7)begin
                        if(raw_count!=25 || fill_bits!=200)begin done_error<=1;state<=Done;end
                        else if(head==31)state<=Done;
                        else begin
                            head<=head+5'd1;raw_count<=0;group_index<=0;
                            window<=0;fill_bits<=0;state<=ReadUnit;
                        end
                    end else begin group_index<=group_index+3'd1;state<=ReadRaw;end
                end
            end
            Done:if(done_ready)state<=Idle;
            default:begin done_error<=1;state<=Done;end
        endcase
    end
endmodule
