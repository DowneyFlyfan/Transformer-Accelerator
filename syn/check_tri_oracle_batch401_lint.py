"""Compare coordinator lint against the published batch 400 source."""

import json
from pathlib import Path
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_batched_predictive400"
BASE = "f145d89638d0d507fd3c48bb247863a3cde101c7"
MEMORIES = {
    "TS5N28HPCPSVTA32X128M2FW": """(
    input logic CLK, CEB, WEB, input logic [4:0] A,
    input logic [127:0] D, BWEB, output logic [127:0] Q
);
    logic [127:0] memory [0:31];
    always @(posedge CLK) if (!CEB) begin
        if (WEB) Q <= memory[A];
        else memory[A] <= (memory[A] & BWEB) | (D & ~BWEB);
    end
endmodule
""",
    "TS5N28HPCPSVTA512X64M4F": """(
    input logic CLK, CEB, WEB, input logic [8:0] A,
    input logic [63:0] D, output logic [63:0] Q
);
    logic [63:0] memory [0:511];
    always @(posedge CLK) if (!CEB) begin
        if (WEB) Q <= memory[A];
        else memory[A] <= D;
    end
endmodule
""",
    "TS6N28HPCPSVTA16X128M2F": """(
    input logic CLKW, CLKR, WEB, REB, input logic [3:0] AA, AB,
    input logic [127:0] D, output logic [127:0] Q
);
    logic [127:0] memory [0:15];
    always @(posedge CLKW) if (!WEB) memory[AA] <= D;
    always @(posedge CLKR) if (!REB) Q <= memory[AB];
endmodule
""",
}


def compare(candidate_text):
    receipt = json.loads((ROOT / "records/batch400_predictive_result.json").read_text())
    sources = [Path(name) for name in receipt["source_sha256"]
               if name.endswith(".sv") and not name.endswith(("_tb.sv", "_hierarchy.sv", TOP + ".sv"))]
    baseline = subprocess.check_output(
        ["git", "show", f"{BASE}:verilog/{TOP}.sv"], cwd=ROOT, text=True,
    )
    reports = {}
    with tempfile.TemporaryDirectory(prefix="batch401_lint_", dir=ROOT / ".cache") as folder:
        work = Path(folder)
        for name, ports_and_body in MEMORIES.items():
            model = work / (name + ".sv")
            model.write_text("`timescale 1ns/1ps\nmodule " + name + ports_and_body)
            sources.append(model)
        for label, source in (("baseline", baseline), ("candidate", candidate_text)):
            coordinator = work / (TOP + ".sv")
            coordinator.write_text(source)
            result = subprocess.run(
                ["verilator", "--lint-only", "-Wall", "-Wno-fatal", "--top-module", TOP,
                 "+define+TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC", *map(str, sources), str(coordinator)],
                cwd=work, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60,
            )
            assert result.returncode == 0, result.stdout
            lines = [line for line in result.stdout.splitlines() if line.startswith("%Warning-")]
            reports[label] = {
                "log": result.stdout,
                "coordinator_warnings": [line for line in lines if f"/{TOP}.sv:" in line],
                "remaining_warnings": [line for line in lines if f"/{TOP}.sv:" not in line],
            }
    return reports


def main():
    candidate = (ROOT / "verilog" / (TOP + ".sv")).read_text()
    reports = compare(candidate)
    for label, result in reports.items():
        (ROOT / ".cache" / f"batch401_lint_{label}.log").write_text(result["log"])
        print(label, "coordinator warnings:", len(result["coordinator_warnings"]),
              "other warnings:", len(result["remaining_warnings"]))
        for warning in result["coordinator_warnings"]:
            match = re.search(r"'(tri_oracle_batched_predictive400\.[A-Za-z0-9_.]+)'", warning)
            print(match.group(1) if match else warning)


if __name__ == "__main__":
    main()
