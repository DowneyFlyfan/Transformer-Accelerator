"""Compare the corrected full-chip packet replay against pinned software rows."""

from argparse import ArgumentParser
from hashlib import file_digest
import json
from pathlib import Path
import re
import shlex

ROOT = Path(__file__).resolve().parents[1]
WORK = Path(
    ".cache/physical/whole_chip_xcelium_speed/booth_joined_chip/native_glue/retry/packet_replay"
)
REFERENCE = Path("records/tri_oracle_trained_attention_output_reference.json")
PEER = Path("verilog/tri_oracle_booth_packet_peer.svh")
PREPARE = Path("syn/prepare_tri_oracle_booth_packet_replay.py")


def sha(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def load(path):
    return json.loads(path.read_text())


def reference_rows(path):
    published = load(REFERENCE)
    assert sha(path) == published["files_sha256"]["attention_accumulators.bin"]
    data = path.read_bytes()
    stride = 4 * 64  # The signed 32-bit accumulators for one query head.
    heads = published["query_heads"]
    assert len(data) == published["rank_count"] * heads * stride
    text = (WORK / "fixture/rows.txt").read_text().splitlines()[1:]
    rows = []
    for index, line in enumerate(text):
        rank, _, reads, raw = line.split()
        row = data[index * heads * stride : index * heads * stride + stride]
        assert int(rank) == published["ranks"][index]
        assert bytes.fromhex(raw)[::-1] == row
        rows.append((int(rank), int(reads), raw))
    assert len(rows) == 2
    return rows


def verify(reference):
    pinned = load(WORK / "prepared.json")
    assert (
        pinned["state"]
        == "trained_packet_attention_fixture_bound_to_corrected_full_chip"
    )
    expected = reference_rows(reference)
    status = load(WORK / "native_status.json")
    assert status["exit_status"] == 0 and status["stop_reason"] is None
    log = WORK / "xrun.log"
    text = log.read_text()
    history = WORK / "xrun.history"
    invocation = next(
        line
        for line in reversed(history.read_text().splitlines())
        if line.startswith("s")
    )
    arguments = shlex.split(invocation.split("):", 1)[1])
    assert (
        arguments[0] == "xrun"
        and arguments[arguments.index("-top") + 1] == pinned["testbench_top"]
    )
    assert str((WORK / "bundle.sv").resolve()) in arguments
    assert f"+FIXTURE={(WORK / 'fixture').resolve()}" in arguments
    assert f"+DUMP={(WORK / 'attention.hex').resolve()}" in arguments
    assert str((WORK / "bundle.sv").resolve()) in text
    assert pinned["testbench_top"] in text
    assert text.count("Simulation complete via $finish(1)") == 1
    assert not re.search(r"\*[EF],", text)
    for line in (
        "WHOLE_CHIP_STATUS_LINK_PASS replies=3 lease_transitions=2",
        "TOKEN_SIGN_FETCH_PASS vectors=576 bursts=577 faults=1",
    ):
        assert text.splitlines().count(line) == 1
    assert re.search(r"(?m)^HOST_CONTROL_RELOCATED_PASS .* restored_words=90$", text)
    measured = re.findall(
        r"(?m)^PACKET_ATTENTION_ROW_PASS rank=(\d+) value_reads=(\d+) at [^\n]+$", text
    )
    assert [(int(rank), int(reads)) for rank, reads in measured] == [
        (rank, reads) for rank, reads, _ in expected
    ]
    n = sum(reads for _, reads, _ in expected)
    assert re.search(
        rf"(?m)^COLD_PACKET_ATTENTION_PASS rows=2 host_words=289 maps=576 context_words=90 "
        rf"reads=[1-9]\d* value_reads={n} wide=[1-9]\d* auxiliary=[1-9]\d*$",
        text,
    )
    (counts,) = re.findall(
        r"(?m)^COLD_PACKET_PHYSICAL_LINK_PASS outgoing_bytes=(\d+) incoming_chunks=(\d+),(\d+)$",
        text,
    )
    outgoing, rising, falling = map(int, counts)
    assert outgoing > 0 and outgoing % 3 == 0 and rising > 0 and falling > 0
    dump = WORK / "attention.hex"
    assert [int(line, 16) for line in dump.read_text().splitlines()] == [
        int(raw, 16) for _, _, raw in expected
    ]
    assert all(
        sha(Path(path)) == key for path, key in pinned["evidence_sha256"].items()
    )
    peer_sources = [
        path
        for path in pinned["evidence_sha256"]
        if path.endswith("/physical_peer.svh") or path == str(PEER)
    ]
    (recorded_peer,) = peer_sources
    assert sha(PEER) == pinned["evidence_sha256"][recorded_peer]
    files = (
        REFERENCE,
        reference,
        log,
        history,
        dump,
        PEER,
        PREPARE,
        WORK / "native_status.json",
        WORK / "prepared.json",
        Path(__file__).resolve().relative_to(ROOT),
    )
    return dict(
        state="corrected_cold_chip_trained_attention_rows_verified_over_physical_ports",
        cold_netlist_sha256=pinned["netlist_sha256"],
        exact_trained_row_ranks=[rank for rank, _, _ in expected],
        external_value_requests=n,
        token_maps=576,
        native_wall_seconds=round(status["wall_seconds"], 3),
        restored_context_words=90,
        outgoing_memory_request_bytes=outgoing,
        received_memory_chunks=[rising, falling],
        scope=pinned["scope"],
        evidence_sha256={str(path): sha(path) for path in files},
    )


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.reference), sort_keys=True, indent=2))
