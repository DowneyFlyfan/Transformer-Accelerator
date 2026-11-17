module lockstep;
  logic [11:0] controls;
  wire [3:0] reference, mapped;
  boundary_reference rtl(
    .command_valid(controls[0]), .command_ready(controls[1]),
    .command_opcode(controls[4:2]), .response_valid(controls[5]),
    .response_opcode(controls[8:6]), .payload_valid(controls[9]),
    .payload_ready(controls[10]), .payload_last(controls[11]),
    .merge_start(reference[0]), .merge_finish(reference[1]),
    .config_valid(reference[2]), .host_config_enable(reference[3])
  );
  tri_oracle_boundary_control gates(
    .command_valid(controls[0]), .command_ready(controls[1]),
    .command_opcode(controls[4:2]), .response_valid(controls[5]),
    .response_opcode(controls[8:6]), .payload_valid(controls[9]),
    .payload_ready(controls[10]), .payload_last(controls[11]),
    .merge_start(mapped[0]), .merge_finish(mapped[1]),
    .config_valid(mapped[2]), .host_config_enable(mapped[3])
  );
  initial begin
    for (int index = 0; index < 4096; index++) begin
      controls = 12'(index);
      #1;
      if ($isunknown(mapped) || mapped !== reference)
        $fatal(1, "BOUNDARY_GLUE_DIFFERENT input=%0h reference=%0h mapped=%0h",
               controls, reference, mapped);
    end
    $display("TRI_ORACLE_BOUNDARY_GLUE_EQUIVALENT binary_vectors=4096");
    $finish;
  end
endmodule
