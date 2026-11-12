`timescale 1ns/1ps

module tri_oracle_ranked_sign_slots_tb #(
    parameter int SLOT_BITS = 5
);
    localparam int ENTRIES = 1 << SLOT_BITS;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic frame_start = 0, frame_enable = 0;
    logic [8:0] frame_strips = 0;
    logic observe_valid = 0, observe_first = 0, observe_active = 0;
    logic [7:0] observe_strip = 0;
    logic build = 0, map_ready, lookup_valid;
    logic [7:0] lookup_strip = 0;
    logic [SLOT_BITS-1:0] lookup_slot;

    logic [15:0] norm_codes[16*256*8];
    int counts[256];
    bit reference_selected[256];
    int verified_frames = 0, max_build_cycles = 0;

    tri_oracle_ranked_sign_slots #(.SLOT_BITS(SLOT_BITS)) dut (.*);

    task automatic start_frame(input int strips, input bit enabled);
        frame_start = 1;
        frame_strips = 9'(strips);
        frame_enable = enabled;
        @(negedge clk);
        frame_start = 0;
        if (map_ready !== !enabled)
            $fatal(1, "SLOT_FRAME_READY enabled=%b", enabled);
    endtask

    task automatic send_strip(input int strip, input bit first, active, finish_build = 0);
        observe_valid = 1;
        observe_first = first;
        observe_active = active;
        observe_strip = 8'(strip);
        build = finish_build;
        @(negedge clk);
        observe_valid = 0;
        build = 0;
    endtask

    task automatic check_frame(input int strips, input bit enabled);
        int count, delay_cycles;
        count = 0;
        delay_cycles = 0;
        while (!map_ready && delay_cycles < 272) begin
            @(negedge clk);
            delay_cycles++;
        end
        if (!map_ready || delay_cycles > 271 || (!enabled && delay_cycles != 0))
            $fatal(1, "SLOT_BUILD_BUDGET cycles=%0d", delay_cycles);
        if (delay_cycles > max_build_cycles) max_build_cycles = delay_cycles;
        foreach (reference_selected[strip]) reference_selected[strip] = 0;
        if (enabled)
            for (int uses = 16; uses >= 2; uses--)
                for (int strip = 0; strip < strips; strip++)
                    if (counts[strip] == uses && count < ENTRIES) begin
                        reference_selected[strip] = 1;
                        count++;
                    end
        count = 0;
        for (int strip = 0; strip < 256; strip++) begin
            lookup_strip = 8'(strip);
            #1ps;
            if (lookup_valid !== reference_selected[strip] ||
                (lookup_valid && lookup_slot !== SLOT_BITS'(count)))
                $fatal(1, "SLOT_MAP strip=%0d uses=%0d wanted=%b slot=%0d",
                       strip, counts[strip], reference_selected[strip], count);
            if (lookup_valid) count++;
        end
        @(negedge clk);
        verified_frames++;
        $display("RANKED_SIGN_SLOTS_FRAME entries=%0d strips=%0d selected=%0d cycles=%0d",
                 ENTRIES, strips, count, delay_cycles);
    endtask

    task automatic synthetic(input int strips, tokens, pattern);
        foreach (counts[strip]) counts[strip] = 0;
        start_frame(strips, tokens > 1);
        for (int token = 0; token < tokens; token++)
            for (int strip = 0; strip < strips; strip++) begin
                bit active;
                case (pattern)
                    0: active = 1;
                    1: active = 0;
                    2: active = token < ((strip * 11 + 7) % (tokens + 1));
                    default: active = (strip % 7 == 0) && (token < 2);
                endcase
                counts[strip] += int'(active);
                send_strip(strip, token == 0, active, token == tokens-1 && strip == strips-1);
            end
        check_frame(strips, tokens > 1);
    endtask

    initial begin : exercise
        string fixture;
        if (!$value$plusargs("NORM=%s", fixture)) $fatal(1, "SLOT_NORM_FIXTURE");
        $readmemh(fixture, norm_codes);
        repeat (2) @(negedge clk);
        rst_n = 1;
        synthetic(256, 16, 0);
        synthetic(7, 2, 1);
        synthetic(256, 16, 2);
        synthetic(255, 16, 3);
        synthetic(256, 1, 0);
        synthetic(1, 2, 0);
        foreach (counts[strip]) counts[strip] = 0;
        start_frame(256, 1);
        for (int token = 0; token < 16; token++)
            for (int strip = 0; strip < 256; strip++) begin
                bit active;
                active = 0;
                for (int lane = 0; lane < 8; lane++) begin
                    logic signed [15:0] value;
                    value = norm_codes[(token*256+strip)*8+lane];
                    active |= value > 16'sd768 || value < -16'sd768;
                end
                counts[strip] += int'(active);
                send_strip(strip, token == 0, active, token == 15 && strip == 255);
            end
        check_frame(256, 1);
        // Restart during a build before a completed map becomes visible.
        start_frame(1, 1);
        send_strip(0, 1, 1, 1);
        synthetic(256, 2, 1);
        $display("RANKED_SIGN_SLOTS_PASS entries=%0d frames=%0d max_build_cycles=%0d",
                 ENTRIES, verified_frames, max_build_cycles);
        $finish;
    end

    initial begin
        #1000000;
        $fatal(1, "RANKED_SIGN_SLOTS_TIMEOUT");
    end
endmodule
