"""Map the dual-lane chip parent after its source and interface checks pass."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import time

from prepare_tri_oracle_parallel_chip_synthesis import AUX_PORTS, TOP, pin, read, verify, width
from tri_oracle_process_guard import terminate_process_group
from verify_linked_placed_topology import module_index, parse_module
from verify_tri_oracle_packed_down_weights import ROOT, sha256


GIB = 2**30


def proc_identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except FileNotFoundError:
        return None
    return None if fields[0] in ("Z", "X") else fields[19]


def wait_for_receipt(receipt, worker, *scripts):
    started = proc_identity(worker)
    if not receipt.is_file():
        assert started, (worker, "worker ended before publishing", receipt)
        try:
            argv = Path(f"/proc/{worker}/cmdline").read_bytes().split(b"\0")
        except FileNotFoundError:
            assert receipt.is_file(), (worker, "worker ended before publishing", receipt)
        else:
            names = tuple(("/" + script).encode() for script in scripts)
            assert any(item.endswith(names) for item in argv), (worker, scripts)
    deadline = time.monotonic() + 4 * 3600
    print("Waiting for", receipt.name, "from", worker, flush=True)
    while True:
        try:
            return read(receipt)
        except (FileNotFoundError, json.JSONDecodeError):
            assert started and proc_identity(worker) == started, (worker, receipt)
            assert time.monotonic() < deadline, receipt
            time.sleep(5)


def check_source(training, attention, candidate, pins):
    trained = read(training)
    attention_proof = read(attention)
    assert trained["state"] == "parallel_chip_replayed_exact_trained_frame_from_both_packed_images"
    assert attention_proof["state"] == "parallel_chip_preserved_archived_attention"
    assert trained["native"]["native_exit_status"] == attention_proof["native"]["native_exit_status"] == 0
    for proof in (trained, attention_proof):
        verify(proof["input_sha256"])
        name = str((candidate / "prepared.json").relative_to(ROOT))
        assert proof["input_sha256"][name] == pins[name]
    baseline = ROOT / "records/wac_paired_chip_trained_result.json"
    reference = read(baseline)
    assert reference["state"] == "single_packed_lane_matched_full_width_trained_layer_from_checkpoint_images"
    pin(pins, baseline)
    expected = reference["training_frame"]
    actual = trained["counters"]
    assert actual.keys() == expected.keys()
    assert all(actual[key] == expected[key] for key in expected if key not in ("read_requests", "read_bytes"))
    assert actual["exact_outputs"] == 32768 and attention_proof["counters"]["rows"] == 4
    lane_totals = trained["responses_by_lane"]
    assert len(lane_totals) == 2 and all(all(value > 0 for value in lane.values()) for lane in lane_totals)
    assert trained["simultaneous_responses"] > 0
    for key, count in reference["packed_weight_responses_by_projection"].items():
        assert sum(lane[key] for lane in lane_totals) == count, key
    pin(pins, training)
    pin(pins, attention)
    return trained["simulated_cycles"]


def check_elaboration(output, setup, pins):
    status = output / "native_status.json"
    native = read(status)
    assert native["exit_status"] == 0 and native["stop_reason"] is None
    log = output / "console.log"
    assert log.read_text().splitlines().count("TRI_ORACLE_PARALLEL_CHIP_GENUS_ELABORATION_PASS") == 1
    ledger = output / "cut_inventory.tsv"
    found = {}
    for line in ledger.read_text().splitlines():
        raw, master, hpins = line.split("\t")
        name = raw.replace("\\", "").removeprefix(TOP + "/").replace("/", ".")
        assert name not in found and int(hpins) > 0, line
        found[name] = master
    assert found == {name: item["source_module"] for name, item in setup["preserved"].items()}, found
    for path in (status, log, ledger, output / "port_inventory.tsv", output / "elaborate.tcl"):
        pin(pins, path)


def memory():
    def read_value(path, field):
        with Path(path).open() as source:
            return next(int(line.split()[1]) for line in source if line.startswith(field))

    return (1024 * read_value("/proc/meminfo", "MemAvailable:"),
            read_value("/sys/fs/cgroup/memory.stat", "anon "))


def map_parent(script, output):
    deadline = time.monotonic() + 4 * 3600
    available, anonymous = memory()
    while available < 18.5 * GIB or anonymous > 3.5 * GIB:
        assert time.monotonic() < deadline, (available, anonymous)
        time.sleep(5)
        available, anonymous = memory()
    native_log = output / "genus"
    console = output / "console.log"
    cmd = ["/usr/bin/prlimit", f"--as={6 * GIB}", "--", "/opt/cadence/bin/genus",
           "-batch", "-files", str(script), "-log", str(native_log)]
    (output / "invocation.json").write_text(json.dumps({"argv": cmd}, indent=2) + "\n")
    started = time.monotonic()
    minimum, peak = available, anonymous
    stop_reason = None
    with console.open("x") as stream:
        process = subprocess.Popen(cmd, cwd=output, stdout=stream, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
        print("Dual-lane parent Genus synthesis started", process.pid, flush=True)
        try:
            while process.poll() is None:
                available, anonymous = memory()
                minimum, peak = min(minimum, available), max(peak, anonymous)
                if minimum < 13.5 * GIB or peak > 8 * GIB or time.monotonic() - started > 7200:
                    stop_reason = {"host_available_bytes": minimum, "anonymous_bytes": peak,
                                   "elapsed_seconds": time.monotonic() - started}
                    break
                time.sleep(1)
        finally:
            terminate_process_group(process, log_argument=str(native_log))
    result = {"native_exit_status": process.returncode, "stop_reason": stop_reason,
              "elapsed_seconds": time.monotonic() - started, "minimum_host_available_bytes": minimum,
              "peak_cgroup_anonymous_bytes": peak}
    (output / "native_status.json").write_text(json.dumps(result, indent=2) + "\n")
    assert process.returncode == 0 and stop_reason is None, result
    assert console.read_text().splitlines().count("TRI_ORACLE_PARALLEL_CHIP_PARTITION_MAPPED") == 1
    return result


def check_netlist(code, setup):
    spans = module_index(code)
    top, = (name for name in spans if name in (TOP, TOP + "_parallel_chip"))
    views = {}

    def view(master):
        if master not in views:
            _, ports, _, children, _ = parse_module(code, spans[master])
            views[master] = ports, children
        return views[master]

    def child_at(master, path):
        while path:
            names = {name.removeprefix("\\"): child for name, (child, _) in view(master)[1].items()}
            selected, = (name for name in names if path == name or path.startswith(name + "."))
            master = names[selected]
            path = path.removeprefix(selected).removeprefix(".")
        return master

    top_ports = view(top)[0]
    for name, (direction, bits) in AUX_PORTS.items():
        observed, span = top_ports[name]
        assert (observed, width(span)) == (direction, bits), name
    cuts = {}
    for name, cut in setup["preserved"].items():
        instance = child_at(top, name)
        ports, children = view(instance)
        signature = {port: [direction, list(span) if span is not None else None]
                     for port, (direction, span) in ports.items()}
        assert signature == cut["ports"], (name, instance)
        assert not children, (name, instance)
        cuts[name] = {"abstract_master": instance, "mapped_master": cut["mapped_master"]}
    return top, cuts


def run(synthesis, candidate, source_worker, interface_worker):
    prepared = synthesis / "prepared.json"
    setup = read(prepared)
    assert setup["state"] == "parallel_chip_synthesis_partition_prepared"
    preflight = synthesis / "preflight_receipt.json"
    simulated = read(preflight)
    assert simulated["state"] == "parallel_chip_preserved_synthesis_interfaces_verified"
    assert len(simulated["checked_cuts"]) == len(setup["preserved"]) == 11
    pins = simulated["input_sha256"]
    assert pins[str(prepared.relative_to(ROOT))] == sha256(prepared)
    pin(pins, preflight)
    verify(pins)
    training = candidate / "full_native/trained_receipt.json"
    attention = candidate / "full_native/attention_receipt.json"
    assert str(training) == setup["source_training_receipt_required"]
    native_elaboration = synthesis / "genus_elaboration_guarded"
    wait_for_receipt(training, source_worker, "replay_tri_oracle_parallel_chip.py",
                     "retry_tri_oracle_parallel_chip_trained.py")
    cycles = check_source(training, attention, candidate, pins)
    wait_for_receipt(native_elaboration / "native_status.json", interface_worker, "retry_genus_elaboration.py")
    check_elaboration(native_elaboration, setup, pins)
    pin(pins, Path(__file__).resolve())
    pin(pins, Path(module_index.__code__.co_filename).resolve())
    pin(pins, Path(terminate_process_group.__code__.co_filename).resolve())
    verify(pins)

    output = synthesis / "native_parent"
    output.mkdir()
    admission = output / "admission.json"
    admission.write_text(json.dumps({"trained_layer_cycles": cycles, "input_sha256": pins}, indent=2) + "\n")
    native = map_parent(synthesis / "map.tcl", output)
    netlist = output / "netlist.v"
    top, cuts = check_netlist(netlist.read_text(), setup)
    verify(pins)
    pin(pins, admission)
    result = {
        "state": "dual_lane_chip_parent_mapped_and_preserved_cut_signatures_verified",
        "native": native, "top": top, "preserved_cuts": cuts, "input_sha256": pins,
        "output_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in (
            netlist, output / "area.rpt", output / "timing.rpt", output / "constraints.sdc",
            output / "mapped_check.rpt", output / "console.log", output / "invocation.json",
        )},
    }
    (output / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print(result["state"], top, len(cuts), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("synthesis", type=lambda value: Path(value).resolve())
    parser.add_argument("candidate", type=lambda value: Path(value).resolve())
    parser.add_argument("source_worker", type=int)
    parser.add_argument("interface_worker", type=int)
    run(**vars(parser.parse_args()))
