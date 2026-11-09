"""Real filesystem regressions for explicit linked-model checkpoint identity."""
from pathlib import Path
import os
import tempfile
import unittest

from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint


ABC_SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
MODEL = {"type": "directory", "files": {
    "core.v": {"size_bytes": 3, "sha256": ABC_SHA256}}}


class HierarchyFingerprintTest(unittest.TestCase):
    def setUp(self):
        Path(".cache/physical").mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(
            prefix="hierarchy_fingerprint_", dir=".cache/physical")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = self.root / "chip.db"
        self.database.mkdir()
        (self.database / "top.dat").write_bytes(b"abc")
        self.model = self.root / "core_model"
        self.model.mkdir()
        (self.model / "core.v").write_bytes(b"abc")

    def link_model(self):
        link = self.database / "libs/ilm"
        link.parent.mkdir()
        link.symlink_to(self.model.resolve(), target_is_directory=True)
        return link

    def test_declared_matching_model_is_bound_into_checkpoint(self):
        # Missing directory-link support must fail this native-layout case.
        self.link_model()
        try:
            result = hierarchy_fingerprint(
                self.database, directory_dependencies={self.model: MODEL})
        except ValueError as error:
            self.fail("A declared, matching model directory must be supported: " + str(error))
        self.assertEqual(result["type"], "hierarchical_directory")
        self.assertEqual(result["files"]["top.dat"],
                         {"size_bytes": 3, "sha256": ABC_SHA256})
        self.assertEqual(result["directory_dependencies"][str(self.model.resolve())], MODEL)
        self.assertEqual(result["directory_links"]["libs/ilm"]["dependency"],
                         str(self.model.resolve()))
        self.assertEqual(result["directory_links"]["libs/ilm"]["symlink_target"],
                         str(self.model.resolve()))

    def test_undeclared_directory_target_is_rejected(self):
        self.link_model()
        with self.assertRaises(ValueError):
            hierarchy_fingerprint(self.database)

    def test_changed_model_content_cannot_keep_old_identity(self):
        self.link_model()
        (self.model / "core.v").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            hierarchy_fingerprint(self.database, directory_dependencies={self.model: MODEL})

    def test_retargeting_link_to_identical_undeclared_model_is_rejected(self):
        link = self.link_model()
        other = self.root / "other_model"
        other.mkdir()
        (other / "core.v").write_bytes(b"abc")
        link.unlink()
        link.symlink_to(other.resolve(), target_is_directory=True)
        with self.assertRaises(ValueError):
            hierarchy_fingerprint(self.database, directory_dependencies={self.model: MODEL})

    def test_nested_directory_cycle_is_rejected(self):
        self.link_model()
        (self.model / "cycle").symlink_to(self.model.resolve(), target_is_directory=True)
        with self.assertRaises(ValueError):
            hierarchy_fingerprint(self.database, directory_dependencies={self.model: MODEL})

    def test_dangling_link_is_rejected(self):
        (self.database / "broken").symlink_to(self.root.resolve() / "absent")
        with self.assertRaises(ValueError):
            hierarchy_fingerprint(self.database)

    def test_plain_database_and_file_links_match_legacy_identity(self):
        (self.database / "empty.aux").write_bytes(b"")
        (self.database / "library.lib").symlink_to((self.model / "core.v").resolve())
        self.assertEqual(hierarchy_fingerprint(self.database),
                         artifact_fingerprint(self.database))

    def test_primary_database_changes_are_detected(self):
        first = hierarchy_fingerprint(self.database)
        (self.database / "top.dat").write_bytes(b"abd")
        self.assertNotEqual(first, hierarchy_fingerprint(self.database))

    def test_model_link_alone_cannot_substitute_for_database_content(self):
        self.link_model()
        (self.database / "top.dat").write_bytes(b"")
        with self.assertRaises(ValueError):
            hierarchy_fingerprint(self.database, directory_dependencies={self.model: MODEL})

    @unittest.skipUnless(hasattr(os, "mkfifo"), "Requires real POSIX special file")
    def test_special_file_is_rejected_without_reading_it(self):
        os.mkfifo(self.database / "pipe")
        with self.assertRaises(ValueError):
            hierarchy_fingerprint(self.database)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "Requires real POSIX special file")
    def test_unbound_special_file_inside_model_is_rejected(self):
        self.link_model()
        os.mkfifo(self.model / "pipe")
        with self.assertRaises(ValueError):
            hierarchy_fingerprint(self.database, directory_dependencies={self.model: MODEL})

    def test_root_symlink_is_rejected(self):
        alias = self.root / "database_alias"
        alias.symlink_to(self.database.resolve(), target_is_directory=True)
        with self.assertRaises(ValueError):
            hierarchy_fingerprint(alias)

    def test_nonempty_file_identity_matches_legacy(self):
        path = self.database / "top.dat"
        self.assertEqual(hierarchy_fingerprint(path), artifact_fingerprint(path))

    def test_legacy_fingerprinter_still_rejects_directory_links(self):
        self.link_model()
        with self.assertRaises(ValueError):
            artifact_fingerprint(self.database)


if __name__ == "__main__":
    unittest.main()
