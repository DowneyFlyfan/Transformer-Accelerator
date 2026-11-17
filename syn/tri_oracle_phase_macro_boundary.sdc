# Ideal clocks use the trained replay's phase and input budget. Macro pins
# provide the output loads.
create_clock -name memory_clock -period 0.862 -waveform {0.000 0.431} [get_ports memory_clk]
if {[sizeof_collection [get_ports -quiet core_clk]] == 1} {
    create_clock -name core_clock -period 1.724 -waveform {0.431 1.293} [get_ports core_clk]
} else {
    set divider_q [get_pins clock_source/divider_core_clk_reg/Q]
    if {[sizeof_collection $divider_q] != 1} {error "Missing clock divider output"}
    create_generated_clock -name core_clock -source [get_ports memory_clk] -edges {2 4 6} $divider_q
}
set_clock_uncertainty 0.030 [get_clocks {memory_clock core_clock}]
set core_inputs [get_ports {read_cores* read_address* write_pending* write_allowed* write_core* write_address* write_rows* write_payload*}]
set_input_delay -max 0.20 -clock core_clock $core_inputs
set_input_delay -min 0.10 -clock core_clock $core_inputs
set_input_transition 0.05 $core_inputs
set_output_delay -max 0.10 -clock core_clock [get_ports {write_retired*}]
set_output_delay -min -0.10 -clock core_clock [get_ports {write_retired*}]
set_false_path -from [get_ports rst_n]
