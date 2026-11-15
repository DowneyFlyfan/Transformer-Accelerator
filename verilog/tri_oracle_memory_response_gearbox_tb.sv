`timescale 1ns/1ps

module tri_oracle_memory_response_gearbox_tb;
  localparam int BurstsPerCluster = 9;
  logic clk = 0, rst_n = 0, checking = 0;
  always #5 clk = ~clk;

  logic [4:0] client_req_valid = 0, client_req_ready;
  logic [4:0][63:0] client_req_address = 0;
  logic [4:0][5:0] client_req_length = 0;
  logic [4:0] client_rsp_valid, client_rsp_ready = 0;
  logic [4:0] client_rsp_last, client_rsp_error;
  logic [4:0][511:0] client_rsp_data;
  logic [1:0] mem_req_valid, mem_req_ready = 0;
  logic [1:0][63:0] mem_req_address;
  logic [1:0][5:0] mem_req_length;
  logic [1:0] mem_rsp_valid, mem_rsp_last, mem_rsp_error, mem_rsp_ready;
  logic [1:0][511:0] mem_rsp_data;
  logic [1:0] in_valid = 0, in_ready, in_last = 0, in_error = 0;
  logic [1:0][2:0] in_words = 0;
  logic [1:0][447:0] in_data = 0;

  tri_oracle_grouped_read_fabric_cells dut (
    .clk, .rst_n, .client_req_valid, .client_req_ready, .client_rsp_valid, .client_rsp_ready,
    .client_rsp_last, .client_rsp_error, .mem_req_valid, .mem_req_ready,
    .mem_rsp_valid, .mem_rsp_last, .mem_rsp_error, .mem_rsp_ready,
    .\client_req_address[0] (client_req_address[0]), .\client_req_address[1] (client_req_address[1]),
    .\client_req_address[2] (client_req_address[2]), .\client_req_address[3] (client_req_address[3]),
    .\client_req_address[4] (client_req_address[4]),
    .\client_req_length[0] (client_req_length[0]), .\client_req_length[1] (client_req_length[1]),
    .\client_req_length[2] (client_req_length[2]), .\client_req_length[3] (client_req_length[3]),
    .\client_req_length[4] (client_req_length[4]),
    .\client_rsp_data[0] (client_rsp_data[0]), .\client_rsp_data[1] (client_rsp_data[1]),
    .\client_rsp_data[2] (client_rsp_data[2]), .\client_rsp_data[3] (client_rsp_data[3]),
    .\client_rsp_data[4] (client_rsp_data[4]),
    .\mem_req_address[0] (mem_req_address[0]), .\mem_req_address[1] (mem_req_address[1]),
    .\mem_req_length[0] (mem_req_length[0]), .\mem_req_length[1] (mem_req_length[1]),
    .\mem_rsp_data[0] (mem_rsp_data[0]), .\mem_rsp_data[1] (mem_rsp_data[1])
  );

  for (genvar lane = 0; lane < 2; lane++) begin : g_lanes
    tri_oracle_memory_response_gearbox gearbox (
      .clk, .rst_n, .in_valid(in_valid[lane]), .in_ready(in_ready[lane]),
      .in_data(in_data[lane]), .in_words(in_words[lane]), .in_last(in_last[lane]),
      .in_error(in_error[lane]), .out_valid(mem_rsp_valid[lane]), .out_ready(mem_rsp_ready[lane]),
      .out_data(mem_rsp_data[lane]), .out_last(mem_rsp_last[lane]), .out_error(mem_rsp_error[lane])
    );
  end

  int offered[5] = '{default:0}, completed[5] = '{default:0};
  int owner[2] = '{-1, -1}, transmitted[2] = '{0, 0}, delivered[2] = '{0, 0};
  int previous_input[2] = '{0, 0}, chunk_count[2] = '{0, 0};
  bit [1:0] stalled_input = 0, stalled_output = 0;
  logic [1:0][513:0] held_output;
  bit [7:1] lengths_seen = 0;
  int cycle = 0, response_beats = 0, input_chunks = 0, input_stalls = 0;
  int output_stalls = 0, errors = 0, full_rate_bursts = 0, concurrent_responses = 0;

  function automatic logic [63:0] address(input int client, number);
    return (64'(client) << 16) | (64'(number) << 6);
  endfunction

  function automatic int length(input int client, number);
    return number == 0 ? 56 : 1 + (client + number * 5) % 13;
  endfunction

  function automatic logic [63:0] word(input int client, number, element);
    return 64'h9834_dcfe_1234_5678 ^ (64'(client) << 30) ^ (64'(number) << 51) ^ 64'(element);
  endfunction

  function automatic bit error_status(input int client, number, beat);
    return number != 0 && (client + number + beat) % 7 == 0;
  endfunction

  always @(posedge clk) if (checking) begin : compare_transfers
    logic [4:0] expected_valid, expected_ready;
    expected_valid = 0;
    expected_ready = 0;
    if (mem_rsp_valid == 2'b11) concurrent_responses++;
    for (int lane = 0; lane < 2; lane++) begin
      int client, number, beats;
      bit final_beat;
      client = owner[lane];
      if (stalled_output[lane] &&
          {mem_rsp_valid[lane], mem_rsp_last[lane], mem_rsp_error[lane], mem_rsp_data[lane]}
          !== {1'b1, held_output[lane]})
        $fatal(1, "Gearbox changed a stalled response");
      stalled_input[lane] = in_valid[lane] && !in_ready[lane];
      stalled_output[lane] = mem_rsp_valid[lane] && !mem_rsp_ready[lane];
      held_output[lane] = {mem_rsp_last[lane], mem_rsp_error[lane], mem_rsp_data[lane]};
      input_stalls += int'(stalled_input[lane]);
      output_stalls += int'(stalled_output[lane]);
      if (mem_req_valid[lane] && mem_req_ready[lane]) begin
        if (client != -1) $fatal(1, "Read lane reused before prior burst retired");
        client = int'(mem_req_address[lane][18:16]);
        if (client >= 5 || !client_req_valid[client] || offered[client] != completed[client] ||
            mem_req_address[lane] !== address(client, offered[client]) ||
            mem_req_length[lane] !== 6'(length(client, offered[client])))
          $fatal(1, "Mapped read request did not match the client");
        expected_ready[client] = 1;
        owner[lane] = client;
        offered[client]++;
        transmitted[lane] = 0;
        delivered[lane] = 0;
        chunk_count[lane] = 0;
        previous_input[lane] = 0;
      end
      if (in_valid[lane] && in_ready[lane]) begin
        if (owner[lane] < 0) $fatal(1, "Ingress accepted unsolicited data");
        if (completed[owner[lane]] == 0 &&
            (in_words[lane] != 7 || (chunk_count[lane] != 0 && previous_input[lane] != cycle-1)))
          $fatal(1, "Gap in full-rate 448-bit input");
        previous_input[lane] = cycle;
        chunk_count[lane]++;
        transmitted[lane] += int'(in_words[lane]);
        lengths_seen[in_words[lane]] = 1;
        input_chunks++;
      end
      if (mem_rsp_valid[lane]) begin
        if (client == -1) $fatal(1, "Unsolicited complete beat");
        number = completed[client];
        beats = length(client, number);
        final_beat = delivered[lane] + 1 == beats;
        expected_valid[client] = 1;
        if (client_rsp_last[client] !== final_beat ||
            client_rsp_error[client] !== error_status(client,number,delivered[lane]))
          $fatal(1, "Burst status was attached to the wrong beat");
        for (int item = 0; item < 8; item++)
          if (client_rsp_data[client][item*64+:64] !== word(client,number,delivered[lane]*8+item))
            $fatal(1, "Incorrect beat data client=%0d beat=%0d word=%0d",client,delivered[lane],item);
        if (mem_rsp_ready[lane]) begin
          response_beats++;
          errors += int'(client_rsp_error[client]);
          delivered[lane]++;
          if (final_beat) begin
            if (transmitted[lane] != beats*8) $fatal(1, "Incorrect transferred word count");
            if (number == 0) begin
              if (chunk_count[lane] != 64) $fatal(1, "56 beats required more than 64 full input chunks");
              full_rate_bursts++;
            end
            owner[lane] = -1;
            completed[client]++;
          end
        end
      end
    end
    if (client_req_ready !== expected_ready || client_rsp_valid !== expected_valid)
      $fatal(1, "Response delivered to the wrong cluster");
  end

  initial begin
    int expected_beats = 0, expected_errors = 0, done;
    repeat (3) @(negedge clk);
    rst_n = 1;
    // Discard a partial frame and a stalled completed beat together.
    in_valid = 2'b11;
    in_words = {3'd3,3'd7};
    @(negedge clk);
    in_valid = 2'b01;
    @(negedge clk);
    if (mem_rsp_valid !== 2'b01) $fatal(1, "Missing complete beat before reset");
    rst_n = 0;
    in_valid = 0;
    repeat (2) @(negedge clk);
    if (mem_rsp_valid !== 0) $fatal(1, "Reset left a pending response");
    rst_n = 1;
    checking = 1;
    for (int client = 0; client < 5; client++)
      for (int number = 0; number < BurstsPerCluster; number++) begin
        expected_beats += length(client,number);
        for (int beat = 0; beat < length(client,number); beat++)
          expected_errors += int'(error_status(client,number,beat));
      end

    for (cycle = 1; cycle < 5000; cycle++) begin
      done = 0;
      for (int client = 0; client < 5; client++) begin
        done += int'(completed[client] == BurstsPerCluster);
        client_req_valid[client] = offered[client] == completed[client] && offered[client] < BurstsPerCluster;
        client_req_address[client] = address(client,offered[client]);
        client_req_length[client] = 6'(length(client,offered[client]));
        client_rsp_ready[client] = completed[client] == 0 || (cycle+client*7)%23 >= 9;
      end
      if (done == 5) break;
      for (int lane = 0; lane < 2; lane++) begin
        int client, number, count, sent, total;
        mem_req_ready[lane] = (cycle+lane)%5 != 3;
        if (stalled_input[lane]) continue;
        in_valid[lane] = 0;
        client = owner[lane];
        if (client < 0) continue;
        number = completed[client];
        total = length(client,number)*8;
        sent = transmitted[lane];
        if (sent == total || (number != 0 && (cycle+lane)%11 == 0)) continue;
        count = number == 0 ? 7 : 1+(cycle+lane+number)%7;
        if (count > total-sent) count = total-sent;
        for (int item = 0; item < 7; item++) in_data[lane][item*64+:64] = word(client,number,sent+item);
        in_valid[lane] = 1;
        in_words[lane] = 3'(count);
        in_last[lane] = sent+count == total;
        in_error[lane] = (sent%8+count >= 8) && error_status(client,number,sent/8);
      end
      @(negedge clk);
    end
    if (done != 5 || response_beats != expected_beats || errors != expected_errors ||
        lengths_seen != '1 || input_stalls == 0 || output_stalls == 0 ||
        full_rate_bursts != 5 || concurrent_responses == 0)
      $fatal(1, "Missing ingress coverage or completion");
    $display("TRI_ORACLE_MEMORY_RESPONSE_GEARBOX_PASS bursts=%0d beats=%0d chunks=%0d errors=%0d input_stalls=%0d output_stalls=%0d simultaneous=%0d full_rate=%0d",
      5*BurstsPerCluster,response_beats,input_chunks,errors,input_stalls,output_stalls,concurrent_responses,full_rate_bursts);
    $finish;
  end
endmodule
