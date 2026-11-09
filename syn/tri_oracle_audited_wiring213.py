"""Classify exact zero-cone wrapper declarations without suppressing live defects."""
from collections import Counter
import json
from pathlib import Path
import re
import sys


TOP='tri_oracle_predicted_feedforward_frame'


def require_audited_wiring(report, expected):
    required={f"No undriven {kind} in '{TOP}'" for kind in ['combinational pin','sequential pin','port']}
    required.update(f"No multidriven {kind} in '{TOP}'" for kind in
                    ['combinational pin','sequential pin','hierarchical pin','ports','unloaded nets'])
    required.update(['Check Design Report (c)','Undriven Port(s)/Pin(s)','Multidriven Port(s)/Pin(s)',
                     f"The following hierarchical pin(s) in design '{TOP}' are undriven",'Done Checking the design.'])
    seen=Counter();pins=[];totals=[]
    for raw in report.splitlines():
        line=raw.strip()
        if not line or set(line)=={'-'}:continue
        if line in required:seen[line]+=1;continue
        match=re.fullmatch(r'hpin:'+re.escape(TOP)+r'/([^\s]+)\s+\(fanout\s*:\s*(\d+)\)',line)
        if match:
            if match[2]!='0':raise ValueError('An undriven hierarchy input has fanout')
            pins.append(match[1]);continue
        match=re.fullmatch("Total number of hierarchical undriven pins in design '"+re.escape(TOP)+r"'\s*:\s*(\d+)",line)
        if match:totals.append(int(match[1]));continue
        raise ValueError('Additional or unknown native wiring diagnostic: '+line)
    if set(seen)!=required or any(n!=1 for n in seen.values()):raise ValueError('Missing or repeated native wiring obligations')
    if len(pins)!=len(set(pins)) or set(pins)!=set(expected) or totals!=[len(pins)]:
        raise ValueError('Native undriven pin identities/count differ from independent cone audit')
    return dict(state='native_wiring_valid_with_exact_audited_dead_inputs',
        native_undriven_status=1,audited_dead_wrapper_inputs=len(pins),
        undriven_leaf_and_top_ports=0,multiple_drivers=0,
        scope='Only exact previously audited no-net/no-load hierarchy inputs admitted. Native raw undriven status remains nonzero; no loaded electrical defect is waived.')


def main():
    report,targets,output=map(Path,sys.argv[1:])
    names=targets.read_text().splitlines()
    assert len(names)==len(set(names))==32106
    result=require_audited_wiring(report.read_text(),set(names))
    assert not output.exists();output.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
