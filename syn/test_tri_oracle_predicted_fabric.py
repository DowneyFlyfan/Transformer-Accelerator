"""Real shared prediction/selection through all five four-core compute clusters."""
from pathlib import Path
import os
import hashlib
import json
import resource
import subprocess
import tempfile
import time
import unittest
from tri_oracle_process_guard import terminate_process_group

UNITS = ("predicted_dispatch", "strip_predictor", "channel_compactor",
         "fabric_projection", "cluster_projection", "sparse_weight_dma",
         "compute_cluster", "memory_compute", "pe_array", "word_bank")

class PredictedFabricTest(unittest.TestCase):
    def test_shared_prediction_twenty_core_batches_protocol_and_recovery(self):
        def bounded():
            limit = getattr(self, "address_space_limit", 2*1024**3)
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            resource.setrlimit(resource.RLIMIT_CPU, (1800, 1800))
        def run(command, phase, seconds):
            started = time.monotonic()
            log = Path("records") / (getattr(self, "log_prefix", "predicted_fabric") + "_" + phase + ".log")
            with log.open("w") as output:
                child = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, start_new_session=True,
                                         preexec_fn=bounded)
                try:
                    self.native_child_pid = child.pid
                    while child.poll() is None:
                        available = int(next(line.split()[1] for line in
                            Path("/proc/meminfo").read_text().splitlines()
                            if line.startswith("MemAvailable:")))*1024
                        self.assertGreater(available, 4*1024**3)
                        anonymous = int(dict(line.split() for line in
                            Path("/sys/fs/cgroup/memory.stat").read_text().splitlines())["anon"])
                        self.assertLess(anonymous, 20*1024**3)
                        self.assertLess(time.monotonic()-started, seconds, phase)
                        time.sleep(.25)
                    return child.returncode, log.read_text()
                finally:
                    terminate_process_group(child, grace_seconds=2)
        paths = [getattr(self, "source_path", "verilog/tri_oracle_predicted_fabric.sv"),
                 "verilog/tri_oracle_predicted_fabric_tb.sv", __file__] + [
                 getattr(self, "dependency_overrides", {}).get(unit,
                 "verilog/tri_oracle_" + unit + ".sv") for unit in UNITS]
        def digest(path):
            with Path(path).open("rb") as source:
                return hashlib.file_digest(source, "sha256").hexdigest()
        source_hashes = {path: digest(path) for path in paths}
        with tempfile.TemporaryDirectory(prefix="predicted_fabric_", dir=".cache") as folder:
            binary = Path(folder)/"sim.vvp"
            code, output = run(["iverilog", "-g2012", "-s", "tri_oracle_predicted_fabric_tb",
                "-o", str(binary), getattr(self, "source_path", "verilog/tri_oracle_predicted_fabric.sv"),
                *[getattr(self, "dependency_overrides", {}).get(unit,
                    "verilog/tri_oracle_" + unit + ".sv") for unit in UNITS],
                "verilog/tri_oracle_predicted_fabric_tb.sv"], "compile", 120)
            self.assertEqual(code, 0, output[-4000:])
            if hasattr(self, "binary_observer"):
                self.binary_observer(binary)
            args = ["+SMOKE"] if (getattr(self, "smoke_only", False) or
                os.environ.get("TRI_ORACLE_PREDICTED_FABRIC_SMOKE")) else []
            code, output = run(["vvp", "-i", str(binary), *args], "run", 1800)
            self.assertEqual(code, 0, output[-4000:])
            expected_cases = 1 if args else 51
            self.assertEqual(output.count("PREDICTED_FABRIC_CASE_PASS"), expected_cases, output)
            self.assertIn("PREDICTED_FABRIC_PASS cases=" + str(expected_cases), output)
            self.native_stdout = output
        for path, expected in source_hashes.items():
            self.assertEqual(digest(path), expected, "Source changed during run: " + path)
        self.source_sha256 = source_hashes

if __name__ == "__main__":
    unittest.main()
