"""Verify a component-only placement seed against a linked mapped design."""

import argparse
from collections import Counter
from hashlib import file_digest
import json
import mmap
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from audit_tri_oracle_mapped_redundancy import ENDMODULE, MODULE, TOP
from verify_tri_oracle_pad_cold_reload import components


INSTANCE = re.compile(rb"(?m)^[ \t]+([\w$]+)\s+(\\\S+|[\w$]+)\s*\(\s*\.")


def expanded_instances(path):
    with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as source:
        definitions = {}
        for module in MODULE.finditer(source):
            name = module[1]
            if name in definitions:
                raise ValueError(f"Repeated module {name!r}")
            definitions[name] = module.end(), ENDMODULE.search(source, module.end()).start()

        def walk(master, prefix, ancestors):
            if master in ancestors:
                raise ValueError(f"Recursive module {master!r}")
            begin, end = definitions[master]
            for row in INSTANCE.finditer(source, begin, end):
                child, instance = row.groups()
                name = prefix + instance.removeprefix(b"\\")
                if child in definitions:
                    yield from walk(child, name + b"/", ancestors | {master})
                else:
                    yield name, child

        yield from walk(TOP.encode(), b"", set())


def digest(path):
    with path.open("rb") as handle:
        return file_digest(handle, "sha256").hexdigest()


def verify(candidate, seed, parent):
    input_digests = {str(path): digest(path) for path in (candidate, seed, parent)}
    added = {}
    original, buffered = components(parent), components(seed)
    before_count = Counter()
    for old_name, old_pose in original:
        before_count[old_pose[1]] += 1
        if next(buffered, None) != (old_name, old_pose):
            raise ValueError(f"Parent coordinate or cell changed at {old_name!r}")
    for name, (master, status, x, y, orientation, _) in buffered:
        if status != "PLACED" or name in added:
            raise ValueError(f"Invalid additional component {name!r}")
        added[name] = dict(master=master, x=x, y=y, orientation=orientation)

    with TemporaryDirectory(dir=seed.parent, prefix="seed_component_audit_") as directory:
        work = Path(directory)
        results = []
        for label, rows in (
            ("netlist", expanded_instances(candidate)),
            ("def", ((name.replace(b"\\", b""), pose[0].encode()) for name, pose in components(seed))),
        ):
            raw, ordered = work / f"{label}.tsv", work / f"{label}.sorted"
            with raw.open("xb") as out:
                for name, master in rows:
                    out.write(name + b"\t" + master + b"\n")
            with ordered.open("xb") as out:
                subprocess.run(["sort", "--parallel=2", "-S", "96M", "-T", str(work), str(raw)],
                               env={"LC_ALL": "C"}, check=True, stdout=out)
            raw.unlink()
            results.append(ordered)
        with results[0].open("rb") as expected, results[1].open("rb") as observed:
            count, previous = 0, b""
            for actual, planned in zip(expected, observed, strict=True):
                if actual != planned:
                    raise ValueError(f"Unmatched instance or master: {actual!r} vs {planned!r}")
                name = planned.partition(b"\t")[0]
                if name <= previous:
                    raise ValueError(f"Repeated instance {name!r}")
                previous = name
                count += 1
        inventory_id = digest(results[1])
    if count != sum(before_count.values()) + len(added):
        raise ValueError("Incorrect expanded inventory size")
    if any(digest(Path(path)) != identity for path, identity in input_digests.items()):
        raise ValueError("Input changed during seed verification")
    return dict(candidate_sha256=input_digests[str(candidate)], seed_sha256=input_digests[str(seed)],
                parent_sha256=input_digests[str(parent)], matched_instances=count,
                unchanged_parent_components=sum(before_count.values()),
                unchanged_fixed_parent_macros=before_count["FIXED"],
                new_components={name.replace(b"\\", b"").decode(): pose for name, pose in added.items()},
                sorted_name_and_master_sha256=inventory_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("seed", type=Path)
    parser.add_argument("parent", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.candidate, args.seed, args.parent), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
