  logic host_rx_pad_valid, host_rx_pad_ready;
  logic host_tx_pad_valid, host_tx_pad_ready;
  logic [3:0] host_rx_pad_data, host_tx_pad_data;
  logic memory_request_valid, memory_request_credit, memory_request_clock;
  logic [7:0] memory_request_data;
  logic [447:0] response_pad_data;
  logic [6:0] response_pad_metadata;
  logic [1:0] response_pad_credit, response_pad_fault;

  tri_oracle_chip_credited_request dut (
    .clk, .rst_n,
    .host_rx_valid(host_rx_pad_valid), .host_rx_ready(host_rx_pad_ready),
    .host_rx_data(host_rx_pad_data),
    .host_tx_valid(host_tx_pad_valid), .host_tx_ready(host_tx_pad_ready),
    .host_tx_data(host_tx_pad_data),
    .memory_tx_valid(memory_request_valid), .memory_tx_data(memory_request_data),
    .memory_tx_credit(memory_request_credit), .memory_tx_clock(memory_request_clock),
    .memory_mem_rsp_data(response_pad_data), .memory_mem_rsp_metadata(response_pad_metadata),
    .memory_mem_rsp_credit(response_pad_credit),
    .memory_mem_rsp_protocol_error(response_pad_fault)
  );

  tri_oracle_flit_to_pads #(.WORD_BITS(18), .PAD_BITS(4)) host_request (
    .clk, .rst_n, .in_valid(host_rx_valid), .in_ready(host_rx_ready),
    .in_word({host_rx_payload_last, host_rx_is_payload, host_rx_data}),
    .pad_valid(host_rx_pad_valid), .pad_ready(host_rx_pad_ready), .pad_data(host_rx_pad_data)
  );

  tri_oracle_flit_from_pads #(.WORD_BITS(17), .PAD_BITS(4)) host_reply (
    .clk, .rst_n, .pad_valid(host_tx_pad_valid), .pad_ready(host_tx_pad_ready),
    .pad_data(host_tx_pad_data), .out_valid(host_tx_valid), .out_ready(host_tx_ready),
    .out_word({host_tx_last, host_tx_data})
  );

  // Same integral-cycle flight times used in the standalone credited request test.
  localparam int Request_Transit = 2, Credit_Transit = 6;
  logic [7:0] flight_data[Request_Transit];
  logic [Request_Transit-1:0] flight_valid;
  logic [Credit_Transit-1:0] flight_credit;
  logic queue_full, queue_empty, request_head_valid, request_head_ready;
  logic [7:0] request_head;
  wire tail_valid = flight_valid[Request_Transit-1];
  wire reload_head = !request_head_valid || request_head_ready;
  wire grant_credit = reload_head && (!queue_empty || tail_valid);
  assign memory_request_credit = flight_credit[Credit_Transit-1];

  tri_oracle_credit_bypass_fifo #(.WIDTH(8), .DEPTH(16)) request_queue (
    .clk, .rst_n, .read_enable(reload_head), .write_enable(tail_valid),
    .write_data(flight_data[Request_Transit-1]), .read_data(request_head),
    .full(queue_full), .empty(queue_empty)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      flight_valid <= '0;
      flight_credit <= '0;
      request_head_valid <= 0;
    end else begin
      flight_valid <= {flight_valid[Request_Transit-2:0], memory_request_valid};
      flight_credit <= {flight_credit[Credit_Transit-2:0], grant_credit};
      if (reload_head) request_head_valid <= grant_credit;
    end
  end

  always_ff @(posedge clk) begin
    flight_data[0] <= memory_request_data;
    for (int stage = 1; stage < Request_Transit; stage++)
      flight_data[stage] <= flight_data[stage-1];
  end

  tri_oracle_flit_from_pads #(.WORD_BITS(22), .PAD_BITS(8)) memory_request (
    .clk, .rst_n, .pad_valid(request_head_valid), .pad_ready(request_head_ready),
    .pad_data(request_head), .out_valid(memory_tx_valid), .out_ready(memory_tx_ready),
    .out_word(memory_tx_data)
  );

  logic [1:0] response_pending, response_upper, response_wide;
  logic [1:0] response_last, response_error, sending;
  logic [1:0][511:0] response_word;
  logic [1:0][447:0] send_data;
  logic [1:0][6:0] send_metadata;
  logic falling_sent;
  wire [1:0] sent = {falling_sent, sending[0]};
  int memory_request_bytes, response_chunks[2];

  // Present independent response fragments on the two physical sampling edges.
  assign #2 response_pad_data = clk ? send_data[1] : send_data[0];
  assign #2 response_pad_metadata = clk ? send_metadata[1] : send_metadata[0];
  assign memory_mem_rsp_ready = ~response_pending;

  always_ff @(negedge clk or negedge rst_n)
    if (!rst_n) falling_sent <= 0;
    else falling_sent <= sending[1];

  for (genvar lane = 0; lane < 2; lane++) begin : response_peer
    int available;
    wire tail = !response_wide[lane] || response_upper[lane];
    assign sending[lane] = rst_n && response_pending[lane] && available > 0;
    assign send_data[lane] = response_upper[lane] ?
        {384'b0, response_word[lane][511:448]} : response_word[lane][447:0];
    // Zero words tags a scalar or acknowledgment in the compact decoder.
    wire [2:0] send_words = !response_wide[lane] ? 3'd0 : (tail ? 3'd1 : 3'd7);
    assign send_metadata[lane] = {
      sending[lane], send_words, !response_wide[lane],
      tail && response_last[lane], tail && response_error[lane]
    };

    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
        available <= 8;
        response_pending[lane] <= 0;
        response_upper[lane] <= 0;
        response_chunks[lane] <= 0;
      end else begin
        int next_credits;
        next_credits = available + int'(response_pad_credit[lane]) - int'(sent[lane]);
        if (next_credits < 0 || next_credits > 8)
          $fatal(1, "COLD_MEMORY_RESPONSE_CREDIT lane=%0d value=%0d", lane, next_credits);
        available <= next_credits;
        if (sent[lane]) begin
          response_chunks[lane] <= response_chunks[lane] + 1;
          if (tail) response_pending[lane] <= 0;
          else response_upper[lane] <= 1;
        end
        if (memory_mem_rsp_valid[lane] && memory_mem_rsp_ready[lane]) begin
          response_pending[lane] <= 1;
          response_upper[lane] <= 0;
          response_wide[lane] <= reading[lane] && reading_wide[lane];
          response_last[lane] <= memory_mem_rsp_last[lane];
          response_error[lane] <= memory_mem_rsp_error[lane];
          response_word[lane] <= memory_mem_rsp_data[lane * 512 +: 512];
        end
      end
    end
  end

  always @(posedge clk) if (rst_n) begin
    if (response_pad_fault !== 2'b00 || dut.request_protocol_error !== 1'b0 ||
        (queue_full && tail_valid)) $fatal(1, "COLD_MEMORY_PAD_PROTOCOL");
    if (memory_request_valid) memory_request_bytes++;
  end
