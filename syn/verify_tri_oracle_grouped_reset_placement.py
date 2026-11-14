"""Compare original component poses with the reset-buffer placement."""
import argparse
from hashlib import file_digest
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

COMPONENT_HEADER = re.compile(r"COMPONENTS (\d+) ;\n")
ADDED_BUFFER = re.compile(r"grouped_([0-4])/(?:[^/]+/)*TRI_GROUPED_RESET_[0-4]_([0-9]+)")
COMPONENT = re.compile(r"^-\s+(\S+)\s+(\S+)\s+.*?\+\s+(PLACED|FIXED)\s+\(\s+(-?\d+)\s+(-?\d+)\s+\)\s+(\w+)")


def summarize(def_file, sorted_file, scratch, plan=None):
    added = {}
    baseline_count = records = fixed = 0
    with def_file.open() as source, sorted_file.open("wb") as output:
        for line in source:
            if header := COMPONENT_HEADER.fullmatch(line):
                break
        else:
            raise ValueError(f"Missing components in {def_file}")
        with subprocess.Popen(
            ["sort", "-S", "128M", "-T", str(scratch)],
            stdin=subprocess.PIPE,
            stdout=output,
            text=True,
            env=os.environ | {"LC_ALL": "C"},
        ) as sorter:
            component = ""
            for line in source:
                if line.rstrip() == "END COMPONENTS":
                    assert not component
                    break
                if line.startswith("- "):
                    assert not component
                component += line
                if not line.rstrip().endswith(";"):
                    continue
                record = " ".join(component.split())
                component = ""
                match = COMPONENT.match(record)
                assert match, record
                name, master, status, x, y, orientation = match.groups()
                records += 1
                if buffer := ADDED_BUFFER.fullmatch(name.replace("\\", "")):
                    assert plan is not None and name not in added
                    key = int(buffer[1]), int(buffer[2])
                    assert master == plan[key] and status == "PLACED", record
                    added[name] = master
                else:
                    baseline_count += 1
                    fixed += status == "FIXED"
                    sorter.stdin.write(record + "\n")
            else:
                raise ValueError(f"Unterminated components in {def_file}")
            sorter.stdin.close()
            assert sorter.wait() == 0
        assert records == int(header[1]), def_file
        if plan is not None:
            assert len(added) == len(plan), def_file
    with sorted_file.open("rb") as stream:
        return dict(original=baseline_count, fixed=fixed, added=len(added),
                    original_component_records_sha256=file_digest(stream, "sha256").hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("plan", type=Path)
    args = parser.parse_args()
    expected = {}
    for group in range(5):
        with (args.plan / f"grouped_{group}.tsv").open() as source:
            next(source)
            for line in source:
                index, master, _ = line.split("\t", 2)
                key = group, int(index)
                assert key not in expected
                expected[key] = master
    assert len(expected) == 3870
    with tempfile.TemporaryDirectory(dir=args.after.parent) as tmp:
        scratch = Path(tmp)
        before = summarize(args.before, scratch / "before.tsv", scratch)
        after = summarize(args.after, scratch / "after.tsv", scratch, expected)
        assert before["original"] == after["original"] == 3761286 and before["fixed"] == after["fixed"] == 631
        same = before["original_component_records_sha256"] == after["original_component_records_sha256"]
        print(json.dumps(dict(original_component_records_identical=same, before=before, after=after), indent=2))
        if not same:
            result = subprocess.run(["cmp", str(scratch / "before.tsv"), str(scratch / "after.tsv")], check=False)
            raise SystemExit(result.returncode or 1)


if __name__ == "__main__":
    main()
