"""Measure the current cold-exported candidate against Figure 31.6.2's system boundary."""

from collections import Counter
from contextlib import ExitStack
from decimal import Decimal
import json
from pathlib import Path
import resource

from audit_tri_oracle_placed_chip_boundary import (
    PAD_ARCHIVE, check_ports, def_boundary, pad_limit, pad_views, verilog_ports,
)
from audit_tri_oracle_placed_fanout import GIB, memory, sha
from check_tri_oracle_paper300_gate import (
    BOUNDED_MAPPED_STRUCTURE, BOUNDED_STAGE, BOUNDED_TOKEN_MAP_PLACEMENT, PAPER_RELATIVE, PAPER_SHA256,
)
from link_tri_oracle_parallel_chip import catalog
from verify_tri_oracle_buffered_chip_boundary import TOP, hierarchy, inspect_connections
from verify_tri_oracle_buffered_topology import verify_compute_arrays


COLD = BOUNDED_STAGE / "native_token_map_buffer_candidate/cold"
ROOT = Path.cwd()
READ_INPUTS = ("rsp_data", "aux_rsp_data", "proj_rsp_data")
WRITE_OUTPUTS = ("wr_data",)


def read(path):
    return json.loads(path.read_text())


def cluster_modules(graph, reference):
    """Check each owner path after the placement change clones mapped module names."""
    measured = []
    for expected in reference:
        bank = expected["bank"]
        master, separator, remaining = expected["instance"].partition(".")
        assert master == TOP and separator
        while remaining:
            matches = []
            for label in graph[master]:
                normalized = label.removeprefix("\\")
                if remaining == normalized or remaining.startswith(normalized + "."):
                    matches.append((normalized, label))
            if not matches:
                raise ValueError(f"Missing compute cluster path {expected['instance']}: {remaining}")
            normalized, label = max(matches, key=lambda pair: len(pair[0]))
            master = graph[master][label]
            remaining = remaining[len(normalized):].removeprefix(".")
        group = graph[master]
        cores = {name: kind for name, kind in group.items() if name.startswith(r"\cores[")}
        assert cores.keys() == {rf"\cores[{index}]" for index in range(4)}
        merger = group[r"\local_merge.token_merge"]
        assert {"sizes", "similarity", "merge_controller"} <= graph[merger].keys()
        for core in cores.values():
            head = graph[core][r"\head.predict"]
            strip = graph[core][r"\strip.predict"]
            assert head.startswith("tri_oracle_core_head450_") and strip.startswith("tri_oracle_core_strip448_")
        measured.append(dict(bank=bank,placed_compute_cluster_master=master,placed_token_merge_master=merger,
                             cores=len(cores),local_head_predictors=len(cores),local_strip_predictors=len(cores)))
    assert len(measured) == 5 and len({row["placed_compute_cluster_master"] for row in measured}) == 5
    return measured


def verify():
    assert Path("/.dockerenv").is_file() and __debug__ and memory()[0] >= 8*GIB
    resource.setrlimit(resource.RLIMIT_AS, (4100*2**20,4100*2**20))
    evidence = {}

    def pin(path, checksum=None):
        identity = sha(path)
        assert checksum is None or checksum == identity, path
        evidence[str(path.relative_to(ROOT))] = identity
        return path

    targets_file = pin(ROOT/"records/paper_result_targets.json")
    targets = read(targets_file)
    assert targets["source"] == PAPER_RELATIVE and "31.6.2" in targets["source_figures"]
    paper = pin(ROOT/PAPER_RELATIVE, PAPER_SHA256)
    placement = read(pin(ROOT/BOUNDED_TOKEN_MAP_PLACEMENT))
    assert placement["state"] == "token_map_buffered_whole_chip_native_placement_verified"
    native_path = COLD.parent/"native_receipt.json"
    native = read(pin(ROOT/native_path, placement["evidence_sha256"][str(native_path)]))
    assert native["state"] == "token_map_native_import_cold_coordinates_and_connectivity_verified"
    assert native["cold_netlist_sha256"] == placement["cold_netlist_sha256"]
    netlist = pin(ROOT/COLD/"cold.v", native["cold_netlist_sha256"])
    layout_path = COLD/"layout.def"
    layout = pin(ROOT/layout_path, native["evidence_sha256"][str(layout_path)])
    reference = read(pin(ROOT/BOUNDED_MAPPED_STRUCTURE))
    assert reference["paper_sha256"] == PAPER_SHA256
    graph = hierarchy(netlist)
    assert TOP in graph
    measures = cluster_modules(graph, reference["clusters"])
    with ExitStack() as stack:
        endpoint_counts = inspect_connections(graph, catalog(stack, netlist), reference["clusters"])
    arrays = verify_compute_arrays(netlist, graph, targets)
    assert arrays == reference["compute"]

    cell_names, signal_masters, min_pad_width, corner_width, library_hash = pad_views(PAD_ARCHIVE)
    ports = verilog_ports(netlist)
    die, terminals, edges, pads = def_boundary(layout, cell_names)
    check_ports(ports, terminals)
    assert len(ports) == 106
    assert len(terminals) == sum(edges.values()) == placement["checked_ports"]
    assert list(die) == [Decimal(str(mm))*1000 for mm in targets["silicon"]["die_dimensions_mm"]]
    port_directions = Counter()
    for direction,width in ports.values():
        port_directions[direction.lower()] += width or 1
    assert port_directions.total() == len(terminals)
    assert ports["command_opcode"] == ("INPUT",3) and ports["payload_data"] == ("INPUT",64)

    for name in READ_INPUTS:
        assert ports[name][0] == "INPUT"
    for name in WRITE_OUTPUTS:
        assert ports[name][0] == "OUTPUT"
    data_widths = {name: ports[name][1] for name in (*READ_INPUTS,*WRITE_OUTPUTS)}
    assert data_widths == {"rsp_data":512,"aux_rsp_data":512,"proj_rsp_data":64,"wr_data":64}
    upper_with_corners = pad_limit(die,min_pad_width,corner_width)
    upper_without_corners = pad_limit(die,min_pad_width,Decimal(0))
    assert not pads and sum(data_widths.values()) > upper_without_corners >= upper_with_corners
    assert graph[TOP]["dispatch"] == "tri_oracle_indexed_chip_dispatch"
    assert graph[TOP]["grouped_reads"] == "tri_oracle_grouped_read_fabric_cells"
    for function in (verify, hierarchy, inspect_connections, verify_compute_arrays, check_ports,
                     verilog_ports, def_boundary, catalog, pad_views):
        pin(Path(function.__code__.co_filename).resolve())
    assert sha(netlist) == placement["cold_netlist_sha256"] and sha(paper) == PAPER_SHA256
    return dict(
        state="current_cold_chip_boundary_verified_with_system_gaps",
        paper_figure="31.6.2", source_netlist_sha256=placement["cold_netlist_sha256"],
        checked_clusters=measures, compute=arrays, external_clock_endpoints=endpoint_counts,
        external_dispatch_ports=13, external_memory_data_width_bits=data_widths,
        mapped_logical_ports=len(ports), placed_signal_terminals=len(terminals),
        placed_signal_terminals_by_direction=dict(port_directions),
        placed_signal_terminals_by_edge=edges, die_um=[str(side) for side in die],
        single_row_signal_pad_upper_bound=upper_with_corners,
        single_row_upper_bound_ignoring_corners=upper_without_corners,
        minimum_signal_pad_width_um=str(min_pad_width), minimum_corner_width_um=str(corner_width),
        available_signal_pad_masters=signal_masters, placed_library_pad_cells=sum(pads.values()),
        pad_archive=str(PAD_ARCHIVE), pad_archive_sha256=sha(PAD_ARCHIVE),
        extracted_pad_abstract_sha256=library_hash,
        evidence_sha256=evidence,
        scope="Exact cold-exported placed candidate. The external clock feeds the verified arrays. "
              "The mapped dispatcher exposes a host command interface and the grouped read fabric uses "
              "external data ports. Paper clock generation and full network and external memory integration "
              "remain unverified. The pad bound assumes one signal per pad and a single perimeter row and "
              "excludes power, ground, and required spacing.",
    )


if __name__ == "__main__":
    print(json.dumps(verify(),indent=2,sort_keys=True))
