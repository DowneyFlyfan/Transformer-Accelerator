"""A sequence of native restores must preserve every committed transcript segment."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import verify_tri_oracle_booth_attention_checkpoint as checkpoint


def save(slot, time_ns):
    return (f"Ran until {time_ns} NS + 0\n"
            f"Saved snapshot worklib.checkpoint_{slot}:sv\n"
            f"TRI_UNSEEDED_PACKET_CHECKPOINT checkpoint_{slot}\n")


class CheckpointChainTests(unittest.TestCase):
    def test_two_restarts_use_the_latest_committed_prefix_and_pin_both_segments(self):
        with TemporaryDirectory(dir=".cache") as scratch:
            root = Path(scratch).resolve()
            native = root / "native"
            native.mkdir()
            driver = root / "checkpoint.tcl"
            driver.write_text("# Statically pinned simulation schedule\n")
            original_log = native / "xrun.log"
            original_log.write_text(save("a", 1_200_000) + "discarded original tail\n")
            status = native / "native_status.json"
            status.write_text(json.dumps(dict(exit_status=1, stop_reason=None, log_sha256=checkpoint.digest(original_log))))
            prepared = {"cold_netlist_sha256": "candidate", "command": ["/opt/cadence/bin/xrun", "-64bit"]}

            def resumed(prefix, used_index, next_time, previous=None):
                facts, _, committed = checkpoint.checkpoint_prefix(prefix)
                stage = root / f"recovery_after_{facts['checkpoint_time_ns']}ns"
                stage.mkdir()
                log = stage / "resume.log"
                definition = dict(facts, cold_netlist_sha256="candidate",
                                  state="checkpoint_output_prepared_for_restore",
                                  restore=checkpoint.restore_invocation(prepared, facts, log))
                if previous:
                    definition["source_recovery"] = previous.name
                    definition["source_status_sha256"] = checkpoint.digest(previous / "resume_status.json")
                archived = stage / "checkpoint_prefix.log"
                archived.write_text(committed)
                definition["replay_prefix_sha256"] = checkpoint.digest(archived)
                (stage / "prepared_recovery.json").write_text(json.dumps(definition))
                snapshot = facts["snapshot"]
                next_slot = "b" if used_index % 2 == 0 else "a"
                log.write_text(f"\t-r {snapshot}\n\t-input {driver}\n\t-log {log}\n"
                               f"Loading snapshot {snapshot} ........ Done\n"
                               f"TRI_UNSEEDED_PACKET_RESTORE {used_index}\n"
                               f"{save(next_slot, next_time)}discarded resumed tail\n")
                (stage / "resume_status.json").write_text(json.dumps(
                    dict(exit_status=1, stop_reason=None, log_sha256=checkpoint.digest(log))))
                return stage

            with patch.multiple(checkpoint, WORK=root, NATIVE=native, DRIVER=driver):
                initial = original_log.read_text()
                first = resumed(initial, 0, 16_200_000)
                first_text, restored_at = checkpoint.resumed_checkpoint_text(first, initial, prepared)
                self.assertEqual(restored_at, 1_200_000)
                second = resumed(first_text, 1, 31_200_000, first)
                second_text, restored_at = checkpoint.resumed_checkpoint_text(second, initial, prepared)
                facts, _, prefix = checkpoint.checkpoint_prefix(second_text)
                self.assertEqual(restored_at, 16_200_000)
                self.assertEqual(facts["checkpoint_count"], 3)
                self.assertEqual(facts["checkpoint_time_ns"], 31_200_000)
                self.assertNotIn("discarded", prefix)
                with (first / "resume.log").open("a") as stream:
                    stream.write("altered predecessor\n")
                with self.assertRaises(AssertionError):
                    checkpoint.resumed_checkpoint_text(second, initial, prepared)


if __name__ == "__main__":
    unittest.main()
