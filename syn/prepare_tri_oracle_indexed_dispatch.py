"""Add a versioned weight-format word to the grouped command dispatcher."""

import argparse
from pathlib import Path


def prepare(source):
    changes = [
        ("module tri_oracle_chip_dispatch #(", "module tri_oracle_indexed_chip_dispatch #("),
        ("  output logic [PAYLOAD_BITS-1:0] layer_command_payload,",
         "  output logic [PAYLOAD_BITS-1:0] layer_command_payload,\n"
         "  output logic layer_feedforward_indexed,"),
        ("{Idle, Receive, Drain, Issue, Complete, FormatError}",
         "{Idle, Receive, Drain, Issue, Complete, FormatError, FeedforwardFormat}"),
        ("  logic expected_last, selected_done_valid, tag_error;",
         """  logic expected_last, selected_done_valid, tag_error, indexed_descriptor;
  localparam logic [63:0] INDEXED_WEIGHT_FORMAT_V1 = 64'h1;

  assign layer_feedforward_indexed = indexed_descriptor && (state == Issue || state == Complete);"""),
        ("  assign payload_ready = state == Receive || state == Drain;",
         "  assign payload_ready = state == Receive || state == Drain || state == FeedforwardFormat;"),
        ("      word_index <= '0;\n    end else begin", "      word_index <= '0;\n      indexed_descriptor <= 0;\n    end else begin"),
        ("          opcode <= command_opcode;", "          opcode <= command_opcode;\n          indexed_descriptor <= 0;"),
        ("          else if (expected_last)\n            state <= Drain;",
         """          else if (expected_last)
            state <= opcode == FEEDFORWARD ? FeedforwardFormat : Drain;"""),
        ("        Drain: if (payload_valid && payload_last)", """        // The extension is consumed separately. The prior 960 bits,
        // including write-back scales, remain the base descriptor.
        FeedforwardFormat: if (payload_valid) begin
          if (!payload_last)
            state <= Drain;
          else if (payload_data != INDEXED_WEIGHT_FORMAT_V1)
            state <= FormatError;
          else begin
            indexed_descriptor <= 1;
            state <= Issue;
          end
        end
        Drain: if (payload_valid && payload_last)"""),
    ]
    for old, new in changes:
        if source.count(old) != 1:
            raise ValueError(f"Expected one grouped dispatcher occurrence of {old!r}")
        source = source.replace(old, new)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dispatcher", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(prepare(args.dispatcher.read_text()))


if __name__ == "__main__":
    main()
