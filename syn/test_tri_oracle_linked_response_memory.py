from pathlib import Path
import unittest

from verify_tri_oracle_linked_response_memory import check_snapshot


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.bundle = Path("/fixture/current/bundle.sv")
        self.snapshot = Path("/fixture/current/xcelium.d")
        self.build = (
            f"\t-xmlibdirname {self.snapshot}\n"
            f"\t{self.bundle}\nfile: {self.bundle}\n"
            "\tWriting initial simulation snapshot: worklib.tri_oracle_attention430_tb:sv\n"
            "TOOL: xrun(64): Exiting on Nov 12\n"
        )
        self.replay = (
            f"\t-xmlibdirname {self.snapshot}\n\t-R\n"
            "Loading snapshot worklib.tri_oracle_attention430_tb:sv ... Done\n"
            "Simulation complete via $finish(1) at time 7143030 NS + 0\n"
            "TOOL: xrun(64): Exiting on Nov 12\n"
        )

    def test_accepts_matching_native_transcripts(self):
        check_snapshot(self.build, self.replay, self.bundle, self.snapshot, 7143030)

    def test_rejects_another_replay_snapshot(self):
        stale = self.replay.replace(str(self.snapshot), "/fixture/stale/xcelium.d")
        with self.assertRaisesRegex(ValueError, "replay snapshot"):
            check_snapshot(self.build, stale, self.bundle, self.snapshot, 7143030)

    def test_rejects_a_second_snapshot_argument(self):
        ambiguous = self.replay.replace("\t-R\n", "\t-xmlibdirname /fixture/stale/xcelium.d\n\t-R\n")
        with self.assertRaisesRegex(ValueError, "replay snapshot"):
            check_snapshot(self.build, ambiguous, self.bundle, self.snapshot, 7143030)

    def test_rejects_another_elaboration_bundle(self):
        stale = self.build.replace(str(self.bundle), "/fixture/stale/bundle.sv")
        with self.assertRaisesRegex(ValueError, "elaboration"):
            check_snapshot(stale, self.replay, self.bundle, self.snapshot, 7143030)

    def test_rejects_a_replay_error(self):
        bad = self.replay.replace("Simulation complete", "xmsim: *E,FAULT\nSimulation complete")
        with self.assertRaisesRegex(ValueError, "Native error"):
            check_snapshot(self.build, bad, self.bundle, self.snapshot, 7143030)


if __name__ == "__main__":
    unittest.main()
