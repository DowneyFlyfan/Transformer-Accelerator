"""Fail-closed semantic checks for this flow's Innovus25.10 block reports.

This validates report contents only. Separate checks must establish run/input
freshness, database and exported-artifact integrity, functional equivalence,
process qualification and all paper-level results. No foundry signoff claim.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys


class ReportError(ValueError):
    """Required physical evidence is absent, ambiguous, or violates a gate."""


def _load(directory, name, top, hashes, design_header=True):
    path = directory/name
    if not path.is_file() or not 0 < path.stat().st_size <= 2*1024*1024:
        raise ReportError(f'{name}: missing, empty, or unexpectedly large report')
    raw = path.read_bytes()
    if path.suffix == '.gz':
        with gzip.open(path, 'rt', encoding='utf-8') as source:
            text = source.read(2*1024*1024+1)
        if len(text) > 2*1024*1024:
            raise ReportError(f'{name}: unexpectedly large decompressed report')
    else:
        text = raw.decode('utf-8')
    hashes[name] = hashlib.sha256(raw).hexdigest()
    if design_header:
        designs = re.findall(r'^\s*#\s*Design:\s*(\S+)\s*$', text, re.M)
        if designs != [top]:
            raise ReportError(f'{name}: expected exactly one design header for {top}')
    if re.search(r'\*\*(?:ERROR|WARN)|\b(?:ERROR|WARNING)\b', text):
        raise ReportError(f'{name}: diagnostic requires inspection')
    return text


def _timing(text, name, view, check):
    paths = list(re.finditer(r'^Path\s+(\d+):\s+(MET|VIOLATED)\s+\(([+-]?\d+(?:\.\d+)?) ns\)\s+(Setup Check|Hold Check|Late Output Delay Assertion)', text, re.M))
    all_headers = re.findall(r'^\s*Path\s+\d+:',text,re.M)
    if len(all_headers)!=len(paths):
        raise ReportError(f'{name}: incomplete or unrecognized timing path')
    views = re.findall(r'^\s*View:\s*(\S+)\s*$', text, re.M)
    if not paths or paths[0].group(1)!='1' or len(views)!=len(paths) or any(value!=view for value in views):
        raise ReportError(f'{name}: missing timing paths or wrong analysis view')
    if 'No constrained timing paths' in text:
        raise ReportError(f'{name}: contradictory unconstrained-path message')
    for index,path in enumerate(paths):
        if path.group(2)!='MET' or path.group(3).startswith('-') or {'Setup Check':'Setup','Hold Check':'Hold','Late Output Delay Assertion':'Setup'}[path.group(4)]!=check:
            raise ReportError(f'{name}: timing violation, ambiguous rounded slack, or wrong check type')
        end = paths[index+1].start() if index+1<len(paths) else len(text)
        section = text[path.start():end]
        if path.group(4)=='Late Output Delay Assertion':
            output_delays=re.findall(r'^\s*Output Delay:-\s*([+-]?\d+(?:\.\d+)?)\s*$',section,re.M)
            if len(output_delays)!=1:
                raise ReportError(f'{name}: missing or ambiguous output-delay assertion body')
        summary = re.findall(r'^\s*Slack:=\s*([+-]?\d+(?:\.\d+)?)\s*$',section,re.M)
        lines = [line.strip() for line in section.splitlines() if line.strip()]
        if not re.search(r'^\s*Startpoint:\s*.+',section,re.M) or not re.search(r'^\s*Endpoint:\s*.+',section,re.M):
            raise ReportError(f'{name}: missing timing path endpoints')
        if len(summary)!=1 or summary[0].startswith('-') or float(summary[0])!=float(path.group(3)) or not lines[-1].startswith('#---'):
            raise ReportError(f'{name}: incomplete timing body or inconsistent slack')
        separators = list(re.finditer(r'^#-+\s*$',section,re.M))
        if len(separators)<3:
            raise ReportError(f'{name}: missing timing rows or closing separator')
        rows = [line.strip() for line in section[separators[-2].end():separators[-1].start()].splitlines() if line.strip() and not line.lstrip().startswith('#')]
        startpoint = re.search(r'^\s*Startpoint:\s+\([RF]\)\s+(\S+)\s*$',section,re.M)
        endpoint = re.search(r'^\s*Endpoint:\s+\([RF]\)\s+(\S+)\s*$',section,re.M)
        if not rows or not startpoint or not endpoint or rows[0].split()[0]!=startpoint.group(1) or rows[-1].split()[0]!=endpoint.group(1):
            raise ReportError(f'{name}: timing table lacks matching start/end rows')
    return min(float(path.group(3)) for path in paths)


def _body(text):
    return '\n'.join(line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#'))


def _electrical(directory, top, hashes):
    scope = _load(directory, 'electrical_reporting_scope.rpt', top, hashes, False)
    expected_scope = ('base_report_timing_max_transition_use_si_transition: false\n'
                      'noisy_report_timing_max_transition_use_si_transition: true')
    if scope.strip() != expected_scope:
        raise ReportError('electrical_reporting_scope.rpt: explicit base/noisy modes required')
    for prefix in ['electrical_violators', 'electrical_base']:
        for suffix, view in [('slow', 'setup_slow'), ('typ', 'setup_typ')]:
            name = f'{prefix}_{suffix}.rpt'
            text = _load(directory, name, top, hashes)
            commands = re.findall(r'^#\s*Command:\s*(.+)$', text, re.M)
            if len(commands) != 1 or not re.search(
                    r'\breport_constraint\b.*-all_violators\b.*-view\s+' + view + r'(?:\s|$)',
                    commands[0]):
                raise ReportError(f'{name}: missing all-violator command or wrong analysis view')
            body = '\n'.join(line for line in _body(text).splitlines()
                             if not re.fullmatch(r'-+', line))
            expected = ('Check type : max_capacitance\nNo Violations found\n'
                        'Check type : max_transition\nNo Violations found')
            if body != expected:
                raise ReportError(f'{name}: electrical violation or incomplete report')
    for suffix, check in [('tran', 'max_tran'), ('cap', 'max_cap')]:
        name = f'qualification_si_reports/qualification_si.{suffix}.gz'
        text = _load(directory, name, top, hashes)
        commands = re.findall(r'^#\s*Command:\s*(.+)$', text, re.M)
        if len(commands) != 1 or not all(
                token in commands[0].split() for token in
                ['time_design', '-post_route', '-drv_report', '-expanded_views']):
            raise ReportError(f'{name}: missing expanded-view post-route command')
        if _body(text) != f'*info: there is 0 {check} violation in the design.':
            raise ReportError(f'{name}: electrical violation or incomplete noisy report')


def validate_reports(directory, top, require_electrical=False):
    directory = Path(directory)
    if not re.fullmatch(r'tri_oracle_[a-z_]+', top):
        raise ReportError('Invalid expected design name')
    hashes = {}
    timing = {}
    for name,view,check in [('export_setup_slow.rpt','setup_slow','Setup'),('export_setup_typ.rpt','setup_typ','Setup'),('export_hold_fast.rpt','hold_fast','Hold')]:
        timing[view] = _timing(_load(directory,name,top,hashes),name,view,check)
    for name,positive in [('route_drc.rpt','No DRC violations were found'),('antenna.rpt','No Ant violations were found')]:
        if _body(_load(directory,name,top,hashes)) != positive:
            raise ReportError(f'{name}: expected unambiguous zero-violation report')
    text = _load(directory,'route_connectivity.rpt',top,hashes)
    summaries = re.findall(r'Begin Summary\s*(.*?)\s*End Summary',text,re.S)
    if summaries != ['Found no problems or warnings.']:
        raise ReportError('route_connectivity.rpt: incomplete or nonzero connectivity summary')
    text = _load(directory,'final_placement.rpt',top,hashes,False)
    placed = re.findall(r'\bPlaced\s*=\s*(\d+)',text)
    unplaced = re.findall(r'\bUnplaced\s*=\s*(\d+)',text)
    if len(placed)!=1 or int(placed[0])==0 or unplaced!=['0'] or 'Finished check_place' not in text:
        raise ReportError('final_placement.rpt: incomplete placement or unplaced cells')
    if re.search(r'\b(?:violations?|overlap(?:s|ped|ping)?|illegal|errors?)\b',text,re.I):
        raise ReportError('final_placement.rpt: placement diagnostic requires review')
    density = re.search(r'Placement Density:\s*(\d+(?:\.\d+)?)%',text)
    if not density or not 0<float(density.group(1))<=100:
        raise ReportError('final_placement.rpt: missing or invalid density')
    text = _load(directory,'extraction_audit.rpt',top,hashes,False)
    keys = ['Routed nets','Zero-connection signal nets without routing','Single-connection signal nets without routing','Power/ground nets excluded from signal extraction','Signal nets with multiple connections but no wire shapes']
    counts = {}
    for key in keys:
        matches = re.findall(r'^'+re.escape(key)+r': (\d+)\s*$',text,re.M)
        if len(matches)!=1:
            raise ReportError(f'extraction_audit.rpt: missing or ambiguous {key}')
        counts[key] = int(matches[0])
    if len(text.splitlines())!=len(keys) or counts[keys[0]]==0 or counts[keys[-1]]!=0:
        raise ReportError('extraction_audit.rpt: incomplete audit or active nets missing routes')
    electrical_checked = require_electrical or any(
        (directory / name).exists() for name in
        ['electrical_violators_slow.rpt', 'electrical_violators_typ.rpt', 'qualification_si_reports'])
    if electrical_checked:
        _electrical(directory, top, hashes)
    return {
        'electrical_report_values_checked': electrical_checked,
        'electrical_report_values_pass': True if electrical_checked else None,
        'top':top,'report_values_pass':True,'timing_slack_ns':timing,
        'placed_cells':int(placed[0]),'unplaced_cells':0,'placement_density_percent':float(density.group(1)),
        'routed_signal_nets':counts[keys[0]],'zero_connection_signal_aliases':counts[keys[1]],
        'single_connection_signal_nets':counts[keys[2]],'active_signal_nets_missing_routes':0,
        'report_sha256':hashes,
        'scope':'Report contents only; run/input freshness, exported artifacts, functionality and foundry signoff require separate checks',
        'full_paper_results_matched':False,
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--top',required=True)
    parser.add_argument('--require-electrical', action='store_true')
    arguments=parser.parse_args()
    try:
        result=validate_reports(arguments.directory,arguments.top,arguments.require_electrical)
    except (ReportError,OSError,UnicodeError) as error:
        print('TRI_ORACLE_PHYSICAL_REPORTS_REQUIRE_REVIEW: '+str(error),file=sys.stderr)
        return 1
    print(json.dumps(result,indent=2))
    return 0


if __name__=='__main__':
    sys.exit(main())
