`timescale 1ns/1ps
// One token:32 held head rows,800 packed words plus32 fixed-unit words.
module tri_oracle_raw_context_row_packer (
    input logic clk,rst_n,clear,
    output logic clear_ready,
    input logic signed [8:0] zero_exponent,
    input logic row_valid,
    output logic row_ready,
    input logic [4:0] row_head,
    input logic [2047:0] row_data,
    input logic signed [7:0] row_value_exponent,
    output logic frame_ready,frame_error,
    output logic signed [8:0] context_exponent,
    output logic req_valid,
    input logic req_ready,
    output logic [9:0] req_word,
    output logic [63:0] req_data,
    input logic rsp_valid,rsp_error,
    output logic rsp_ready
);
    typedef enum logic [2:0] {Idle,Scan,Send,Wait,Reject} state_t;
    state_t state;
    logic [2:0] scan_index;
    logic [4:0] word_index,heads_received;
    logic [31:0] present,row_peak,scan_peak,magnitude;
    logic [1599:0] compact;
    logic [31:0] sample;
    logic overflow_seen,scan_overflow,have_nonzero;
    logic signed [8:0] common_unit,zero_latched,candidate_unit;

    function automatic logic signed [8:0] head_unit(
        input logic [31:0] peak,
        input logic signed [7:0] value_exponent
    );
        logic found;
        logic [63:0] threshold;
        head_unit=9'($signed(value_exponent));found=0;
        for(int power=-22;power<=9;power++)begin
            threshold=power<0 ? (64'd8322945>>(-power)) : (64'd8322945<<power);
            if(!found && {32'b0,peak}<=threshold)begin
                head_unit=9'($signed(value_exponent))+9'(power);found=1;
            end
        end
    endfunction

    always_comb begin
        compact='0;
        for(int lane=0;lane<64;lane++)
            compact[25*lane+:25]=row_data[32*lane+:25];
        scan_peak=row_peak;scan_overflow=overflow_seen;sample=0;magnitude=0;
        for(int lane=0;lane<8;lane++)begin
            sample=row_data[256*scan_index+32*lane+:32];
            magnitude=sample[31] ? -$unsigned(sample) : $unsigned(sample);
            if(magnitude>scan_peak)scan_peak=magnitude;
            if(sample[31:25]!={7{sample[24]}})scan_overflow=1;
        end
        candidate_unit=head_unit(row_peak,row_value_exponent);
    end
    assign clear_ready=state==Idle || state==Reject;
    assign row_ready=rst_n && row_valid &&
                     (state==Reject || (state==Wait && rsp_valid && !rsp_error && word_index==25));
    assign req_valid=rst_n && state==Send && row_valid;
    assign req_word=word_index==25 ? 10'd800+10'(row_head) : 10'(row_head)*10'd25+10'(word_index);
    assign req_data=word_index==25 ? {56'b0,row_value_exponent} : compact[64*word_index+:64];
    assign rsp_ready=rst_n && state==Wait;
    assign context_exponent=have_nonzero ? common_unit : zero_latched;

    always_ff @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            state<=Idle;scan_index<=0;word_index<=0;heads_received<=0;
            present<=0;row_peak<=0;overflow_seen<=0;have_nonzero<=0;
            common_unit<=0;zero_latched<=0;frame_ready<=0;frame_error<=0;
        end else if(clear && clear_ready)begin
            state<=Idle;scan_index<=0;word_index<=0;heads_received<=0;
            present<=0;row_peak<=0;overflow_seen<=0;have_nonzero<=0;
            common_unit<=0;zero_latched<=zero_exponent;frame_ready<=0;frame_error<=0;
        end else case(state)
            Idle:if(row_valid && !frame_ready && !frame_error)begin
                row_peak<=0;overflow_seen<=0;scan_index<=0;word_index<=0;
                if(present[row_head])begin frame_error<=1;state<=Reject;end
                else state<=Scan;
            end
            Scan:if(row_valid)begin
                row_peak<=scan_peak;overflow_seen<=scan_overflow;
                if(scan_index==7)begin
                    if(scan_overflow)begin frame_error<=1;state<=Reject;end
                    else state<=Send;
                end else scan_index<=scan_index+3'd1;
            end
            Send:if(req_valid && req_ready)state<=Wait;
            Wait:if(rsp_valid)begin
                if(rsp_error)begin frame_error<=1;state<=Reject;end
                else if(word_index==25)begin
                    present<=present | (32'b1<<row_head);
                    heads_received<=heads_received+5'd1;
                    frame_ready<=heads_received==31;
                    if(row_peak!=0)begin
                        if(!have_nonzero || candidate_unit>common_unit)common_unit<=candidate_unit;
                        have_nonzero<=1;
                    end
                    state<=Idle;
                end else begin word_index<=word_index+5'd1;state<=Send;end
            end
            Reject:if(row_valid)state<=Idle;
            default:begin frame_error<=1;state<=Reject;end
        endcase
    end
endmodule
