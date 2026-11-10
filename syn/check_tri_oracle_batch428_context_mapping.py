"""Check the four-macro Genus result and replay it using the vendor models."""

import json
from pathlib import Path
import re
import subprocess
import tempfile

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_attention_context428"
MACRO = "ts5n28hpcpsvta512x64m4f_130a"
STDCELL = "tcbn28hpcplusbwp12t40p140"
MARKER = "CTX428_PASS saved=12707 restored=12672 writes=1985 reads=1980 stalls=1320"


def main():
    check_memory(10*GIB)
    physical = ROOT/".cache/physical"
    output = physical/"synthesis/attention_context428"
    macro_dir = physical/"sram/activation_cache_banks_01"/MACRO
    cell_model = physical/"library"/f"{STDCELL}.v"
    macro_model = macro_dir/"VERILOG"/f"{MACRO}_tt1v25c.v"
    netlist = output/"netlist.v"
    bench = ROOT/"verilog"/f"{TOP}_tb.sv"
    report_path = ROOT/"records/batch428_context_synthesis_result.json"
    assert not report_path.exists()
    console = output/"console.log"
    assert console.read_text().splitlines().count("CTX428_GENUS_DONE")==1
    check = output/"mapped_check.rpt"
    assert f"No unresolved references in design '{TOP}'" in check.read_text()
    assert len(re.findall(r"^\s*TS5N28HPCPSVTA512X64M4F\s+\S+\s*\(",netlist.read_text(),re.M))==4
    area = output/"area.rpt"
    area_line = re.search(rf"^{TOP}\s+NA\s+(\d+)\s+([\d.]+)",area.read_text(),re.M)
    assert area_line, area.read_text()
    timing = output/"timing.rpt"
    setup_line = re.search(r"^Path 1: (MET|VIOLATED) \((-?[\d.]+) ps\) Setup",timing.read_text(),re.M)
    assert setup_line, timing.read_text()[:2000]
    slack_ps = float(setup_line[2])
    assert (slack_ps>=0)==(setup_line[1]=="MET")
    inputs = [Path(__file__),ROOT/"syn/tri_oracle_synthesize_attention_context428.tcl",
              ROOT/"verilog"/f"{TOP}.sv",bench,netlist,console,check,area,timing,cell_model,macro_model,
              physical/"library"/f"{STDCELL}ssg0p9v125c.lib",
              macro_dir/"NLDM"/f"{MACRO}_ssg0p9v125c.lib"]
    digests = {str(path):sha256(path) for path in inputs}

    with tempfile.TemporaryDirectory(dir=ROOT/".cache",prefix="batch428_mapped_") as folder:
        work = Path(folder)
        log_path = work/"console.log"
        command = ["/opt/cadence/bin/xrun","-64bit","-sv","-timescale","1ns/1ps","-define","UNIT_DELAY","-xmerror","RECOME",
                   "-notimingchecks","-top",f"{TOP}_tb",str(netlist),str(bench),str(cell_model),str(macro_model)]
        with log_path.open("x") as stream:
            worker = subprocess.Popen(command,cwd=work,stdout=stream,stderr=subprocess.STDOUT,
                                      stdin=subprocess.DEVNULL,start_new_session=True)
            try:
                status = worker.wait(timeout=120)
            finally:
                terminate_process_group(worker)
        log = log_path.read_text()
        assert status==0 and log.splitlines().count(MARKER)==1 and not re.search(r"\*(?:E|F),",log), log[-5000:]
    assert all(sha256(Path(path))==digest for path,digest in digests.items())
    mapped_log = output/"mapped_xrun.log"
    with mapped_log.open("x") as stream:
        stream.write(log)
    report = dict(state="isolated_context_mapped_and_functionally_verified",technology="TSMC 28 nm HPC+",
                  slow_corner="0.9 V, 125 C",target_clock_megahertz=580,
                  estimated_preplacement_setup_slack_ps=slack_ps,netlist_cells=int(area_line[1]),
                  library_cell_area_square_micrometers=float(area_line[2]),compiled_context_macros=4,
                  mapped_simulation_marker=MARKER,delay_annotation=False,paper_results_matched=False,
                  inputs_sha256=digests,simulation_log_sha256=sha256(mapped_log),simulation_log_tail=log.splitlines()[-16:])
    with report_path.open("x") as stream:
        stream.write(json.dumps(report,indent=2)+"\n")
    print("CTX428_MAPPED_VERIFIED",f"area={area_line[2]}um2 setup_slack={slack_ps}ps")


if __name__=="__main__":
    main()
