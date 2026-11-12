"""Compare the joined decoder's simulator observations across source and gates."""

from collections import Counter
import re


TRAINED_MARKERS = {
    "BATCH408_PASS": 1,
    "BATCH408_ACTIVATION_PASS": 1,
    "BATCH408_SHARED_BUS": 1,
    "DUAL_LANE_PACKED_SIGN_PASS": 1,
    "PACKED_DECODER_PASS": 1,
    "PACKED_PAIR_BRANCHES": 1,
    "PARALLEL_CHIP_READS": 1,
    "PARALLEL_CHIP_BRANCHES": 2,
    "PARALLEL_CHIP_DOWN_IMAGE": 1,
    "PARALLEL_CHIP_PAIR_IMAGE": 1,
    "UNIFIED_CHIP_FEEDFORWARD_PASS": 1,
}
ATTENTION_MARKERS = {"COMPOSE430_PASS": 1, "COMPOSE430_SHARED_READ_PASS": 1, "COMPOSE430_SHARED_WRITE_PASS": 1}
DIRECTED_MARKERS = {name: count for name, count in TRAINED_MARKERS.items() if not name.endswith("_IMAGE")}


def observations(text, required, optional=()):
    assert text.count("Simulation complete via $finish(1)") == 1
    assert not re.search(r"\*[EF],|\*ERROR|Simulation terminated via \$fatal", text)
    relevant = required.keys() | set(optional)
    lines = []
    counts = Counter()
    for line in text.splitlines():
        name, separator, _ = line.partition(" ")
        if separator and name in relevant:
            counts[name] += 1
            lines.append(line)
    assert all(counts[name] == count for name, count in required.items()), (required, counts)
    return lines


def compare_attention(mapped_log, source_log):
    baseline = observations(source_log.read_text(), ATTENTION_MARKERS)
    measured = observations(mapped_log.read_text(), ATTENTION_MARKERS)
    assert measured == baseline, (baseline, measured)
    return measured


def compare_decoder(mapped_log, source_log, mapped_progress, source_progress, *, trained, fault=0):
    required = TRAINED_MARKERS.copy() if trained else DIRECTED_MARKERS.copy()
    if fault:
        required["BATCH408_FAULT_DRAINED"] = 1
    required["UNIFIED_CHIP_FEEDFORWARD_RESPONSE"] = 2 if fault else 1
    baseline = observations(source_log.read_text(), required, ("BATCH408_FAULT_DRAINED",))
    measured = observations(mapped_log.read_text(), required, ("BATCH408_FAULT_DRAINED",))
    assert measured == baseline, (baseline, measured)
    sign, = (line for line in measured if line.startswith("DUAL_LANE_PACKED_SIGN_PASS "))
    finish, = (line for line in measured if line.startswith("BATCH408_PASS "))
    transport, = (line for line in measured if line.startswith("PACKED_DECODER_PASS "))
    counters = dict((key, int(value)) for key, value in (item.split("=") for item in finish.split()[1:]))
    count = 9152 if trained else 16
    assert sign.startswith(f"DUAL_LANE_PACKED_SIGN_PASS requests={count} responses={count} ")
    assert counters["trained"] == int(trained) and counters["exact_outputs"] == (32768 if trained else 504)
    assert counters["fault"] == fault
    if fault:
        assert f"BATCH408_FAULT_DRAINED fault={fault} output_prefix_packets=0" in measured
    else:
        assert not any(line.startswith("BATCH408_FAULT_DRAINED ") for line in measured)
    progress = mapped_progress.read_bytes()
    assert progress == source_progress.read_bytes() and progress.endswith(b"BATCH408_DONE\n")
    cycles, = re.findall(r" cycles=(\d+)$", transport)
    return {"counters": counters, "packed_sign_transactions": count, "cycles": int(cycles),
            "milestones": len(progress.splitlines()), "matched_observations": measured}
