`timescale 1ns/1ps
module tri_oracle_wac_outlier_sign_tb;
    logic valid = 0;
    logic [127:0] normalized = '0;
    logic response_valid;
    logic [7:0] outliers, negative;

    tri_oracle_wac_outlier_sign dut (.*);

    initial begin
        for (int code = -32768; code <= 32767; code++) begin
            valid = 1;
            for (int lane = 0; lane < 8; lane++)
                normalized[16*lane +: 16] = 16'(code + 97*lane);
            #1;
            if (response_valid !== 1'b1) $fatal(1, "OUTLIER_RESPONSE_MISSING");
            for (int lane = 0; lane < 8; lane++) begin
                automatic int value = int'($signed(normalized[16*lane +: 16]));
                automatic int magnitude = value < 0 ? -value : value;
                if (outliers[lane] !== (magnitude > 3*256) || negative[lane] !== (value < 0))
                    $fatal(1, "OUTLIER_LANE_MISMATCH lane=%0d value=%0d", lane, value);
            end
        end
        valid = 0;
        #1;
        if ({response_valid, outliers, negative} !== '0) $fatal(1, "OUTLIER_IDLE_RESPONSE");
        $display("WAC_OUTLIER_SIGN_PASS lane_codes=524288");
        $finish;
    end
endmodule
