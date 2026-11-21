`timescale 1ns/1ps
// Hold each native64-lane result through its eighth scan cycle.
module tri_oracle_context_unit_finder (
    input logic clk,rst_n,row_valid,
    output logic row_ready,
    input logic [2047:0] row_data,
    input logic signed [7:0] row_value_exponent,
    input logic [5:0] row_index,
    input logic [17:0] zero_exponents,
    output logic out_valid,out_error,
    input logic out_ready,
    output logic [17:0] out_exponents
);
    logic [2:0] word_index;
    logic [31:0] row_peak,batch_peak,magnitude;
    logic signed [31:0] sample;
    logic signed [8:0] units[2],next_unit;
    logic [1:0] nonzero_seen;
    logic [63:0] present;
    logic [5:0] rows_received;
    logic [17:0] zero_latched;

    function automatic logic signed [8:0] head_unit(
        input logic [31:0] peak,
        input logic signed [7:0] value_exponent
    );
        logic found;
        logic [63:0] threshold;
        // Minimal d satisfying peak<=127*65535*2**d. For negative d,
        // integer peak<=floor(127*65535/2**(-d)) is exactly equivalent.
        head_unit=9'($signed(value_exponent));
        found=0;
        for(int power=-22;power<=9;power++)begin
            threshold=power<0 ? (64'd8322945>>(-power)) : (64'd8322945<<power);
            if(!found && {32'b0,peak}<=threshold)begin
                head_unit=9'($signed(value_exponent))+9'(power);
                found=1;
            end
        end
    endfunction

    always_comb begin
        batch_peak=row_peak;
        magnitude='0;
        sample='0;
        for(int lane=0;lane<8;lane++)begin
            sample=$signed(row_data[256*word_index+32*lane+:32]);
            magnitude=sample[31] ? -$unsigned(sample) : $unsigned(sample);
            if(magnitude>batch_peak)batch_peak=magnitude;
        end
        next_unit=head_unit(batch_peak,row_value_exponent);
    end
    assign row_ready=rst_n && row_valid && !out_valid && word_index==7;
    assign out_exponents={nonzero_seen[1] ? units[1] : zero_latched[17:9],
                          nonzero_seen[0] ? units[0] : zero_latched[8:0]};

    always_ff @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            word_index<=0;row_peak<=0;present<=0;rows_received<=0;
            units[0]<=0;units[1]<=0;nonzero_seen<=0;zero_latched<=0;
            out_valid<=0;out_error<=0;
        end else if(out_valid && out_ready)begin
            word_index<=0;row_peak<=0;present<=0;rows_received<=0;
            units[0]<=0;units[1]<=0;nonzero_seen<=0;
            out_valid<=0;out_error<=0;
        end else if(row_valid && !out_valid)begin
            if(rows_received==0 && word_index==0)zero_latched<=zero_exponents;
            if(word_index==7)begin
                word_index<=0;row_peak<=0;
                if(present[row_index])begin out_valid<=1;out_error<=1;end
                else begin
                    present<=present | (64'b1<<row_index);
                    rows_received<=rows_received+6'd1;
                    if(batch_peak!=0)begin
                        nonzero_seen[row_index[5]]<=1;
                        if(!nonzero_seen[row_index[5]] || next_unit>units[row_index[5]])
                            units[row_index[5]]<=next_unit;
                    end
                    if(rows_received==63)out_valid<=1;
                end
            end else begin word_index<=word_index+3'd1;row_peak<=batch_peak;end
        end
    end
endmodule
