`timescale 1ns/1ps

module tri_oracle_host_writeback_tx_tb;
  localparam logic [31:0] FRAME_TAG = 32'h39300001;
  logic clk = 0, rst_n = 0;
  always #5 clk = !clk;

  logic frame_cfg_valid = 0, frame_cfg_ready, frame_active, packet_error;
  logic in_valid = 0, in_ready, in_last;
  logic [3:0] in_token;
  logic [15:0] in_start;
  logic [7:0] in_count;
  logic [5119:0] in_data;
  logic wb_valid, wb_ready, wb_last;
  logic [31:0] wb_tag;
  logic [3:0] wb_token, wb_count;
  logic [15:0] wb_start;
  logic [127:0] wb_data;
  logic bank_read_valid, bank_read_ready, bank_response_ready;
  logic bank_response_valid = 0;
  logic [8:0] bank_read_row;
  logic [231:0] bank_response_data;
  logic source_valid = 0, source_ready, source_last;
  logic [15:0] source_data;
  logic tx_valid, tx_ready, tx_last;
  logic [15:0] tx_data;

  logic [620:0] fixture [512];
  logic [15:0] words [131], held_data;
  logic held_last;
  bit held = 0;
  int cycles = 0, reads = 0, accepted = 0, strips = 0, word_index = 0;
  int responses = 0, stalled = 0, contended = 0;
  string fixture_path, dump_path;
  int dump;

  assign bank_read_ready = cycles % 7 != 2;
  assign tx_ready = cycles % 11 >= 4 && cycles % 17 != 7;

  tri_oracle_decoder_bank_writeback writer (
    .clk, .rst_n, .lease_granted(1'b1), .frame_cfg_valid, .frame_abort(1'b0),
    .frame_down_shifts({5'd11, 5'd11}), .frame_cfg_ready, .frame_active,
    .in_valid, .in_ready, .packet_error, .in_tag(FRAME_TAG),
    .in_token, .in_start, .in_count, .in_last, .in_data,
    .bank_read_valid, .bank_read_ready, .bank_read_row,
    .bank_response_valid, .bank_response_ready, .bank_response_data,
    .out_valid(wb_valid), .out_ready(wb_ready), .out_tag(wb_tag),
    .out_token(wb_token), .out_start(wb_start), .out_count(wb_count),
    .out_last(wb_last), .out_data(wb_data)
  );

  tri_oracle_host_writeback_tx dut (.*);

  function automatic int strip_row(input int ordinal);
    int tile, slot, tile_strips;
    tile = ordinal / 40;
    slot = ordinal % 40;
    tile_strips = tile == 12 ? 16 : 20;
    return 256*(slot / tile_strips) + 20*tile + slot % tile_strips;
  endfunction

  function automatic int response_size(input int ordinal);
    case (ordinal % 3)
      0: return 3;
      1: return 6;
      default: return 131;
    endcase
  endfunction

  function automatic logic [15:0] response_word(input int ordinal, input int index);
    // A command tag can start with the same word as a writeback record.
    if (index == 0) return 16'ha67e;
    return 16'(16'h4700 + 32*ordinal + index);
  endfunction

  always @(posedge clk) if (rst_n) begin
    if (packet_error) $fatal(1, "BANK_WRITER_REJECTED_TRAINED_INPUT");
    if (bank_response_valid && bank_response_ready) bank_response_valid <= 0;
    if (bank_read_valid && bank_read_ready) begin
      if (reads >= 512 || bank_read_row !== 9'(strip_row(reads)) || bank_response_valid)
        $fatal(1, "BANK_WRITER_READ_ORDER strip=%0d row=%0d", reads, bank_read_row);
      bank_response_valid <= 1;
      bank_response_data <= fixture[bank_read_row][231:0];
      reads++;
    end
    if (wb_valid && wb_ready) accepted++;
    if (source_valid && wb_valid) contended++;
    if (held && (!tx_valid || tx_data !== held_data || tx_last !== held_last))
      $fatal(1, "HOST_TX_CHANGED_DURING_STALL");
    held = tx_valid && !tx_ready;
    if (held) begin
      stalled++;
      held_data = tx_data;
      held_last = tx_last;
    end
    if (tx_valid && tx_ready) begin
      int row;
      if (word_index >= 131) $fatal(1, "HOST_TX_FRAME_TOO_LONG");
      words[word_index] = tx_data;
      if (tx_last) begin
        if (word_index == 12) begin
          row = strip_row(strips);
          if (strips >= 512 || strips >= accepted || words[0] !== 16'ha67e ||
              {words[2], words[1]} !== FRAME_TAG || words[3] !== 16'(8*(row%256)) ||
              words[4] !== {7'b0, (strips==511), 4'd8, 4'(row/256)})
            $fatal(1, "HOST_WRITEBACK_METADATA strip=%0d row=%0d", strips, row);
          for (int lane=0; lane<8; lane++)
            if (words[5+lane] !== fixture[row][493+16*lane +: 16])
              $fatal(1, "HOST_WRITEBACK_VALUE strip=%0d lane=%0d", strips, lane);
          $fdisplay(dump, "%08h%04h%04h%04h%04h%04h%04h%04h%04h%04h%04h%04h",
                    FRAME_TAG, words[3], words[4], words[12], words[11], words[10], words[9],
                    words[8], words[7], words[6], words[5], words[0]);
          strips++;
        end else begin
          if (responses >= 18 || word_index + 1 != response_size(responses))
            $fatal(1, "HOST_COMMAND_RESPONSE_LENGTH response=%0d words=%0d", responses, word_index+1);
          for (int index=0; index<=word_index; index++)
            if (words[index] !== response_word(responses, index))
              $fatal(1, "HOST_COMMAND_RESPONSE_CHANGED response=%0d word=%0d", responses, index);
          responses++;
        end
        word_index = 0;
      end else word_index++;
    end
  end

  always @(negedge clk) cycles <= cycles + 1;

  initial begin
    if (!$value$plusargs("FIXTURE=%s", fixture_path) || !$value$plusargs("DUMP=%s", dump_path))
      $fatal(1, "HOST_WRITEBACK_FIXTURE_AND_DUMP_REQUIRED");
    $readmemh(fixture_path, fixture);
    dump = $fopen(dump_path, "w");
    if (!dump) $fatal(1, "HOST_WRITEBACK_DUMP_OPEN");
    repeat (3) @(negedge clk);
    rst_n = 1;
    fork
      begin
        frame_cfg_valid = 1;
        do @(posedge clk); while (!frame_cfg_ready);
        @(negedge clk);
        frame_cfg_valid = 0;
        for (int tile=0; tile<13; tile++) begin
          for (int token=0; token<2; token++) begin
            int tile_strips;
            tile_strips = tile == 12 ? 16 : 20;
            in_data = '0;
            for (int strip=0; strip<tile_strips; strip++) begin
              int row;
              row = token*256 + tile*20 + strip;
              if (fixture[row][492:488] !== 5'd11) $fatal(1, "TRAINED_WRITEBACK_DOWNSHIFT");
              in_data[strip*256 +: 256] = fixture[row][487:232];
            end
            in_token = 4'(token);
            in_start = 16'(tile*160);
            in_count = 8'(tile_strips*8);
            in_last = tile == 12 && token == 1;
            in_valid = 1;
            do @(posedge clk); while (!in_ready);
            @(negedge clk);
            in_valid = 0;
          end
        end
      end
      begin
        for (int frame=0; frame<18; frame++) begin
          repeat (4+frame) @(negedge clk);
          for (int index=0; index<response_size(frame); index++) begin
            if (index % 19 == 4) begin
              source_valid = 0;
              repeat (2) @(negedge clk);
            end
            source_data = response_word(frame, index);
            source_last = index == response_size(frame)-1;
            source_valid = 1;
            do @(posedge clk); while (!source_ready);
            @(negedge clk);
            source_valid = 0;
          end
        end
      end
    join
    repeat (200) @(negedge clk);
    if (strips != 512 || accepted != 512 || reads != 512 || responses != 18 ||
        stalled == 0 || contended == 0 || frame_active || word_index != 0)
      $fatal(1, "HOST_WRITEBACK_DELIVERY strips=%0d accepted=%0d reads=%0d responses=%0d",
             strips, accepted, reads, responses);
    $fclose(dump);
    $display("HOST_WRITEBACK_TX_PASS strips=%0d values=%0d responses=%0d stalled=%0d contended=%0d",
             strips, strips*8, responses, stalled, contended);
    $finish;
  end

  initial begin
    repeat (25000) @(negedge clk);
    $fatal(1, "HOST_WRITEBACK_TX_TIMEOUT strips=%0d", strips);
  end
endmodule
