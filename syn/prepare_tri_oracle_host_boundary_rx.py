"""Extend the verified normalization receiver at its record boundary."""

import argparse
from pathlib import Path

from measure_tri_oracle_serial_memory_requests import digest, read, replace


BASE = Path("verilog/tri_oracle_host_normalization_rx.sv")
REFERENCE = Path("records/tri_oracle_host_normalization_packets.json")
EXPECTED_RTL = "tri_oracle_host_boundary_rx"


def receiver():
    record = read(REFERENCE)
    assert digest(BASE) == record["evidence_sha256"][str(BASE)]
    source = replace(BASE.read_text(), "module tri_oracle_host_normalization_rx", f"module {EXPECTED_RTL}")
    source = replace(source, "  input logic forward_ready,\n", """  input logic forward_ready,
  output logic control_valid,
  input logic control_ready,
  output logic [1:0] control_action,
""")
    source = replace(source, "  logic auxiliary, local_header,", "  logic sideband_header, auxiliary, local_header,")
    source = replace(source, "  assign forwarding = state == ForwardBody || (state == RecordStart && !local_header);\n"
                     "  assign rx_ready = rst_n && (forwarding ? forward_ready : state != Pending);",
                     """  assign sideband_header = auxiliary && (rx_data == 16'hA67E || rx_data[15:1] == 15'h5341);
  assign control_valid = rst_n && state == RecordStart && sideband_header && rx_valid;
  assign control_action = rx_data == 16'hA67E ? 2'd0 : rx_data[0] ? 2'd2 : 2'd1;
  assign forwarding = state == ForwardBody ||
                      (state == RecordStart && !local_header && !sideband_header);
  always_comb begin
    if (!rst_n || state == Pending) rx_ready = 1'b0;
    else if (state == RecordStart && sideband_header) rx_ready = control_ready;
    else if (forwarding) rx_ready = forward_ready;
    else rx_ready = 1'b1;
  end""")
    return replace(source, "      RecordStart: if (transfer) begin", "      RecordStart: if (transfer && !sideband_header) begin")


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with args.output.open("x") as output:
        output.write(receiver())
