`timescale 1ns/1ps

module tri_oracle_host_grouped_tx_tb;
  localparam logic [31:0] GROUP_TAG = 32'h00000071;
  localparam logic [4:0][3:0] ACTIVE = {4'h9, 4'h4, 4'h5, 4'ha, 4'hf};
  logic clk = 0, rst_n = 0, start_valid = 0, start_ready;
  always #5 clk = !clk;

  wire [4:0] start_mask = '1, cluster_start_ready = '1;
  wire done_ready = 1'b1;
  wire [4:0] cluster_done_error = '0;
  logic [4:0] cluster_start_valid, cluster_done_valid, cluster_done_ready;
  logic [4:0] cluster_result_valid, cluster_result_last, cluster_result_ready;
  logic [4:0][1:0] cluster_result_lane;
  logic [4:0][2047:0] cluster_result_data;
  logic [4:0][3:0] remaining = '0, observed = '0;
  logic [4:0] started = '0;
  logic result_valid, result_last, result_ready;
  logic [2:0] result_cluster;
  logic [1:0] result_lane;
  logic [2047:0] result_data;
  logic batch_active, done_valid, done_error;

  logic source_valid = 0, source_ready, source_last;
  logic [15:0] source_data;
  logic combined_valid, combined_ready, combined_last;
  logic [15:0] combined_data;
  logic tx_valid, tx_last, tx_ready;
  logic [15:0] tx_data;
  logic wb_valid = 0, wb_ready, wb_last;
  logic [31:0] wb_tag = 32'habcd1234;
  logic [3:0] wb_token = 0, wb_count = 8;
  logic [15:0] wb_start;
  wire [127:0] wb_data = 128'h00070006000500040003000200010000;

  logic [2047:0] fixture [20];
  logic [2111:0] packet;
  logic [15:0] held_data;
  logic held_last;
  bit held = 0, finished = 0;
  string fixture_path, dump_path;
  int cycles = 0, word_index = 0, groups = 0, writes = 0, commands = 0, stalled = 0;
  int overlap = 0, retired = 0, dump;
  assign tx_ready = cycles%11 >= 4 && cycles%17 != 2;

  // BATCH_INSTANCE
  tri_oracle_grouped_cluster_batch batch (.*);
  // END_BATCH_INSTANCE

  tri_oracle_host_grouped_tx grouped_tx (
    .clk, .rst_n, .source_valid, .source_ready, .source_last, .source_data,
    .group_valid(result_valid), .group_ready(result_ready), .group_last(result_last),
    .group_tag(GROUP_TAG), .group_cluster(result_cluster), .group_lane(result_lane), .group_values(result_data),
    .tx_valid(combined_valid), .tx_last(combined_last), .tx_ready(combined_ready), .tx_data(combined_data)
  );
  tri_oracle_host_writeback_tx writeback_tx (
    .clk, .rst_n, .source_valid(combined_valid), .source_ready(combined_ready),
    .source_last(combined_last), .source_data(combined_data),
    .wb_valid, .wb_ready, .wb_last, .wb_tag, .wb_token, .wb_count, .wb_start, .wb_data,
    .tx_valid, .tx_last, .tx_ready, .tx_data
  );

  always_comb begin
    for (int cluster=0; cluster<5; cluster++) begin
      logic selected;
      selected = 0;
      cluster_result_lane[cluster] = '0;
      for (int lane=0; lane<4; lane++)
        if (!selected && remaining[cluster][lane]) begin
          selected = 1;
          cluster_result_lane[cluster] = 2'(lane);
        end
      cluster_result_valid[cluster] = started[cluster] && selected;
      cluster_result_last[cluster] = $onehot(remaining[cluster]);
      cluster_result_data[cluster] = fixture[4*cluster + int'(cluster_result_lane[cluster])];
      cluster_done_valid[cluster] = started[cluster] && !selected;
    end
  end

  always @(posedge clk) if (rst_n) begin
    for (int cluster=0; cluster<5; cluster++) begin
      if (cluster_start_valid[cluster] && cluster_start_ready[cluster]) begin
        started[cluster] <= 1;
        remaining[cluster] <= ACTIVE[cluster];
      end
      if (cluster_result_ready[cluster]) begin
        if (!cluster_result_valid[cluster] || !result_ready)
          $fatal(1, "GROUPED_SOURCE_UNEXPECTED_ACK");
        remaining[cluster][cluster_result_lane[cluster]] <= 0;
      end
    end
    if (wb_valid && result_valid) overlap++;
    if (result_valid && result_ready) begin
      if (!tx_ready || !tx_valid || !tx_last || word_index!=131)
        $fatal(1, "GROUPED_ACK_BEFORE_FINAL_WORD groups=%0d word=%0d", groups, word_index);
      retired++;
    end
    if (held && (!tx_valid || tx_last !== held_last || tx_data !== held_data))
      $fatal(1, "GROUPED_HOST_CHANGED_DURING_STALL");
    held = tx_valid && !tx_ready;
    if (held) begin
      stalled++;
      held_data = tx_data;
      held_last = tx_last;
    end

    if (tx_valid && tx_ready) begin
      if (word_index == 132) $fatal(1, "GROUPED_HOST_FRAME_OVERFLOW");
      packet = {tx_data, packet[2111:16]};
      if (tx_last) begin
        case (word_index)
          2: begin
            if (commands >= 4 || packet[2111-:48] !== {16'h0007,16'(commands),16'ha680})
              $fatal(1, "GROUPED_HOST_COMMAND_FRAME");
            commands++;
          end
          12: begin
            if (writes >= 11 || packet[2111-:208] !==
                {wb_data,7'b0,(writes==10),4'd8,4'd0,16'(writes*8),32'habcd1234,16'ha67e})
              $fatal(1, "GROUPED_HOST_WRITEBACK_FRAME row=%0d", writes);
            writes++;
          end
          131: begin
            int cluster, lane;
            cluster = int'(result_cluster);
            lane = int'(result_lane);
            if (!result_ready || !result_valid || cluster>=5 || !ACTIVE[cluster][lane] ||
                observed[cluster][lane] || retired != groups+1 ||
                packet !== {fixture[cluster*4+lane],10'b0,result_last,2'(lane),3'(cluster),
                            GROUP_TAG,16'ha680})
              $fatal(1, "GROUPED_HOST_RESULT group=%0d cluster=%0d lane=%0d", groups, cluster, lane);
            observed[cluster][lane] = 1;
            $fdisplay(dump, "%0d %0d %0b %0512h", cluster, lane, result_last, fixture[cluster*4+lane]);
            groups++;
          end
          default: $fatal(1, "GROUPED_HOST_FRAME_LENGTH words=%0d", word_index+1);
        endcase
        word_index = 0;
      end else word_index++;
    end
    if (done_valid && done_ready) begin
      if (done_error || groups != 11) $fatal(1, "GROUPED_DONE_BEFORE_RESULTS groups=%0d", groups);
      finished = 1;
    end
  end

  always @(negedge clk) cycles <= cycles + 1;

  initial begin
    if (!$value$plusargs("FIXTURE=%s", fixture_path) || !$value$plusargs("DUMP=%s", dump_path))
      $fatal(1, "GROUPED_HOST_FIXTURE_AND_DUMP_REQUIRED");
    $readmemh(fixture_path, fixture);
    dump = $fopen(dump_path, "w");
    if (!dump) $fatal(1, "GROUPED_HOST_DUMP_OPEN");
    repeat (3) @(negedge clk);
    rst_n = 1;
    fork
      begin
        start_valid = 1;
        do @(posedge clk); while (!start_ready);
        @(negedge clk);
        start_valid = 0;
      end
      begin
        for (int frame=0; frame<4; frame++) begin
          repeat (2+frame) @(negedge clk);
          for (int word=0; word<3; word++) begin
            source_last = word == 2;
            case (word)
              0: source_data = 16'ha680;
              1: source_data = 16'(frame);
              2: source_data = 16'h0007;
            endcase
            source_valid = 1;
            do @(posedge clk); while (!source_ready);
            @(negedge clk);
            source_valid = 0;
            repeat (2) @(negedge clk);
          end
        end
      end
      begin
        for (int strip=0; strip<11; strip++) begin
          repeat (3) @(negedge clk);
          wb_start = 16'(8*strip);
          wb_last = strip == 10;
          wb_valid = 1;
          do @(posedge clk); while (!wb_ready);
          @(negedge clk);
          wb_valid = 0;
        end
      end
    join
    while (!finished || writes < 11) @(negedge clk);
    repeat (4) @(negedge clk);
    if (observed !== ACTIVE || !finished || batch_active || groups != 11 || commands != 4 ||
        writes != 11 || overlap == 0 || stalled == 0 || word_index != 0)
      $fatal(1, "GROUPED_HOST_DELIVERY groups=%0d commands=%0d writebacks=%0d", groups, commands, writes);
    $fclose(dump);
    $display("GROUPED_HOST_TX_PASS groups=%0d values=%0d command_frames=%0d writeback_frames=%0d held=%0d overlap=%0d",
             groups,groups*64,commands,writes,stalled,overlap);
    $finish;
  end

  initial begin
    repeat (10000) @(negedge clk);
    $fatal(1, "GROUPED_HOST_TIMEOUT groups=%0d", groups);
  end
endmodule
