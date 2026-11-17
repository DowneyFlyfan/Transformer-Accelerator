"""Allow a matrix read and an activation load to address distinct input banks."""

from prepare_tri_oracle_early_weight_pairs import edit

ACTIVATION_MACRO = "TS5N28HPCPSVTA512X64M4F"
TIMED_ACTIVATION_MACRO = f"TRI_ORACLE_TIMED_{ACTIVATION_MACRO}"


def prepare_activation_core(source, timed=False):
    source = edit(source, [
        ("logic [8:0] input_address;", "logic [1:0][8:0] input_address;"),
        ("logic [8:0] imem_address;", "logic [1:0][8:0] imem_address;"),
        ("assign imem_address = softmax_owns_input ? simd_mem_address : input_address;",
         "assign imem_address = softmax_owns_input ? {2{simd_mem_address}} : input_address;"),
        ("    cmd_ready = compute_enabled && array_ready && !accepted_load;",
         """    cmd_ready = compute_enabled && array_ready &&
                !(accepted_load && (load_kind != 1 || load_addr[9] == cmd_activation[9]));"""),
        ("""    mask_address = accepted_load ? load_addr[4:0] : cmd_mask;
    input_address = accepted_load ? load_addr[8:0] : cmd_activation[8:0];""",
         "    mask_address = accepted_load && load_kind == 2 ? load_addr[4:0] : cmd_mask;"),
        ("""                         && load_addr[9] == 1'(bank));
      input_ceb[bank]""",
         """                         && load_addr[9] == 1'(bank));
      input_address[bank] = input_web[bank] ? cmd_activation[8:0] : load_addr[8:0];
      input_ceb[bank]"""),
    ])
    if timed:
        source = stage_activation_pins(source)
    return source


def stage_activation_pins(source):
    return edit(source, [
        (f"""  {ACTIVATION_MACRO} inputs[1:0] (
    .CLK(clk), .CEB(imem_ce_n), .WEB(imem_we_n), .A(imem_address),
    .D(imem_d), .Q(input_q)
  );""", f"""  logic activation_sram_clk;
  logic [1:0] activation_ce_n, activation_we_n;
  logic [1:0][8:0] activation_address;
  logic [1:0][63:0] activation_data;

  // Issue at the core edge and sample the registered pins at the subsequent
  // memory edge, alongside the corresponding weight read.
  always_ff @(posedge memory_clk or negedge rst_n) begin
    if (!rst_n) activation_sram_clk <= 0;
    else activation_sram_clk <= clk;
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      activation_ce_n <= '1;
      activation_we_n <= '1;
    end else begin
      activation_ce_n <= imem_ce_n;
      activation_we_n <= imem_we_n;
    end
  end
  always_ff @(posedge clk) begin
    activation_address <= imem_address;
    activation_data <= imem_d;
  end
  {TIMED_ACTIVATION_MACRO} inputs[1:0] (
    .CLK(activation_sram_clk), .CEB(activation_ce_n), .WEB(activation_we_n),
    .A(activation_address), .D(activation_data), .Q(input_q)
  );"""),
    ])


def prepare_activation_cluster(source):
    return edit(source, [
        ("&& !load_valid && count < 16",
         "&& (!load_valid || (load_kind == 1 && load_addr[9] != cmd_activation[9])) && count < 16"),
    ])


def broadcast_chip_activation(tensor, fabric):
    tensor = edit(tensor, [
        (".load_payload,.load_row_enable,.load_error,",
         ".load_payload,.load_row_enable,.load_error,\n    .load_broadcast(state==ACT_BROADCAST && !local_scores),"),
        ("if(broadcast_cluster==last_cluster)begin", "if(!local_scores || broadcast_cluster==last_cluster)begin"),
    ])
    fabric = edit(fabric, [
        ("input wire clk,rst_n,load_valid,", "input wire clk,rst_n,load_valid,load_broadcast,"),
        (".load_valid(load_valid && load_kind!=0 && load_core[4:2]==3'(cluster)),",
         ".load_valid(load_valid && load_kind!=0 && (load_broadcast || load_core[4:2]==3'(cluster))),"),
    ])
    return tensor, fabric


def prepare_activation_bench(source):
    return edit(source, [
        ("  logic init_valid = 0, reload = 0;", """  logic init_valid = 0, reload = 0, prefetch_done = 0;
  logic prefetch_active = 0, same_bank_probe = 0;
  bit serialize_activation;
  initial serialize_activation = $test$plusargs("SERIAL_ACTIVATIONS");
  int prefetch_writes = 0, concurrent_activation_writes = 0, conflict_stalls = 0;"""),
        ("    if (cmd_accepted) begin\n      reads++;", """    if (prefetch_active && init_valid) begin
      if (init_kind != 1 || init_addr < 512)
        $fatal(1, "ACTIVATION_PREFETCH_WRONG_BANK");
      prefetch_writes++;
      if (cmd_accepted) begin
        if (cmd_activation >= 512) $fatal(1, "ACTIVATION_PREFETCH_OVERWRITE");
        concurrent_activation_writes++;
      end
    end
    if (same_bank_probe) begin
      if (!cmd_valid || cmd_accepted || init_addr[9] != cmd_activation[9])
        $fatal(1, "ACTIVATION_SAME_BANK_COMMAND_NOT_BLOCKED");
      conflict_stalls++;
    end
    if (cmd_accepted) begin
      reads++;"""),
        ("""      for (int tile = 0; tile < 2; tile++)
        for (int token = 0; token < 16; token++)
          for (int word = 0; word < 32; word++)
            initialize_word(1, core, tile*512+token*32+word,
                            2048'(activations[((tile*32+word)*16+token)*4+core%4]));""",
         """      for (int token = 0; token < 16; token++)
        for (int word = 0; word < 32; word++)
          initialize_word(1, core, token*32+word, 2048'(activations[(word*16+token)*4+core%4]));"""),
        ("""    allow_issue = 1;
    wait (projection_done);""", """    if (!serialize_activation) begin
      initialize_word(1, 0, 5, 2048'(activations[5*16*4]));
      same_bank_probe = 1;
    end
    allow_issue = 1;
    if (!serialize_activation) begin
      @(negedge clk);
      init_valid = 0;
      same_bank_probe = 0;
    end
    fork begin
      if (serialize_activation) wait (projection_done);
      prefetch_active = 1;
      for (int core = 0; core < 20; core++)
        for (int token = 0; token < 16; token++)
          for (int word = 0; word < 32; word++)
            initialize_word(1, core, 512+token*32+word,
                            2048'(activations[((32+word)*16+token)*4+core%4]));
      @(negedge clk);
      init_valid = 0;
      prefetch_active = 0;
      prefetch_done = 1;
    end join_none
    wait (projection_done);"""),
        ("    wait (stage_done);\n    @(negedge clk);",
         "    wait (stage_done && prefetch_done);\n    @(negedge clk);"),
        ("""    $display("COMPILED_CLUSTER_WEIGHT_FABRIC clusters=5 cores=20 dual_cluster_writes=%0d",
             parallel_writes);""", """    $display("COMPILED_CLUSTER_WEIGHT_FABRIC clusters=5 cores=20 dual_cluster_writes=%0d",
             parallel_writes);
    if (prefetch_writes != 10240 ||
        (serialize_activation ? (concurrent_activation_writes != 0 || conflict_stalls != 0) :
                  (concurrent_activation_writes < 500 || conflict_stalls != 1)))
      $fatal(1, "ACTIVATION_PREFETCH_COVERAGE writes=%0d concurrent=%0d conflicts=%0d",
             prefetch_writes, concurrent_activation_writes, conflict_stalls);
    $display("ACTIVATION_PREFETCH_PASS writes=%0d concurrent=%0d same_bank_stalls=%0d",
             prefetch_writes, concurrent_activation_writes, conflict_stalls);"""),
    ])
