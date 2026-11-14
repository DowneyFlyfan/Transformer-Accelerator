"""Bind the pre-routing timing inputs to the cold-reloaded pad-ring checkpoint."""

from collections import Counter
from decimal import Decimal
from hashlib import file_digest
import json
from pathlib import Path
import re

from tri_oracle_artifact_fingerprint import artifact_fingerprint


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".cache/placement_coordinate_reuse"
TIMING_LIBRARY = re.compile(r"(?m)^Reading (ls_\w+) timing library '?([^'\s]+\.lib)'?(?:\s+\.\.\.|\.)?$")
PHYSICAL_LIBRARY = re.compile(r"(?m)^Loading LEF file (\S+) \.\.\.$")
RC_CORNER = re.compile(r"(?ms)^    RC-Corner Name\s*: (rc_\w+)\n.*?^    RC-Corner Technology file: '([^']+)'$")
CORNERS = {"ls_slow": "ssg0p9v125c.lib", "ls_typ": "tt1v25c.lib", "ls_fast": "ffg1p05vm40c.lib"}


def sha(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def library_contents(directory):
    return {str(path.relative_to(directory)): sha(path)
            for path in directory.rglob("*") if path.is_file()}


def observations(console, directory, inventories):
    """Check that Innovus opened each expected timing and physical input."""
    timing = Counter((corner, Path(path).resolve()) for corner, path in TIMING_LIBRARY.findall(console))
    expected = Counter()
    for corner, suffix in CORNERS.items():
        libraries = [directory / path for path in inventories if path.endswith(suffix)]
        assert len(libraries) == 7, corner
        expected.update((corner, path.resolve()) for path in libraries)
    assert timing == expected, "Timing library inventory differs"

    abstracts = [directory / path for path in inventories if path.startswith("lef/")]
    assert len(abstracts) == 8
    assert Counter(Path(path) for path in PHYSICAL_LIBRARY.findall(console)) == Counter(abstracts)

    corners = {name: directory / path for path in inventories
               if (name := Path(path).parent.name).startswith("rc_")}
    assert corners.keys() == {"rc_slow", "rc_typ", "rc_fast"}
    actual = Counter((name, Path(path)) for name, path in RC_CORNER.findall(console))
    assert actual == Counter(corners.items()), "Extraction corner inventory differs"


def verify():
    assert __debug__ and Path("/.dockerenv").is_file()
    original = WORK / "grouped_active_eco/apply/active.db"
    pad = WORK / "partial_pad_seed_keep_tree"
    restored = pad / "native/pad_ring.db"
    public = ROOT / "records/tri_oracle_partial_pad_native_cold_result.json"
    result = json.loads(public.read_bytes())
    cold = pad / "cold_native/receipt.json"
    assert sha(cold) == result["evidence_sha256"][str(cold.relative_to(ROOT))]
    receipt = json.loads(cold.read_bytes())
    assert receipt["state"] == "full_chip_partial_pad_cold_reload_exactly_verified"
    assert receipt["candidate_sha256"] == result["input_candidate_sha256"]
    checkpoint = artifact_fingerprint(restored)
    assert checkpoint == receipt["checkpoint"]
    inventory = library_contents(restored / "libs")
    assert len(inventory) == 33 and inventory == library_contents(original / "libs")

    console = pad / "cold_native/console.log"
    assert sha(console) == receipt["evidence"][str(console.relative_to(ROOT))]
    text = console.read_text()
    assert text.splitlines().count("TRI_ORACLE_GROUPED_RESET_pad_cold_PASS") == 1
    observations(text, restored / "libs", inventory)
    constraint = restored / "libs/mmmc/candidate.sdc"
    assert sha(constraint) == inventory["mmmc/candidate.sdc"]
    period, = re.findall(r'(?m)^create_clock -name "core_clock" -period (\d+(?:\.\d+)?) '
                         r'-waveform \{0\.0 \S+\} \[get_ports clk\]$', constraint.read_text())
    paper = ROOT / "records/paper_result_targets.json"
    target = json.loads(paper.read_bytes())["peak"]["clock_megahertz"]
    assert abs(Decimal(period) - Decimal(1000) / target) < Decimal("0.00001")
    assert artifact_fingerprint(restored) == checkpoint
    return dict(
        state="pad_ring_cold_restored_timing_and_physical_inputs_verified",
        candidate_netlist_sha256=receipt["candidate_sha256"],
        clock_period_nanoseconds=period, paper_target_megahertz=target,
        identical_library_and_constraint_files=len(inventory), timing_libraries=21,
        physical_abstracts=8, extraction_models=3, constraint_sha256=sha(constraint),
        evidence_sha256={str(path.relative_to(ROOT)): sha(path) for path in
                         (public, cold, console, paper, Path(__file__).resolve())},
        scope="The saved placement and its cold reload use the same physical libraries, extraction models and "
              "clock constraint as the verified buffered candidate. No timing slack was measured.",
    )


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
