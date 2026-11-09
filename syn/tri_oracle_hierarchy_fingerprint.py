"""Explicit closed-dependency identity for hierarchical native databases."""
import hashlib
import os
from pathlib import Path

from tri_oracle_artifact_fingerprint import artifact_fingerprint


def hierarchy_fingerprint(path, *, directory_dependencies=None):
    """Bind a native database and its declared, immutable model directories.

    Dependency identities must come from previously verified producer records.
    Models may contain ordinary files and file links, as supported by the legacy
    fingerprinter. Nested directory links are rejected rather than followed.
    A saved database still needs its own positive file content.
    """
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        return artifact_fingerprint(root)
    allowed = {}
    for target, expected in (directory_dependencies or {}).items():
        try:
            resolved = Path(target).resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ValueError("Missing or cyclic declared model: " + str(target)) from error
        if resolved in allowed and allowed[resolved] != expected:
            raise ValueError("Conflicting declared model identities: " + str(resolved))
        allowed[resolved] = expected
    files = {}
    links = {}
    dependencies = {}

    def visit(directory):
        for child in sorted(directory.iterdir()):
            relative = str(child.relative_to(root))
            raw_link = None
            actual = child
            if child.is_symlink():
                raw_link = os.readlink(child)
                try:
                    actual = child.resolve(strict=True)
                except (OSError, RuntimeError) as error:
                    raise ValueError("Missing or cyclic database link: " + str(child)) from error
                if actual.is_dir():
                    if actual not in allowed:
                        raise ValueError("Undeclared model directory: " + str(actual))
                    key = str(actual)
                    if key not in dependencies:
                        # Legacy manifests bind regular files and file links.
                        # Reject anything they would leave unbound or recurse.
                        for member in actual.rglob("*"):
                            if member.is_symlink() and not member.is_file():
                                raise ValueError("Unsupported nested model link: " + str(member))
                            if not member.is_file() and not member.is_dir():
                                raise ValueError("Unsupported model object: " + str(member))
                        fingerprint = artifact_fingerprint(actual)
                        if fingerprint != allowed[actual]:
                            raise ValueError("Model dependency changed: " + key)
                        dependencies[key] = fingerprint
                    links[relative] = {"symlink_target": raw_link, "dependency": key}
                    continue
            if actual.is_file():
                with actual.open("rb") as stream:
                    checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                entry = {"size_bytes": actual.stat().st_size, "sha256": checksum}
                if raw_link is not None:
                    entry["symlink_target"] = raw_link
                files[relative] = entry
            elif actual.is_dir():
                visit(actual)
            else:
                raise ValueError("Unsupported database object: " + str(child))

    visit(root)
    if not files or sum(entry["size_bytes"] for entry in files.values()) == 0:
        raise ValueError("Empty native database: " + str(root))
    if not links:
        return {"type": "directory", "files": files}
    return {"type": "hierarchical_directory", "files": files,
            "directory_links": links, "directory_dependencies": dependencies}
