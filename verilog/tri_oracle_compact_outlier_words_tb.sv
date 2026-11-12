`timescale 1ns/1ps

module tri_oracle_compact_outlier_words_tb;
    localparam int Words = 16 * 52;
    logic clk = 0, read_enable = 0, write_enable = 0;
    always #5 clk = ~clk;
    logic [9:0] address = '0;
    logic [63:0] write_word = '0, read_word;
    logic [79:0] encode_metadata = '0;
    logic [63:0] encoded, decode_word;
    logic [2:0] decode_strip = '0;
    logic [15:0] decoded_metadata;

    tri_oracle_outlier_word_codec codec (.*);
    tri_oracle_compact_outlier_words memory (.*);
    assign decode_word = encoded;

    function automatic logic [63:0] pattern(input int index);
        return 64'h6bc17b20a93518fe ^ (64'(index) * 64'h0fb1a2907183aa01);
    endfunction

    task automatic write_address(input int index, input logic [63:0] data);
        address = 10'(index);
        write_word = data;
        write_enable = 1;
        @(negedge clk);
        write_enable = 0;
    endtask

    task automatic read_address(input int index, input logic [63:0] expected);
        address = 10'(index);
        read_enable = 1;
        @(negedge clk);
        read_enable = 0;
        if (read_word !== expected) $fatal(1, "COMPACT_OUTLIER_MEMORY address=%0d got=%h expected=%h",
                                           index, read_word, expected);
    endtask

    initial begin : exercise
        int value, digit, lane;
        logic [79:0] canonical;
        // Sweep all five-trit values in every byte position. A sign on an
        // inactive lane is ignored and must not survive the round trip.
        for (int byte_index = 0; byte_index < 8; byte_index++)
            for (int code = 0; code < 243; code++) begin
                encode_metadata = '0;
                canonical = '0;
                for (int index = 0; index < 40; index++) begin
                    encode_metadata[16*(index/8)+8+index%8] = 1;
                end
                value = code;
                for (int index = 0; index < 5; index++) begin
                    lane = byte_index*5 + index;
                    digit = value % 3;
                    value /= 3;
                    canonical[16*(lane/8)+lane%8] = digit != 0;
                    canonical[16*(lane/8)+8+lane%8] = digit == 2;
                    encode_metadata[16*(lane/8)+lane%8] = digit != 0;
                    encode_metadata[16*(lane/8)+8+lane%8] = digit != 1;
                end
                #1ps;
                if (encoded !== (64'(code) << (8*byte_index)))
                    $fatal(1, "COMPACT_OUTLIER_CODEC byte=%0d code=%0d got=%h", byte_index, code, encoded);
                for (int strip = 0; strip < 5; strip++) begin
                    decode_strip = 3'(strip);
                    #1ps;
                    if (decoded_metadata !== canonical[16*strip+:16])
                        $fatal(1, "COMPACT_OUTLIER_DECODE byte=%0d code=%0d strip=%0d", byte_index, code, strip);
                end
            end
        @(negedge clk);
        // Write every physical slot, then update each odd halfword. The
        // even half in the same compiled row must retain its prior data.
        for (int index = 0; index < Words; index++) write_address(index, pattern(index));
        for (int index = 513; index < Words; index += 2) write_address(index, ~pattern(index));
        write_address(Words, '1);
        write_address(1023, '1);
        for (int index = Words-1; index >= 0; index--)
            read_address(index, index >= 512 && (index%2 != 0) ? ~pattern(index) : pattern(index));
        $display("COMPACT_OUTLIER_WORDS_PASS codec_values=%0d decoded_strips=%0d words=%0d masked_updates=%0d",
                 8*243, 8*243*5, Words, (Words-512)/2);
        $finish;
    end

    initial begin
        #100000;
        $fatal(1, "COMPACT_OUTLIER_WORDS_TIMEOUT");
    end
endmodule
