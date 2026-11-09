"""CUDA integer oracle covering every address of the19KB memory/compute core."""
from pathlib import Path
import hashlib
import json
import random

import torch


def main():
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:'))) * 1024
    assert available > 8*1024**3 and torch.cuda.is_available()
    torch.set_num_threads(2)
    torch.set_num_interop_threads(2)
    torch.cuda.set_per_process_memory_fraction(.125)
    assert torch.cuda.mem_get_info()[0] > 4*1024**3
    rng = random.Random(0x283265)
    # Seeded hardware-memory contents: [weight address32, row32, signed lane8].
    weight_values = [[[rng.randrange(-128, 128) for _ in range(8)]
                      for _ in range(32)] for _ in range(32)]
    # Seeded activations: [input address1024, signed lane8].
    input_values = [[rng.randrange(-128, 128) for _ in range(8)] for _ in range(1024)]
    # Seeded masks: [mask address32, row32, enabled lane8].
    mask_values = [[[rng.randrange(2) for _ in range(8)]
                    for _ in range(32)] for _ in range(32)]
    weight_values[3][0] = [-128]*8
    input_values[0] = [-128]*8
    mask_values[7][0] = [1]*8
    weight_values[30][31] = [127]*8
    input_values[1023] = [127]*8
    mask_values[26][31] = [1]*8

    # GPU copies of the seeded memories; int32 multiplication preserves signed INT8 values.
    weights = torch.tensor(weight_values, dtype=torch.int32, device='cuda')  # [32,32,8]
    inputs = torch.tensor(input_values, dtype=torch.int32, device='cuda')  # [1024,8]
    masks = torch.tensor(mask_values, dtype=torch.int32, device='cuda')  # [32,32,8]
    commands = torch.arange(1024, dtype=torch.int64, device='cuda')  # [command1024]
    weight_indices = (commands*5+3) % 32  # [command1024], every weight address
    mask_indices = (commands*13+7) % 32  # [command1024], every mask address
    slots = commands % 16  # [command1024], destination slot
    slots[-32:] = 3  # Force a consecutive same-slot accumulation chain.
    selected_weights = weights[weight_indices]  # [command1024,row32,lane8]
    selected_masks = masks[mask_indices]  # [command1024,row32,lane8]
    products = selected_weights*inputs[:, None, :]*selected_masks  # [1024,32,8]
    dots = products.sum(dim=2, dtype=torch.int32)  # [command1024,row32]
    expected = torch.zeros((16, 32), dtype=torch.int32, device='cuda')  # [slot16,row32]
    expected.index_add_(0, slots, dots)
    torch.cuda.synchronize()
    assert int(dots[0, 0]) == 131072 and int(dots[-1, 31]) == 129032
    # Independent Python-integer arithmetic checks the entire GPU oracle.
    scalar = [[0]*32 for _ in range(16)]  # [slot16,row32], zero initialization
    for command in range(1024):
        weight = (command*5+3) % 32
        mask = (command*13+7) % 32
        slot = command % 16 if command < 992 else 3
        for row in range(32):
            value = sum(weight_values[weight][row][lane]*input_values[command][lane]
                        for lane in range(8) if mask_values[mask][row][lane])
            scalar[slot][row] = ((scalar[slot][row]+value+2**31) % 2**32)-2**31
    assert expected.cpu().tolist() == scalar
    directory = Path('.cache/model_reference/sram_capacity_gpu')
    directory.mkdir(exist_ok=False)

    def pack(values, bits):
        return sum((value & ((1 << bits)-1)) << (bits*index)
                   for index, value in enumerate(values))

    (directory/'weights.hex').write_text(''.join(
        f'{pack([v for row in word for v in row], 8):0512x}\n' for word in weight_values))
    (directory/'inputs.hex').write_text(''.join(
        f'{pack(word, 8):016x}\n' for word in input_values))
    (directory/'masks.hex').write_text(''.join(
        f'{pack([v for row in word for v in row], 1):064x}\n' for word in mask_values))
    (directory/'expected.hex').write_text(''.join(
        f'{pack(word, 32):0256x}\n' for word in expected.cpu().tolist()))
    record = {'gpu_oracle_matches_independent_scalar': True, 'commands': 1024,
              'input_addresses': 1024, 'weight_addresses': 32, 'mask_addresses': 32,
              'result_words': 16, 'result_rows_each': 32,
              'device': torch.cuda.get_device_name(0), 'torch': torch.__version__,
              'peak_gpu_allocated_bytes': torch.cuda.max_memory_allocated(),
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'vector_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in directory.glob('*.hex')},
              'scope': 'GPU/CPU integer reference vectors only; native hardware comparison remains required.'}
    (directory/'manifest.json').write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
