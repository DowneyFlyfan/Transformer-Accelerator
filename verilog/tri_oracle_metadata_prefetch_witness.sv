`timescale 1ns/1ps

module tri_oracle_metadata_prefetch_witness (
    input logic clk, rst_n, frame_start, read_launch, latch_word, done, done_error
);
    bit pending = 0;
    int reads = 0, latches = 0;

    always @(posedge clk) begin
        if (!rst_n || frame_start) begin
            pending = 0;
            reads = 0;
            latches = 0;
        end else begin
            if (read_launch && latch_word)
                $fatal(1, "METADATA_PREFETCH_SAME_EDGE");
            if (read_launch) begin
                if (pending) $fatal(1, "METADATA_PREFETCH_OVERWROTE_PENDING_WORD");
                pending = 1;
                reads++;
            end
            if (latch_word) begin
                if (!pending) $fatal(1, "METADATA_PREFETCH_LATCH_WITHOUT_READ");
                pending = 0;
                latches++;
            end
        end
    end

    always @(posedge done) begin
        if (!done_error) begin
            if (pending || reads != latches) $fatal(1, "METADATA_PREFETCH_UNCONSUMED_WORD");
            $display("METADATA_PREFETCH_PASS reads=%0d latches=%0d", reads, latches);
        end
    end
endmodule

bind tri_oracle_packed_outlier_replay tri_oracle_metadata_prefetch_witness metadata_prefetch (
    .clk, .rst_n, .frame_start(cfg_valid && cfg_ready), .read_launch(mem_read), .latch_word(state == ReadWord),
    .done(done_valid), .done_error
);
