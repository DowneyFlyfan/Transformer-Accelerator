"""Verify the disclosed compute and predictor placement on the buffered chip."""

from collections import Counter
from hashlib import file_digest
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import ENDMODULE, MODULE, PE_ARRAY, TOP, audit, hierarchy
from audit_tri_oracle_shared_prediction_roles import measure


ROOT = Path(__file__).resolve().parents[1]
NETLIST = ROOT / ".cache/placement_coordinate_reuse/grouped_active_eco/apply/active.v"
PAPER_SHA256 = "6d6b998c459ade605e082d723374462e1d14b53d6a6b13063ca0f8d1180b1d9f"
REGISTERS = re.compile(rb"(?m)^[ \t]*(\w+)\s+\\(product\[\d+\]\.value_reg\[\d+\]"
                       rb"|reduction\[\d+\]\.row\[\d+\]\.sum\[0\]\.value_reg\[\d+\])\s*\(([^;]+)\);")
PRODUCT = re.compile(rb"product\[(\d+)\]\.value_reg\[(\d+)\]")
REDUCTION = re.compile(rb"reduction\[(\d+)\]\.row\[(\d+)\]\.sum\[0\]\.value_reg\[(\d+)\]")


def digest(path):
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def reachable_arrays(graph, module):
    if module.startswith(PE_ARRAY):
        return Counter({module: 1})
    counts = Counter()
    for child in graph[module].values():
        counts.update(reachable_arrays(graph, child))
    return counts


def verify_array(body, rows, lanes, width):
    products = rows * lanes
    tree_level = lanes.bit_length() - 1
    product_width = 2 * width
    sum_width = product_width + tree_level
    assert lanes == 2**tree_level
    for direction, name, msb in ((b"input", b"operand_a", products * width - 1),
                                 (b"input", b"operand_b", products * width - 1),
                                 (b"input", b"lane_enable", products - 1),
                                 (b"output", b"out_sums", rows * sum_width - 1)):
        declaration = rb"(?m)^[ \t]*" + direction + rb"\s+\[(\d+):0\]\s+" + name + rb"\s*;"
        assert re.findall(declaration, body) == [str(msb).encode()], name

    product_bits, sum_bits = set(), set()
    for master, name, connections in REGISTERS.findall(body):
        product = PRODUCT.fullmatch(name)
        if product:
            lane, bit = map(int, product.groups())
            assert (lane, bit) not in product_bits, name
            product_bits.add((lane, bit))
            driver = rb"\\product\[%d\]\.value\s*\[%d\]" % (lane, bit)
        else:
            level, row, bit = map(int, REDUCTION.fullmatch(name).groups())
            if level != tree_level - 1:
                continue
            assert (row, bit) not in sum_bits, name
            sum_bits.add((row, bit))
            driver = rb"out_sums\[%d\]" % (row * sum_width + bit)
        assert master.startswith(b"DF") and re.search(rb"\.CP\(\s*clk\s*\)", connections), name
        assert re.search(rb"\.Q\(\s*" + driver + rb"\s*\)", connections), name
    assert product_bits == {(lane, bit) for lane in range(products) for bit in range(product_width)}
    assert sum_bits == {(row, bit) for row in range(rows) for bit in range(sum_width)}
    return {"registered_product_bits": len(product_bits), "registered_final_sum_bits": len(sum_bits)}


def verify():
    assert __debug__ and Path("/.dockerenv").is_file()
    evidence = {}

    def record(name):
        path = ROOT / "records" / name
        evidence[name] = digest(path)
        return json.loads(path.read_bytes())

    targets = record("paper_result_targets.json")
    assert digest(ROOT / targets["source"]) == PAPER_SHA256
    previous = record("tri_oracle_shared_prediction_roles.json")
    redundancy = record("tri_oracle_mapped_redundancy_and_timing_limit.json")
    reset_graph = record("tri_oracle_grouped_reset_graph.json")
    active_graph = record("tri_oracle_grouped_active_graph.json")
    assert previous["placed_sha256"] == redundancy["placed_netlist_sha256"] == reset_graph["original_netlist_sha256"]
    assert reset_graph["buffered_netlist_sha256"] == active_graph["parent_netlist_sha256"]
    identity = digest(NETLIST)
    assert identity == active_graph["candidate_netlist_sha256"]

    graph = hierarchy(NETLIST)
    topology = audit(graph)
    assert topology["clusters"] == redundancy["clusters"]
    roles = measure(NETLIST)
    assert all(previous[name] == result for name, result in roles.items())
    silicon = targets["silicon"]
    clusters, cores = silicon["clusters"], silicon["cores_per_cluster"]
    rows, lanes = silicon["processing_element_array_per_core"]
    assert silicon["processing_element_precision"] == "signed INT8"
    arrays = reachable_arrays(graph, TOP)
    assert arrays.total() == clusters * cores
    checked = {}
    with NETLIST.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        for module in MODULE.finditer(source):
            name = module[1].decode()
            if name in arrays:
                end = ENDMODULE.search(source, module.end()).start()
                checked[name] = verify_array(source[module.end():end], rows, lanes, 8)
    assert checked.keys() == arrays.keys() and digest(NETLIST) == identity
    for name in (Path(__file__).name, "audit_tri_oracle_mapped_redundancy.py",
                 "audit_tri_oracle_shared_prediction_roles.py"):
        evidence[f"syn/{name}"] = digest(ROOT / "syn" / name)
    peak = clusters * cores * rows * lanes * 2 * targets["peak"]["clock_megahertz"] * 10**6
    assert round(peak / 10**12, 2) == targets["peak"]["trillion_operations_per_second"]
    return dict(
        state="buffered_compute_array_and_local_prediction_topology_verified",
        candidate_netlist_sha256=identity, paper_sha256=PAPER_SHA256,
        paper_figures=["31.6.2", "31.6.4", "31.6.5", "31.6.7"],
        clusters=clusters, cores_per_cluster=cores, array_rows=rows, array_lanes=lanes,
        local_token_mergers=sum(item["local_token_mergers"] for item in topology["clusters"]),
        local_head_predictors=sum(item["local_head_predictors"] for item in topology["clusters"]),
        local_strip_predictors=sum(item["local_strip_predictors"] for item in topology["clusters"]),
        array_instances=arrays.total(), unique_array_masters=len(checked),
        operand_bits=8, registered_product_bits_per_array=rows * lanes * 16,
        registered_final_sum_bits_per_array=rows * (16 + lanes.bit_length() - 1),
        nominal_operations_per_second_at_paper_clock=peak, prediction_roles=roles,
        evidence_sha256=evidence,
        scope="Structural checks on the grouped-active placed netlist. Peak operations use the paper's "
              "assumed clock. Whole-chip timing, prediction effectiveness, external interface and "
              "end-to-end model accuracy require separate measurements.",
    )


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
