"""Charge one ingress cycle per archived compact index response."""
import json
from pathlib import Path

from audit_tri_oracle_placed_fanout import sha
from verify_tri_oracle_gearbox_workload import chunks, read

RECORDS = Path("records")
GEARBOX = RECORDS / "tri_oracle_memory_response_gearbox.json"
WORKLOAD = Path(".cache/memory_response_gearbox/workload_serial.json")
TARGETS = RECORDS / "paper_result_targets.json"
RANKED = RECORDS / "tri_oracle_ranked_sign_workload_bounds.json"
WIDTH_BITS = 79
WORD_BITS = 64


def verify():
    assert Path("/.dockerenv").is_file() and __debug__
    base, workload, targets, signs = map(read,(GEARBOX,WORKLOAD,TARGETS,RANKED))
    assert base["evidence_sha256"][str(WORKLOAD)] == sha(WORKLOAD)
    assert all(sha(Path(path))==digest for path,digest in workload["evidence_sha256"].items())
    assert workload["state"]=="archived_weight_burst_padding_verified_for_memory_response_gearbox"
    index_bursts = workload["modeled_single_response_index_bursts"]
    assert index_bursts == workload["gate_up"]["payload_bursts"] == 20117504
    assert (WIDTH_BITS+WORD_BITS-1)//WORD_BITS==2
    assert chunks(1)==2
    fragments = workload["burst_aligned_aggregate_fragments"] - index_bursts
    cycles = (fragments+workload["one_request_cycle_per_burst"]+1)//2
    saved_cycles = workload["two_lane_ideal_balanced_service_cycles"]-cycles
    assert 2*saved_cycles == index_bursts
    budget, mhz = (targets["system_latency"][key] for key in ("milliseconds","clock_megahertz"))
    paper_cycles = budget*mhz*1000
    assert paper_cycles == signs["paper_latency_cycle_budget"]
    prior_serial_cycles = workload["conditional_serial_cycles_over_paper_budget"]+paper_cycles
    serial = prior_serial_cycles-saved_cycles
    # Even allowing sign lines to pack without padding, every line needs
    # eight words and the two lanes each accept seven words per cycle.
    sign_cycles = (chunks(signs["modeled_sign_line_reads"])+1)//2
    assert cycles < serial < paper_cycles < serial+sign_cycles
    paths = (GEARBOX,WORKLOAD,TARGETS,RANKED,Path(__file__))
    return dict(state="compact_index_archived_latency_scenarios_verified",
                records_requiring_compact_link=index_bursts,meaningful_index_bits=WIDTH_BITS,
                transmitted_words_per_compact_record=2,isolated_full_index_transfer_cycles=chunks(1),
                isolated_compact_index_transfer_cycles=1,two_lane_cycles_saved=saved_cycles,
                conditional_weight_service_ms=cycles/(mhz*1000),
                conditional_serial_weight_projection_ms=serial/(mhz*1000),
                conditional_serial_weight_projection_and_minimum_sign_ms=(serial+sign_cycles)/(mhz*1000),
                ideal_sign_data_cycles=sign_cycles,paper_system_target_ms=budget,
                scope="Conditional archived model with balanced lanes and no memory stalls. "
                      "Assumes every modeled index response uses the compact wire format. "
                      "The sign floor excludes requests, padding and attention and assumes serial service.",
                evidence_sha256={str(path):sha(path) for path in paths})


if __name__=="__main__":
    print(json.dumps(verify(),indent=2,sort_keys=True))
