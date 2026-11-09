"""A matching database checksum alone must not qualify a recovery copy."""
import ast
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from tri_oracle_artifact_fingerprint import artifact_fingerprint


class PhysicalBackupTest(unittest.TestCase):
    def test_real_launcher_rejects_shared_storage_and_accepts_external_library_links(self):
        source = Path("syn/run_tri_oracle_feedforward_physical.sh").read_text()
        program = source.split("<<'PY_CHECK'\n", 1)[1].rsplit("\nPY_CHECK", 1)[0]
        functions = [node for node in ast.parse(program).body
                     if isinstance(node, ast.FunctionDef) and node.name == "require_independent_backup"]
        self.assertEqual(len(functions), 1)
        namespace = {"Path": Path}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "backup_preflight", "exec"), namespace)
        require = namespace["require_independent_backup"]
        with tempfile.TemporaryDirectory(prefix="physical_backup_test_", dir=".cache") as directory:
            root = Path(directory).resolve()
            original = root / "original.db"
            original.mkdir()
            (original / "state.bin").write_bytes(b"immutable physical state")
            library = root / "external_library.lib"
            library.write_bytes(b"shared external read-only model")
            (original / "model.lib").symlink_to(library)
            independent = root / "independent.db"
            shutil.copytree(original, independent, symlinks=True)
            self.assertEqual(artifact_fingerprint(original), artifact_fingerprint(independent))
            require(original, independent)
            aliased = root / "hardlinked.db"
            shutil.copytree(original, aliased, symlinks=True, copy_function=os.link)
            self.assertEqual(artifact_fingerprint(original), artifact_fingerprint(aliased))
            with self.assertRaises(ValueError):
                require(original, aliased)
            (independent / "state.bin").unlink()
            (independent / "state.bin").symlink_to(original / "state.bin")
            with self.assertRaises(ValueError):
                require(original, independent)


if __name__ == "__main__":
    unittest.main()
