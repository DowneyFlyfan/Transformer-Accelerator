"""Compare verified buffer tree geometry before and after pad reservation."""
import argparse
from collections import Counter
import csv
from hashlib import file_digest
import json
from pathlib import Path
import re

from audit_tri_oracle_pad_ring_clearance import POSE

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".cache/placement_coordinate_reuse"


def digest(file):
    with file.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()

def cell(pin):
    return pin.rsplit('/', 1)[0]

def tree(path, root, names, rows, leaves):
    with path.open() as stream:
        recipe = list(csv.DictReader(stream, delimiter='\t'))
    assert [int(row['id']) for row in recipe] == list(range(rows))
    incoming = Counter()
    branches = {}
    terminal_pins = set()
    for row in recipe:
        index = int(row['id'])
        children = list(map(int, row['children'].split()))
        pins = row['pins'].split()
        assert bool(children) != bool(pins)
        assert all(child < index for child in children)
        incoming.update(children)
        assert len(pins) == len(set(pins)) and terminal_pins.isdisjoint(pins)
        terminal_pins.update(pins)
        branches[names[index]] = [names[child] for child in children] or list(map(cell, pins))
    assert incoming == Counter(range(rows-1))
    assert len(terminal_pins) == leaves
    assert root not in branches
    branches[root] = [names[rows-1]]
    return branches

def read_trees():
    root, base = ROOT, WORK
    reset_plan = json.loads((root / "records/tri_oracle_grouped_reset_plan.json").read_bytes())
    active_graph = json.loads((root / "records/tri_oracle_grouped_active_graph.json").read_bytes())
    active_path = base/'grouped_reset_pin_loads_checked/grouped_active_tree_verified.tsv'
    ledger = base/'grouped_active_eco/cold_exact/drivers.tsv'
    for path in (active_path, ledger):
        assert digest(path) == active_graph['evidence_sha256'][str(path.relative_to(root))]
    names = {}
    for row in ledger.read_text().splitlines():
        driver, _ = row.split('\t')
        if match := re.search(r'TRI_GROUPED_ACTIVE_(\d+)/Z$', driver):
            name = int(match[1])
            assert name not in names
            names[name] = cell(driver)
    assert len(names) == 712
    trees = {'grouped_active': tree(active_path, 'batch/g166179', names, 712, 17013)}
    for group in range(5):
        owner = f'grouped_{group}'
        path = base/f'grouped_reset_plan/{owner}.tsv'
        assert digest(path) == reset_plan['evidence_sha256'][str(path.relative_to(root))]
        count = reset_plan['groups'][str(group)]['buffers']
        names = {i: f'{owner}/TRI_GROUPED_RESET_{group}_{i}' for i in range(count)}
        trees[f'grouped_reset_{group}'] = tree(path, f'{owner}/g83737', names, count, 18484)
    return trees

def locations(path, expected, needed):
    assert digest(path) == expected
    placed = {}
    with path.open() as stream:
        for line in stream:
            if line == 'COMPONENTS 3765868 ;\n':
                break
        for line in stream:
            if line == 'END COMPONENTS\n':
                break
            if not line.startswith('- '):
                continue
            name = line.split(maxsplit=2)[1].replace('\\', '')
            if name not in needed:
                continue
            match = POSE.match(line)
            assert match and name not in placed, name
            placed[name] = tuple(map(int, match.group(4,5)))
    assert placed.keys() == needed, needed - placed.keys()
    return placed

def spans(tree, loc):
    result = {}
    for driver, loads in tree.items():
        x, y = zip(*(loc[name] for name in (driver, *loads)))
        result[driver] = (max(x)-min(x) + max(y)-min(y))/2000
    return result

def measure(original, candidate, receipt):
    assert __debug__ and Path("/.dockerenv").is_file()
    seed = json.loads(receipt.read_bytes())
    placement = json.loads((ROOT / "records/tri_oracle_grouped_active_placement.json").read_bytes())
    assert seed["input_def_sha256"] == placement["placed_design_exchange_sha256"]
    assert seed["input_candidate_sha256"] == placement["candidate_netlist_sha256"]
    trees = read_trees()
    needed = {name for branches in trees.values() for driver, loads in branches.items()
              for name in (driver, *loads)}
    before = locations(original, seed["input_def_sha256"], needed)
    after = locations(candidate, seed["seed_def_sha256"], needed)
    report = {}
    for name, branches in trees.items():
        old, trial = spans(branches, before), spans(branches, after)
        report[name] = dict(
            net_count=len(old), before_sum_um=round(sum(old.values()),3),
            trial_sum_um=round(sum(trial.values()),3), growth_ratio=round(sum(trial.values())/sum(old.values()),4),
            before_longest_um=max(old.values()), trial_longest_um=max(trial.values()),
            nets_with_greater_span=sum(trial[net]>old[net] for net in old),
            drivers_moved=sum(before[driver]!=after[driver] for driver in branches),
        )

    return dict(
        state="partial_pad_seed_buffer_tree_span_measured",
        candidate_netlist_sha256=seed["input_candidate_sha256"],
        input_def_sha256=seed["input_def_sha256"], seed_def_sha256=seed["seed_def_sha256"],
        trees=report,
        scope="Bounding-box spans use component origins. Actual wiring and timing require separate measurements.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original", "candidate", "receipt"):
        parser.add_argument(name, type=Path)
    print(json.dumps(measure(**vars(parser.parse_args())), indent=2, sort_keys=True))
