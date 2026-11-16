"""Exhaustively check abstract storage credit conservation on the host GPU."""

import itertools
import json
from pathlib import Path

import torch


def check(stages):
    depth = 8
    device = "cuda"
    return_mask = (1 << stages) - 1
    capture, queued, head, pipe = torch.meshgrid(
        torch.arange(2, device=device), torch.arange(depth + 1, device=device),
        torch.arange(2, device=device), torch.arange(1 << stages, device=device),
        indexing="ij",
    )
    pulses = torch.tensor([value.bit_count() for value in range(1 << stages)], device=device)
    available = depth - capture - queued - pulses[pipe]
    legal = available >= 0
    capture, queued, head, pipe, available = (
        value[legal] for value in (capture, queued, head, pipe, available)
    )
    returned = pipe >> (stages - 1)
    # The head already returned its storage credit. It controls whether
    # another slot can dequeue but does not enter the conservation equation.
    for peer_wants, sink_takes in itertools.product((False, True), repeat=2):
        launched = ((available > 0) & peer_wants).long()
        enqueue = ((capture > 0) & (queued < depth)).long()
        dequeue = ((queued > 0) & ((head == 0) | sink_takes)).long()
        assert not ((launched > 0) & (capture > 0) & (enqueue == 0)).any().item()
        next_capture = capture + launched - enqueue
        next_queued = queued + enqueue - dequeue
        next_available = available + returned - launched
        next_pipe = ((pipe << 1) & return_mask) | dequeue
        assert ((next_capture >= 0) & (next_capture <= 1)).all().item()
        assert ((next_queued >= 0) & (next_queued <= depth)).all().item()
        assert ((next_available >= 0) & (next_available <= depth)).all().item()
        assert (next_capture + next_queued + next_available + pulses[next_pipe] == depth).all().item()
    return 4 * available.numel()


if __name__ == "__main__":
    assert __debug__ and not Path("/.dockerenv").exists()
    assert torch.cuda.is_available()
    torch.cuda.set_per_process_memory_fraction(0.08)
    torch.cuda.reset_peak_memory_stats()
    counts = {stages: check(stages) for stages in range(1, 9)}
    print(json.dumps({
        "scope": "Abstract storage credit invariant. Each return stage preserves pulses.",
        "device": torch.cuda.get_device_name(),
        "state_transitions_by_return_stages": counts,
        "verified_transitions": sum(counts.values()),
        "peak_device_bytes": torch.cuda.max_memory_allocated(),
    }, indent=2))
