"""Check equivalence of live queue entries and the output head across one clock."""
import itertools
import json
from pathlib import Path

import torch


assert not Path("/.dockerenv").exists() and torch.cuda.is_available()
torch.cuda.set_per_process_memory_fraction(0.08)
device = "cuda"
depth = 8
pointers = torch.arange(2 * depth, device=device)
head_states = torch.arange(2, device=device)
read, count, head_valid = (field.reshape(-1) for field in torch.meshgrid(
    pointers, torch.arange(depth + 1, device=device), head_states, indexing="ij"))
write = (read + count) % (2 * depth)
slots = torch.arange(depth, device=device)[None]
offsets = (slots - read[:, None]) % depth
live_before = offsets < count[:, None]
# Distinct tokens stand for all possible old storage bits, old head and new input.
queued = 1 + offsets
old_head = torch.full_like(read, 50)
incoming = torch.full_like(read, 100)
checked = 0
for input_valid, sink_ready in itertools.product((False, True), repeat=2):
    reload = (head_valid == 0) | sink_ready
    empty = count == 0
    full = count == depth
    pop = reload & ~empty
    bypass = reload & empty & input_valid
    enqueue = ~full & input_valid & ~bypass
    write_slot = slots == (write[:, None] % depth)
    assert not bool((~full[:, None] & live_before & write_slot).any())
    ordinary = torch.where((enqueue[:, None] & write_slot), incoming[:, None], queued)
    proposed = torch.where((~full[:, None] & write_slot), incoming[:, None], queued)
    next_offset = (slots - read[:, None] - pop[:, None].long()) % depth
    next_count = count + enqueue.long() - pop.long()
    assert bool(((next_count >= 0) & (next_count <= depth)).all())
    live_after = next_offset < next_count[:, None]
    assert not bool((live_after & (ordinary != proposed)).any())
    queued_head = queued.gather(1, (read % depth)[:, None]).squeeze(1)
    expected = torch.where(bypass, incoming, torch.where(pop, queued_head, old_head))
    # The split's direct register updates on reload and the select records emptiness.
    direct = torch.where(reload, incoming, old_head)
    from_input = reload & empty
    actual = torch.where(from_input, direct, torch.where(pop, queued_head, old_head))
    next_head_valid = torch.where(reload, pop | bypass, head_valid.bool())
    assert not bool((next_head_valid & (expected != actual)).any())
    checked += int(read.numel())
print(json.dumps({
    "device": torch.cuda.get_device_name(),
    "queue_and_head_transitions": checked,
    "scope": "All pointer, occupancy, input-valid and sink-ready combinations for a synchronous depth-eight queue. "
    "Check live storage and registered output against the single-head bypass.",
}, indent=2))
