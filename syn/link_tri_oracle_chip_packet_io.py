"""Bind the verified packet adapters to the exact cold whole-chip export."""

import argparse
import json
import mmap
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time

from audit_tri_oracle_physical_io_budget import INTERFACE
from audit_tri_oracle_placed_chip_boundary import TOP
from link_tri_oracle_indexed_whole_chip import module_at, pins, signature, spans
from link_tri_oracle_narrow_host import ADAPTER, HOST, PHYSICAL, declarations, width
from measure_tri_oracle_serial_memory_requests import digest, read


ROOT = Path(".cache/physical/whole_chip_xcelium_speed")
RECORDS = Path("records")
WRAPPER = "tri_oracle_chip_packet_io"
BENCH = "tri_oracle_chip_packet_io_tb"
MEMORY = "tri_oracle_memory_io_link"
HOST_NETLIST = Path(".cache/host_command_link/genus/netlist.v")
MEMORY_NETLIST = ROOT / "memory_io_link/genus/netlist.v"
MEMORY_FIELDS = ("req_valid", "req_ready", "req_address", "req_length",
                 "rsp_valid", "rsp_ready", "rsp_last", "rsp_error", "rsp_data")
WRITE_FIELDS = ("wr_req_valid", "wr_req_ready", "wr_address", "wr_length", "wr_data_valid",
                "wr_data_ready", "wr_data", "wr_strobe", "wr_data_last", "wr_rsp_valid", "wr_rsp_ready", "wr_rsp_error")
WIRE_FIELDS = ("tx_valid", "tx_ready", "tx_data", "mem_rsp_valid", "mem_rsp_ready",
               "mem_rsp_last", "mem_rsp_error", "mem_rsp_data")


def ports(body):
    result = {}
    for name, (direction, bits) in signature(body).items():
        count = int(re.fullmatch(rb"\[(\d+):0\]", bits)[1]) + 1 if bits else None
        result[name] = direction.decode().upper(), count
    return result


def instance(master, name, connections):
    return f"  {master} {name} (\n" + ",\n".join(
        f"    .{port}({net})" for port, net in connections.items()) + "\n  );\n"


def io_connections():
    result = {}
    for field in MEMORY_FIELDS:
        extension = "1'b0, " if field == "req_length" else ""
        result[field] = "{" + extension + ", ".join(prefix + field for prefix in ("proj_", "aux_", "")) + "}"
    return result | {"primary_wide": "req_wide"} | {name: name for name in WRITE_FIELDS}


def load():
    evidence = {}

    def pin(path, expected=None):
        if str(path) not in evidence:
            evidence[str(path)] = digest(path)
        checksum = evidence[str(path)]
        assert expected is None or checksum == expected, path
        return path

    placed = read(pin(RECORDS / "tri_oracle_repacked_whole_chip_cold_reload.json"))
    host = read(pin(RECORDS / "tri_oracle_cold_memory_boundary.json"))
    memory = read(pin(RECORDS / "tri_oracle_memory_io_link.json"))
    assert placed["cold_netlist_sha256"] == host["cold_netlist_sha256"] == memory["cold_netlist_sha256"]
    cold, = (Path(path) for path in placed["evidence_sha256"] if path.endswith("/cold.v"))
    pin(cold, placed["cold_netlist_sha256"])
    pin(HOST_NETLIST, host["evidence_sha256"][str(HOST_NETLIST)])
    pin(MEMORY_NETLIST, memory["evidence_sha256"][str(MEMORY_NETLIST)])
    prefix = ROOT / "prefix_bundle.sv"
    prepare = read(pin(ROOT / "prepared.json"))
    assert prepare["cold_netlist_sha256"] == placed["cold_netlist_sha256"]
    pin(prefix, prepare["evidence_sha256"][str(prefix)])
    include_paths = [Path(name) for name in re.findall(r'(?m)^`include "([^"]+)"$', prefix.read_text())]
    previous_native = read(pin(ROOT / "full_multicore/prepared.json"))
    assert previous_native["cold_netlist_sha256"] == placed["cold_netlist_sha256"]
    models = [path.relative_to(Path.cwd()) for path in include_paths if path.suffix == ".v" and path != cold.resolve()]
    assert len(models) == 7 and cold.resolve() in include_paths
    for model in models:
        pin(model, previous_native["evidence_sha256"][str(model)])
    pin(Path(__file__).resolve())

    with cold.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        index = spans(data)
        core = ports(module_at(data, index, TOP))
        chip_modules = set(index)
    adapter_ports = {}
    for name, path in ((ADAPTER, HOST_NETLIST), (MEMORY, MEMORY_NETLIST)):
        data = path.read_bytes()
        index = spans(data)
        assert not chip_modules.intersection(index)
        chip_modules.update(index)
        adapter_ports[name] = ports(module_at(data, index, name))
    clocks = {"clk": "clk", "rst_n": "rst_n"}
    memory_connections = io_connections()
    memory_physical = {port: f"memory_{port}" for port in WIRE_FIELDS}
    host_physical = {port: f"host_{port}" for port in PHYSICAL}
    host_connections = dict(zip(HOST, HOST, strict=True))
    adapter_connections = {ADAPTER: clocks | host_connections | host_physical,
                           MEMORY: clocks | memory_connections | memory_physical}
    assert all(set(ports_by_name) == set(adapter_connections[master])
               for master, ports_by_name in adapter_ports.items())

    internal = set()
    for master, connections in ((ADAPTER, host_connections), (MEMORY, memory_connections)):
        for port, expression in connections.items():
            direction, size = adapter_ports[master][port]
            bits = 0
            for term in expression.strip("{}").split(", "):
                if term == "1'b0":
                    assert direction == "INPUT" and port == "req_length"
                    bits += 1
                else:
                    chip_direction, chip_size = core[term]
                    assert chip_direction != direction and term not in internal
                    internal.add(term)
                    bits += chip_size or 1
            assert bits == (size or 1)

    retained = {name: spec for name, spec in core.items() if name not in internal}
    physical = {}
    for master, mapping in ((ADAPTER, host_physical), (MEMORY, memory_physical)):
        assert not set(mapping.values()) & (set(core) | set(physical))
        assert all(adapter_ports[master][name] == core[name] for name in clocks)
        physical.update({net: adapter_ports[master][port] for port, net in mapping.items()})
    outer = retained | physical
    assert width(core) == 7945 and width({name: core[name] for name in HOST}) == 142
    assert physical["memory_mem_rsp_data"] == ("INPUT", 1024)
    assert width({net: physical[net] for net in host_physical.values()}) == 39
    assert {term for elements in INTERFACE.values() for term in elements.split()} == set(core)
    remaining_groups = {role: width({name: retained[name] for name in members.split() if name in retained})
                        for role, members in INTERFACE.items()}
    remaining_groups = {role: bits for role, bits in remaining_groups.items() if bits and role != "clock_and_reset"}
    assert sum(remaining_groups.values()) + 2 == width(retained)
    return (cold, models, core, adapter_connections, outer, internal, remaining_groups, host, evidence)


def wrapper_text(core, adapter_connections, outer, internal):
    text = f"module {WRAPPER} (\n" + ",\n".join(declarations(outer)) + "\n);\n"
    text += "".join(declaration + ";\n" for declaration in declarations(
        {name: shape for name, shape in core.items() if name in internal}, wires=True))
    text += instance(TOP, "accelerator", dict(zip(core, core, strict=True)))
    text += instance(ADAPTER, "host_link", adapter_connections[ADAPTER])
    text += instance(MEMORY, "memory_link", adapter_connections[MEMORY])
    assert pins(text.encode(), TOP, "accelerator") == {name: name.encode() for name in core}
    for master, name in ((ADAPTER, "host_link"), (MEMORY, "memory_link")):
        assert pins(text.encode(), master, name) == {
            port: value.replace(" ", "").encode() for port, value in adapter_connections[master].items()
        }
    return text + "endmodule\n"


def bench_text(outer):
    stimulus = Path("verilog/tri_oracle_chip_packet_io_tb.svh").read_text()
    bench_nets = {"clk", "rst_n", *(name for name in outer if name.startswith("host_")), "memory_tx_valid"}
    connections = {name: name if name in bench_nets else ("'0" if direction == "INPUT" else "")
                   for name, (direction, _) in outer.items()}
    return stimulus.replace("  // CHIP_INSTANCE", instance(WRAPPER, "dut", connections).rstrip(), 1)


def run(phase, output):
    cold, models, core, adapters, outer, internal, remaining_groups, host, evidence = load()
    wrapper = output / "wrapper.v"
    bench = output / "wrapper_tb.sv"
    bundle = output / "wrapper_bundle.sv"
    files = (*models, cold, HOST_NETLIST, MEMORY_NETLIST, wrapper, bench)
    contents = {
        wrapper: wrapper_text(core, adapters, outer, internal),
        bench: bench_text(outer),
        bundle: "`define UNIT_DELAY\n" + "".join(f'`include "{path.resolve()}"\n' for path in files),
    }
    if phase == "prepare":
        for path, text in contents.items():
            with path.open("x") as stream:
                stream.write(text)
        print(f"Linked {width(core)} original signal bits into {width(outer)} digital boundary bits "
              f"with {sum(remaining_groups.values())} unpacketized bits.")
        return
    for path, text in contents.items():
        assert path.read_text() == text
        evidence[str(path)] = digest(path)
    native = output / "native"
    log = (native / "xrun.log").read_text()
    aname = native / "xrun.history"
    last_command = re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", aname.read_text())[-1]
    argv = shlex.split(last_command)
    assert argv[argv.index("-top") + 1] == BENCH and str(bundle.resolve()) in argv
    assert not re.search(r"\*[EF],", log)
    status = read(output / "native_status.json")
    assert status["native_exit_status"] == 0 and status["stop_reason"] is None
    assert status["log_sha256"] == digest(native / "xrun.log")
    assert re.findall(r"(?m)^COLD_PACKET_IO_PASS (.+)$", log) == ["dispatcher_rejects=1 layer_rejects=1 response_flits=6"]
    assert log.count("Simulation complete via $finish(1)") == 1
    for path in (native / "xrun.log", aname, output / "native_status.json", Path("verilog/tri_oracle_chip_packet_io_tb.svh")):
        evidence[str(path)] = digest(path)
    ports_at_two_edge_receive = width(outer) - 512
    assert ports_at_two_edge_receive - host["clear_pad_sites"] == sum(remaining_groups.values())
    print(json.dumps({
        "state": "whole_cold_chip_packet_wrappers_linked_and_native_host_smoke_verified",
        "cold_netlist_sha256": evidence[str(cold)],
        "original_signal_bits": width(core),
        "new_digital_boundary_signal_bits": width(outer),
        "remaining_unpacketized_signal_bits_by_role": remaining_groups,
        "remaining_unpacketized_signal_bits": sum(remaining_groups.values()),
        "modeled_pad_sites_with_two_edge_receive": ports_at_two_edge_receive,
        "clear_sites_in_current_floorplan": host["clear_pad_sites"],
        "host_smoke": {"dispatcher_rejections": 1, "actual_feedforward_rejections": 1, "response_flits": 6},
        "native_resources": status,
        "scope": "Whole cold hierarchy elaborated with exact mapped host and memory adapters. The host rejection "
                 "smoke exercises the actual chip dispatcher and feed-forward control. Active memory workloads "
                 "and physical timing remain open. The pad estimate assumes two data bits per receive pad per "
                 "cycle before packaging and power.",
        "evidence_sha256": evidence,
    }, indent=2, sort_keys=True))


def native(output, fixture=None, dump=None):
    from audit_tri_oracle_placed_fanout import memory
    from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
    from tri_oracle_process_guard import terminate_process_group

    assert Path("/.dockerenv").is_file()
    gib = 1 << 30
    available, anonymous = memory()
    assert available >= 13 * gib and anonymous < 8 * gib, (available, anonymous)
    assert shutil.disk_usage(output).free >= 28 * gib
    folder = output / "native"
    folder.mkdir()
    log = (folder / "xrun.log").resolve()
    command = ["/usr/bin/prlimit", f"--as={10 * gib}", "--", "/opt/cadence/bin/xrun",
               "-64bit", "-sv", "-timescale", "1ns/1ps", "-nospecify", "-notimingchecks",
               "-sequdp_nba_delay", "-xmerror", "CUVMPW", "-xmerror", "RECOME",
               "-top", BENCH, str((output / "wrapper_bundle.sv").resolve()), "-log", str(log)]
    if fixture is not None:
        command.extend((f"+FIXTURE={fixture.resolve()}", f"+DUMP={dump.resolve()}"))
    control = MemoryPressurePolicy(host_reserve_bytes=8 * gib, resume_bytes=9 * gib,
                                   anonymous_limit_bytes=15 * gib, maximum_pause_seconds=180)
    started = time.monotonic()
    minimum, peak = available, anonymous
    stop = None
    with (folder / "console.log").open("x") as stream:
        worker = subprocess.Popen(command, cwd=folder, stdout=stream, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, start_new_session=True)
        owned = OwnedProcessPause(worker, str(log))
        print(f"Packet I/O native worker {worker.pid} started.", flush=True)
        try:
            while worker.poll() is None:
                available, anonymous = memory()
                minimum, peak = min(minimum, available), max(peak, anonymous)
                now = time.monotonic()
                if now - started > 20 * 60:
                    raise TimeoutError("Native packet I/O smoke exceeded 20 minutes")
                action = control.observe(available, anonymous, now)
                if action == "pause":
                    print("Packet I/O worker paused for memory", owned.pause(), flush=True)
                elif action == "resume":
                    print("Packet I/O worker resumed", owned.resume(), flush=True)
                time.sleep(0.5)
        except (MemoryError, TimeoutError) as error:
            stop = str(error)
            print(stop, flush=True)
        finally:
            owned.resume()
            terminate_process_group(worker, log_argument=str(log))
    with (output / "native_status.json").open("x") as stream:
        json.dump({
            "native_exit_status": worker.returncode,
            "elapsed_seconds": time.monotonic() - started,
            "minimum_host_available_bytes": minimum,
            "peak_container_anonymous_bytes": peak,
            "stop_reason": stop,
            "log_sha256": digest(log) if log.is_file() else None,
        }, stream, indent=2, sort_keys=True)
    raise SystemExit(0 if stop is None and worker.returncode == 0 else 1)


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "native", "verify"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--dump", type=Path)
    args = parser.parse_args()
    assert (args.fixture is None) == (args.dump is None)
    if args.phase == "native":
        native(args.directory, args.fixture, args.dump)
    run(args.phase, args.directory)
