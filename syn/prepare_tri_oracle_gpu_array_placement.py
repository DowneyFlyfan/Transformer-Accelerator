"""Use the host graphics processor to rank area-neutral placement swaps."""

from collections import defaultdict
import json
from pathlib import Path
import re

import numpy as np
from scipy.spatial import cKDTree
import torch

from link_tri_oracle_indexed_whole_chip import spans
from verify_tri_oracle_array_control_buffers import (
    INSTANCE,
    TERMINAL,
    TOP,
    WORK as BASE,
    lookup_sources,
)
from verify_tri_oracle_gated_array_placement import (
    LEF,
    ROOT,
    components,
    dimensions,
    digest,
    gates_script,
    row_grid,
    section,
)

WORK = BASE.with_name("gpu_swaps")


def memory_available():
    return (
        int(
            next(
                line.split()[1]
                for line in Path("/proc/meminfo").read_text().splitlines()
                if line.startswith("MemAvailable:")
            )
        )
        * 1024
    )


def connections(names, master, placed):
    known = {name: i for i, name in enumerate(names)}
    directions = {}
    text = LEF.read_text()
    for macro, body in re.findall(r"(?ms)^MACRO (\S+)\s+?(.*?)^END \1\s*$", text):
        for pin, definition in re.findall(
            r"(?ms)^ +PIN (\S+) *\n(.*?)^ +END \1 *$", body
        ):
            direction = re.search(r"(?m)^ +DIRECTION (\w+)(?: +\w+)* *;", definition)
            assert direction, (macro, pin)
            directions.setdefault(macro, {})[pin] = direction[1]
    _, pin_text = section(placed, "PINS")
    positions = []
    nets = defaultdict(list)
    ports = re.findall(
        r"(?ms)^- (\S+) \+ NET (\S+) \+ DIRECTION (INPUT|OUTPUT) .*?"
        r"\+ PLACED \( (\d+) (\d+) \) \w+ ;",
        pin_text,
    )
    assert len(ports) == 4966
    for port, net, direction, x, y in ports:
        known[port] = len(names) + len(positions)
        nets[net].append((known[port], direction == "INPUT"))
        positions.append((int(x), int(y)))
    source = (BASE / "netlist.v").read_text()
    first, last = spans(source.encode())[TOP]
    instance_count = 0
    for item in INSTANCE.finditer(source[first:last]):
        name = item[1].removeprefix("\\")
        terminals = TERMINAL.findall(item[2])
        if name not in known:
            assert re.fullmatch(r"RC_CG_HIER_INST[0-7]", name)
            name += "/RC_CGIC_INST"
            pin_map = {"enable": "E", "ck_in": "CP", "ck_out": "Q", "test": "TE"}
            terminals = [(pin_map[port], net) for port, net in terminals]
        i = known[name]
        instance_count += 1
        for terminal, net in terminals:
            nets[net].append((i, directions[master[i]][terminal] == "OUTPUT"))
    assert instance_count == len(names)
    edges = defaultdict(float)
    for terms in nets.values():
        if not 2 <= len(terms) <= 64:
            continue
        drivers = [i for i, drive in terms if drive]
        if len(drivers) != 1:
            continue
        driver = drivers[0]
        for i, drive in terms:
            if not drive and i != driver:
                edge = tuple(sorted((i, driver)))
                edges[edge] += (2.0 if edge[1] >= len(names) else 1.0) / (
                    len(terms) - 1
                ) ** 0.4
    critical = {}
    for mode in ("setup", "gate_setup"):
        previous = None
        for line in (BASE / f"native_{mode}.rpt").read_text().splitlines():
            if line.startswith("Path "):
                previous = None
            items = line.split()
            if len(items) != 9 or items[3] not in ("R", "F"):
                continue
            point = items[0].rsplit("/", 1)[0]
            current = known.get(point)
            if (
                current is None
                or point in ("clk", "rst_n")
                or ("RC_CGIC_INST" in point and mode == "setup")
            ):
                previous = None
                continue
            if previous is not None and current != previous:
                edge = tuple(sorted((previous, current)))
                if edge in edges:
                    critical[edge] = max(
                        critical.get(edge, 0), 2 + min(10, 5 * float(items[-2]))
                    )
            previous = current
    assert len(critical) > 30 and len(edges) > 50000, (len(critical), len(edges))
    for edge, weight in critical.items():
        edges[edge] += weight
    return edges, critical, positions


def assignment(widths, slots, ports, edges, critical):
    n = len(slots)
    graph = [dict() for _ in slots]
    for (a, b), weight in edges.items():
        if a < n:
            graph[a][b] = weight
        if b < n:
            graph[b][a] = weight
    degree = max(map(len, graph))
    assert degree < 160, degree
    adjacency = np.zeros((n, degree), dtype=np.int32)
    weights = np.zeros((n, degree), dtype=np.float32)
    for i, row in enumerate(graph):
        adjacency[i, : len(row)] = list(row)
        weights[i, : len(row)] = list(row.values())

    def cuda(array):
        return torch.as_tensor(array, device="cuda")

    nbr = cuda(adjacency).long()
    w = cuda(weights)
    fixed = cuda(ports).float() / 2000
    original = cuda(slots).float() / 2000
    xy = torch.cat((original, fixed))
    total = 0
    groups = [np.flatnonzero(widths == width) for width in np.unique(widths)]
    here = np.arange(n)
    holder = here.copy()
    slot_um = slots.astype(np.float64) / 2000
    trees = [(group, cKDTree(slot_um[group])) for group in groups if len(group) > 1]

    def objective():
        # Internal edges appear twice. Edges to fixed pins appear once.
        coeff = torch.where(nbr < n, 0.5, 1.0)
        cost = ((xy[nbr] - xy[:n, None]).abs().sum(-1) * w * coeff).sum().item()
        drift = (xy[:n] - original).abs().sum().item()
        return cost + 0.10 * drift

    start = previous = objective()
    for epoch in range(20):
        assert memory_available() >= 7 * 2**30
        centers = (
            ((xy[nbr] * w[:, :, None]).sum(1) / w.sum(1, keepdim=True).clamp_min(0.01))
            .cpu()
            .numpy()
        )
        options = []
        for group, tree in trees:
            count = min(12, len(group))
            nearby = tree.query(centers[group], k=count, workers=4)[1]
            neighbors = tree.query(
                slot_um[here[group]], k=min(5, len(group)), workers=4
            )[1]
            candidate = holder[group[np.concatenate((nearby, neighbors), axis=1)]]
            a = np.broadcast_to(group[:, None], candidate.shape)
            options.append(
                (
                    np.minimum(a, candidate).reshape(-1),
                    np.maximum(a, candidate).reshape(-1),
                )
            )
        a, b = (np.concatenate(part) for part in zip(*options))
        unique = np.unique(a[a != b].astype(np.int64) * n + b[a != b])
        aa, bb = unique // n, unique % n
        gain = []
        for offset in range(0, len(aa), 16384):
            a, b = cuda(aa[offset : offset + 16384]), cuda(bb[offset : offset + 16384])

            def benefit(i, j):
                other = xy[nbr[i]]
                old = (other - xy[i, None]).abs().sum(-1)
                new = (other - xy[j, None]).abs().sum(-1)
                return ((old - new) * w[i] * (nbr[i] != j[:, None])).sum(1)

            drift = (xy[a] - original[a]).abs().sum(1) + (
                xy[b] - original[b]
            ).abs().sum(1)
            swapped = (xy[a] - original[b]).abs().sum(1) + (
                xy[b] - original[a]
            ).abs().sum(1)
            gain.append(
                (benefit(a, b) + benefit(b, a) + 0.10 * (drift - swapped)).cpu().numpy()
            )
        gain = np.concatenate(gain)
        good = np.flatnonzero(gain > 0.08)
        ordered = good[np.argsort(-gain[good], kind="stable")]
        forbidden = set()
        accepted = []
        for index in ordered:
            a, b = int(aa[index]), int(bb[index])
            if a not in forbidden and b not in forbidden:
                accepted.append((a, b))
                forbidden.update((a, b))
                forbidden.update(graph[a])
                forbidden.update(graph[b])
        if not accepted:
            break
        a, b = np.asarray(accepted).T
        s, t = here[a].copy(), here[b].copy()
        here[a], here[b] = t, s
        holder[s], holder[t] = b, a
        xy = torch.cat((original[cuda(here)], fixed))
        scoring = objective()
        assert scoring < previous
        previous = scoring
        total += len(accepted)
        print("SWAPS", epoch + 1, len(accepted), round(previous, 1), flush=True)
    assert (
        total
        and np.array_equal(np.sort(here), np.arange(n))
        and np.array_equal(widths, widths[here])
    )
    return here, dict(
        graph_score_before=start,
        graph_score_after=previous,
        swaps=total,
        moved_cells=int((here != np.arange(n)).sum()),
        edges=len(edges),
        measured_critical_edges=len(critical),
        peak_gpu_bytes=torch.cuda.max_memory_allocated(),
    )


def main():
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    WORK.mkdir(exist_ok=True)
    assert memory_available() >= 9 * 2**30
    assert torch.cuda.mem_get_info()[0] >= 5 * 2**30
    torch.cuda.set_per_process_memory_fraction(0.15)
    torch.set_num_threads(4)
    lookup_sources()
    pose = dict(components(BASE / "placed.def"))
    names = {
        name.decode().replace("\\", ""): value for name, value in sorted(pose.items())
    }
    assert len(names) == len(pose) == 53797
    sizes = dimensions([LEF], 2000)
    masters = [entry[0] for entry in names.values()]
    widths = np.array([sizes[m][0] for m in masters])
    slots = np.array([location[2:4] for location in names.values()], dtype=np.int32)
    assert len(set(map(tuple, slots))) == len(names)
    seed = (BASE / "seed.def").read_text()
    edges, critical, ports = connections(names, masters, seed)
    index, summary = assignment(widths, slots, ports, edges, critical)
    faces = {y: side for _, y, side, _, _ in row_grid(seed)[0]}
    coords = dict(zip(names, slots[index], strict=True))
    first, last = seed.split("COMPONENTS ", 1)
    _, last = last.split("END COMPONENTS\n", 1)
    target = WORK / "seed.def"
    with target.open("w") as stream:
        stream.write(first + f"COMPONENTS {len(names)} ;\n")
        for name in pose:
            raw = name.decode()
            plain = raw.replace("\\", "")
            x, y = coords[plain]
            stream.write(
                f"- {raw} {names[plain][0]} + PLACED ( {x} {y} ) {faces[y]} ;\n"
            )
        stream.write("END COMPONENTS\n" + last)
    (WORK / "place.tcl").write_text(
        gates_script().replace("$count != 53622", "$count != 53797")
    )
    for name in ("netlist.v", "emitted.sdc"):
        if not (WORK / name).is_symlink():
            (WORK / name).symlink_to((BASE / name).resolve(strict=True))
    summary.update(
        seed_sha256=digest(target), input_seed_sha256=digest(BASE / "seed.def")
    )
    (WORK / "assignment.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
