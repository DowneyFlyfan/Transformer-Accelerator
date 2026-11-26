`timescale 1ns/1ps
// One provided trained row as synthetic image root0; not a 576-image fixture.
module tri_oracle_normalized_row_stage_green_tb;
  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;
  localparam logic [31:0] TokenTag = 32'h53544701;
  logic cfg_valid = 0, cfg_ready;
  logic [31:0] cfg_tag = TokenTag;
  logic [9:0] cfg_strips = 256;
  logic [63:0] cfg_epsilon_q16 = 0;
  logic signed [7:0] cfg_gamma_exponent = -14;
  logic stats_valid = 0, stats_ready, stats_last = 0;
  logic [255:0] stats_data = 0;
  logic [127:0] stats_gamma = 0;
  logic replay_valid = 0, replay_ready, replay_last = 0;
  logic [255:0] replay_data = 0;
  logic [127:0] replay_gamma = 0;
  logic out_valid, out_ready, out_last, out_error;
  logic [31:0] out_tag;
  logic [9:0] out_index;
  logic [3:0] out_count;
  logic [63:0] out_activation;
  logic signed [8:0] out_exponent, expected_exponent;
  logic [7:0] out_outlier_mask, out_outlier_negative, out_normalized_negative;

  logic ff_idle = 1, acquire_valid, acquire_ready, release_valid, release_ready;
  logic context_owned;
  logic [1:0] ff_ce_n = 2'b11, ff_we_n = 2'b11;
  logic [17:0] ff_address = 0;
  logic [127:0] ff_write_data = 0, ff_read_data;
  logic req_valid, req_write, req_ready;
  logic [9:0] req_word;
  logic [63:0] req_data, rsp_data;
  logic rsp_valid, rsp_error, rsp_ready;

  logic start_valid = 0, start_ready;
  logic stage_req_valid, stage_req_write, stage_req_ready, stage_rsp_ready;
  logic [9:0] stage_req_word;
  logic [63:0] stage_req_data;
  logic stage_row_valid, stage_row_ready, stage_row_consumed;
  logic [31:0] stage_row_tag;
  logic signed [8:0] stage_row_exponent;
  logic [2047:0] stage_row_negative;
  logic stage_release_valid = 0, stage_release_ready;
  logic stage_epoch_invalid, stage_epoch_clear_ready, stage_lease_held;
  logic [8:0] stage_accepted_words, stage_acknowledged_words;
  logic hold_last_ack = 1, permit_stage_response;
  logic reader_owns = 0, reader_req_valid = 0, reader_rsp_ready = 0;
  logic [9:0] reader_word = 0;
  logic contract_done;

  logic merge_rst_n = 0, merge_cfg_valid = 0, merge_cfg_ready, merge_sign_ready;
  logic merge_map_valid, merge_map_last, merge_done_valid, merge_done_error;
  logic [9:0] merge_map_index, merge_map_origin;
  logic allow_merge = 0;
  logic [2047:0] oracle_signs = 0;
  int cycles = 0, stats_accepts = 0, replay_accepts = 0, normalizer_accepts = 0;
  int write_requests = 0, write_acknowledgements = 0, read_requests = 0, readbacks = 0;
  int merger_accepts = 0, vendor_cell_count = 0;
  logic [3:0] vendor_cells_seen = 0;
  string root;

  tri_oracle_fused_input_sign_normalizer normalizer (.*);
  tri_oracle_shared_metadata_store memory (.*);
  tri_oracle_normalized_row_stage stage (
    .clk, .rst_n, .start_valid, .start_ready, .start_tag(TokenTag),
    .abort_valid(1'b0), .producer_idle(cfg_ready && !cfg_valid && !out_valid),
    .epoch_clear_valid(1'b0), .epoch_clear_ready(stage_epoch_clear_ready),
    .epoch_invalid(stage_epoch_invalid),
    .in_valid(out_valid), .in_ready(out_ready), .in_tag(out_tag),
    .in_index(out_index), .in_count(out_count), .in_last(out_last),
    .in_error(out_error), .in_activation(out_activation),
    .in_exponent(out_exponent), .in_negative(out_normalized_negative),
    .memory_acquire_valid(acquire_valid), .memory_acquire_ready(acquire_ready),
    .memory_context_owned(context_owned), .memory_release_valid(release_valid),
    .memory_release_ready(release_ready), .memory_req_valid(stage_req_valid),
    .memory_req_ready(stage_req_ready), .memory_req_write(stage_req_write),
    .memory_req_word(stage_req_word), .memory_req_data(stage_req_data),
    .memory_rsp_valid(rsp_valid && permit_stage_response && !reader_owns),
    .memory_rsp_error(rsp_error), .memory_rsp_ready(stage_rsp_ready),
    .row_valid(stage_row_valid), .row_ready(stage_row_ready),
    .row_tag(stage_row_tag), .row_exponent(stage_row_exponent),
    .row_negative(stage_row_negative), .row_consumed(stage_row_consumed),
    .release_valid(stage_release_valid), .release_ready(stage_release_ready),
    .consumer_idle(!reader_owns), .lease_held(stage_lease_held),
    .accepted_words(stage_accepted_words), .acknowledged_words(stage_acknowledged_words)
  );
  tri_oracle_cumulative_token_merger423 #(
    .IMAGE_WIDTH(24), .IMAGE_HEIGHT(24), .FEATURES(2048), .COMPILED_SIGN_BANK(0)
  ) merger (
    .clk, .rst_n(merge_rst_n), .cfg_valid(merge_cfg_valid),
    .cfg_new_image(1'b1), .cfg_ready(merge_cfg_ready),
    .cfg_minimum_matches(12'd2048), .sign_valid(stage_row_valid && allow_merge),
    .sign_ready(merge_sign_ready), .sign_data(stage_row_negative),
    .map_valid(merge_map_valid), .map_ready(1'b1), .map_index(merge_map_index),
    .map_origin(merge_map_origin), .map_last(merge_map_last),
    .done_valid(merge_done_valid), .done_error(merge_done_error), .done_ready(1'b0)
  );
  row_stage_contract_controls contract_controls (.done(contract_done));

  always_comb begin
    permit_stage_response = !hold_last_ack || write_requests < 256;
    stage_req_ready = req_ready && !reader_owns;
    req_valid = reader_owns ? reader_req_valid : stage_req_valid;
    req_write = reader_owns ? 1'b0 : stage_req_write;
    req_word = reader_owns ? reader_word : stage_req_word;
    req_data = reader_owns ? 64'b0 : stage_req_data;
    rsp_ready = reader_owns ? reader_rsp_ready : stage_rsp_ready && permit_stage_response;
    stage_row_ready = allow_merge && merge_sign_ready;
  end

  function automatic logic [7:0] product_signs (
    input logic [255:0] data, input logic [127:0] gamma
  );
    logic signed [31:0] x;
    logic signed [15:0] g;
    logic signed [47:0] product;
    for (int lane = 0; lane < 8; lane++) begin
      x = $signed(data[lane*32 +: 32]);
      g = $signed(gamma[lane*16 +: 16]);
      product = x*g;
      if ($isunknown(product)) $fatal(1, "ROW_STAGE_UNKNOWN_ORACLE_PRODUCT");
      product_signs[lane] = product < 0;
    end
  endfunction

  always @(posedge clk) begin
    cycles++;
    if (cycles > 200000) $fatal(1, "ROW_STAGE_WATCHDOG");
    if (rst_n) begin
      if (stage_epoch_invalid) $fatal(1, "ROW_STAGE_UNEXPECTED_PRIMARY_EPOCH_ERROR");
      if (stats_valid && stats_ready) begin
        $display("ROW_STAGE_STATS word=%0d raw=%064h gamma=%032h last=%0b", stats_accepts, stats_data, stats_gamma, stats_last);
        stats_accepts++;
      end
      if (replay_valid && replay_ready) begin
        oracle_signs[replay_accepts*8 +: 8] <= product_signs(replay_data, replay_gamma);
        $display("ROW_STAGE_REPLAY word=%0d raw=%064h gamma=%032h last=%0b", replay_accepts, replay_data, replay_gamma, replay_last);
        replay_accepts++;
      end
      if (out_valid && out_ready) begin
        if (out_error || out_tag !== TokenTag || out_count !== 8 ||
            out_index !== 10'(normalizer_accepts) || out_last !== (normalizer_accepts == 255) ||
            out_exponent !== expected_exponent ||
            out_normalized_negative !== oracle_signs[normalizer_accepts*8 +: 8])
          $fatal(1, "ROW_STAGE_NORMALIZER_VALUE_OR_METADATA");
        if (!req_valid || !req_ready || !req_write || req_word !== out_index || req_data !== out_activation)
          $fatal(1, "ROW_STAGE_NONATOMIC_NORMALIZER_MEMORY");
        $display("ROW_STAGE_NORMALIZED word=%0d data=%016h signs=%02h tag=%08h exponent=%0d last=%0b", normalizer_accepts, out_activation, out_normalized_negative, out_tag, $signed(out_exponent), out_last);
        normalizer_accepts++;
      end
      if (req_valid && req_ready) begin
        if (req_write) begin
          if (req_word !== 10'(write_requests)) $fatal(1, "ROW_STAGE_WRITE_INDEX");
          $display("ROW_STAGE_WRITE word=%0d data=%016h", write_requests, req_data);
          write_requests++;
        end else read_requests++;
      end
      if (rsp_valid && rsp_ready && !reader_owns) begin
        if (rsp_error) $fatal(1, "ROW_STAGE_PRIMARY_WRITE_RESPONSE_ERROR");
        write_acknowledgements++;
      end
      if (stage_row_valid && stage_row_ready) begin
        if (write_acknowledgements != 256 || stage_acknowledged_words != 256 ||
            stage_accepted_words != 256 || !stage_lease_held || !context_owned ||
            stage_row_tag !== TokenTag || stage_row_exponent !== expected_exponent ||
            stage_row_negative !== oracle_signs || merger_accepts != 0)
          $fatal(1, "ROW_STAGE_INCOMPLETE_COMMITTED_ROW");
        merger_accepts++;
        #1;
        if (!merge_map_valid || merge_map_index !== 0 || merge_map_origin !== 0 || merge_done_error)
          $fatal(1, "ROW_STAGE_REAL_MERGER_DID_NOT_ACCEPT");
        $display("ROW_STAGE_REAL_MERGE map_index=0 map_origin=0 requests=256 write_acks=256 signs=%0512h", stage_row_negative);
      end
    end
  end

  task automatic provide_pass (input bit replay_pass);
    int raw_file, gamma_file;
    logic [255:0] raw_word;
    logic [127:0] gamma_word;
    raw_file = $fopen({root,"/raw.hex"}, "r");
    gamma_file = $fopen({root,"/gamma.hex"}, "r");
    if (!raw_file || !gamma_file) $fatal(1, "ROW_STAGE_SOURCE_FILE_MISSING");
    for (int word = 0; word < 256; word++) begin
      if ($fscanf(raw_file,"%h\n",raw_word) != 1 || $fscanf(gamma_file,"%h\n",gamma_word) != 1)
        $fatal(1, "ROW_STAGE_SOURCE_PREFIX_TRUNCATED");
      @(negedge clk);
      if (replay_pass) begin
        replay_valid = 1; replay_data = raw_word; replay_gamma = gamma_word;
        replay_last = word == 255;
      end else begin
        stats_valid = 1; stats_data = raw_word; stats_gamma = gamma_word;
        stats_last = word == 255;
      end
      do @(posedge clk); while (replay_pass ? !replay_ready : !stats_ready);
      @(negedge clk);
      if (replay_pass) replay_valid = 0;
      else stats_valid = 0;
    end
    $fclose(raw_file); $fclose(gamma_file);
  endtask

  task automatic read_complete_row;
    int expected_file;
    logic [63:0] expected_word;
    expected_file = $fopen({root,"/expected.hex"}, "r");
    if (!expected_file) $fatal(1, "ROW_STAGE_EXPECTED_FILE_MISSING");
    @(negedge clk); reader_owns = 1;
    for (int word = 0; word < 256; word++) begin
      if ($fscanf(expected_file,"%h\n",expected_word) != 1) $fatal(1, "ROW_STAGE_EXPECTED_PREFIX_TRUNCATED");
      @(negedge clk); reader_word = 10'(word); reader_req_valid = 1;
      do @(posedge clk); while (!req_ready);
      @(negedge clk); reader_req_valid = 0; reader_rsp_ready = 1;
      do @(posedge clk); while (!rsp_valid);
      if (rsp_error || rsp_data !== expected_word) $fatal(1, "ROW_STAGE_INDEPENDENT_RAM_READBACK");
      if (!stage_lease_held || !context_owned || stage_release_ready) $fatal(1, "ROW_STAGE_READER_LEASE_RELEASED");
      $display("ROW_STAGE_READBACK word=%0d data=%016h", word, rsp_data);
      readbacks++;
      @(negedge clk); reader_rsp_ready = 0;
    end
    @(negedge clk); reader_owns = 0;
    $fclose(expected_file);
  endtask

  initial begin
    int epsilon_file, exponent_file;
    if (!$value$plusargs("NORM_ROOT=%s", root)) $fatal(1, "ROW_STAGE_ROOT_ARGUMENT_REQUIRED");
    epsilon_file = $fopen({root,"/epsilon.hex"}, "r");
    exponent_file = $fopen({root,"/expected_exponents.hex"}, "r");
    if (!epsilon_file || !exponent_file ||
        $fscanf(epsilon_file,"%h\n",cfg_epsilon_q16) != 1 ||
        $fscanf(exponent_file,"%h\n",expected_exponent) != 1)
      $fatal(1, "ROW_STAGE_CONFIG_FILE_MISSING");
    $fclose(epsilon_file); $fclose(exponent_file);
    $display("ROW_STAGE_BEGIN fixture_row=0 synthetic_original_root=0 features=2048");
    repeat (3) @(negedge clk); rst_n = 1; merge_rst_n = 1;
    // Acquire staging before normalizer configuration, never concurrently.
    @(negedge clk); start_valid = 1;
    do @(posedge clk); while (!start_ready);
    @(negedge clk); start_valid = 0;
    if (!context_owned || !stage_lease_held) $fatal(1, "ROW_STAGE_LEASE_NOT_ACQUIRED");
    merge_cfg_valid = 1;
    do @(posedge clk); while (!merge_cfg_ready);
    @(negedge clk); merge_cfg_valid = 0;
    while (!merge_sign_ready || merge_map_valid) @(negedge clk);
    cfg_valid = 1;
    do @(posedge clk); while (!cfg_ready);
    @(negedge clk); cfg_valid = 0;
    provide_pass(0);
    fork provide_pass(1); join
    while (write_requests != 256 || !rsp_valid) @(negedge clk);
    repeat (9) begin
      @(negedge clk);
      if (rsp_ready || stage_row_valid || merger_accepts || !context_owned ||
          stage_acknowledged_words != 255 || stage_accepted_words != 256)
        $fatal(1, "ROW_STAGE_FINAL_ACK_BARRIER");
    end
    $display("ROW_STAGE_HELD_FINAL_ACK requests=256 write_acks=255 rsp_valid=1 rsp_ready=0 merge_accepts=0");
    hold_last_ack = 0;
    while (!stage_row_valid) @(negedge clk);
    stage_release_valid = 1;
    repeat (7) begin
      @(negedge clk);
      if (!stage_row_valid || stage_row_ready || stage_release_ready || release_valid ||
          stage_row_tag !== TokenTag || stage_row_exponent !== expected_exponent ||
          stage_row_negative !== oracle_signs || !context_owned)
        $fatal(1, "ROW_STAGE_CONSUMER_STALL_OR_EARLY_RELEASE");
    end
    stage_release_valid = 0; allow_merge = 1;
    do @(posedge clk); while (!(stage_row_valid && stage_row_ready));
    @(negedge clk); allow_merge = 0;
    if (!stage_row_consumed || !context_owned || !stage_lease_held) $fatal(1, "ROW_STAGE_SIGN_CONSUMPTION_RELEASED_LEASE");
    read_complete_row();
    if (stats_accepts != 256 || replay_accepts != 256 || normalizer_accepts != 256 ||
        write_requests != 256 || write_acknowledgements != 256 ||
        read_requests != 256 || readbacks != 256 || merger_accepts != 1)
      $fatal(1, "ROW_STAGE_INCOMPLETE_PRIMARY_COUNTS");
    @(negedge clk); stage_release_valid = 1;
    do @(posedge clk); while (!stage_release_ready);
    @(negedge clk); stage_release_valid = 0;
    if (context_owned || stage_lease_held || stage_row_valid) $fatal(1, "ROW_STAGE_EXPLICIT_RELEASE_FAILED");
    while (!contract_done) @(negedge clk);
    if (vendor_cell_count != 4 || vendor_cells_seen !== 4'b1111) $fatal(1, "ROW_STAGE_VENDOR_CENSUS");
    $display("ROW_STAGE_PRIMARY_PASS normalized_words=256 requests=256 write_acks=256 readbacks=256 signs=2048 real_merger_accepts=1");
    $display("NORMALIZED_ROW_STAGE_GREEN_PASS controller_done=1 vendor_cells=4");
    $finish;
  end
endmodule
