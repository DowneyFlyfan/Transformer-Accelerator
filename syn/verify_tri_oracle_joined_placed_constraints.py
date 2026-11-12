"""Compare Genus and cold Innovus constraints for the joined chip."""

from collections import Counter
from decimal import Decimal
import re


PORT = re.compile(r"\[\s*get_ports\s+(?:\{([^}]+)\}|([^\s]+?))\s*\]$")
CLOCK = re.compile(r"\[\s*get_clocks\s+(?:\{core_clock\}|core_clock)\s*\]")
WAVEFORM = re.compile(r"-waveform\s+\{(\S+)\s+(\S+)\}")
PORT_CONSTRAINTS = {"set_input_delay", "set_output_delay", "set_input_transition", "set_load"}
UNITS = {"time": {"1ns", "1000ps"}, "capacitance": {"1pf", "1000ff"}}


def port_selector(line):
    """Return the command without its one port selector and the selected port."""
    match = re.match(r"create_clock \[get_ports (?:\{clk\}|clk)\] ", line)
    if match:
        return f"create_clock {line[match.end():]}", "clk"
    match = PORT.search(line)
    assert match, line
    name = (match[1] or match[2]).replace("\\", "")
    while name.startswith("{") and name.endswith("}"):
        name = name[1:-1].strip()
    assert re.fullmatch(r"[A-Za-z_]\w*(?:\[\d+\])*", name), name
    return line[:match.start()].strip(), name


def delay_constraint(command, line):
    tail = line.removeprefix(command).strip()
    if command in {"set_input_delay", "set_output_delay"}:
        assert len(CLOCK.findall(tail)) == 1
        tail = CLOCK.sub("core_clock", tail)
        assert tail.split().count("-clock") == 1 and "-clock core_clock" in " ".join(tail.split())
        tail = tail.replace("-clock core_clock", "")
    allowed = {"set_input_delay": {"-add_delay"}, "set_output_delay": {"-add_delay"},
               "set_input_transition": set(), "set_load": {"-pin_load"}}[command]
    tokens = tail.split()
    flags = [token for token in tokens if token.startswith("-") and not re.fullmatch(r"-\d+(?:\.\d+)?", token)]
    assert len(flags) == len(set(flags)) and set(flags) <= allowed | {"-min", "-max"}, line
    if command == "set_load":
        assert "-pin_load" in flags, line
    edges = tuple(flag[1:] for flag in flags if flag in {"-min", "-max"}) or ("min", "max")
    number, = (token for token in tokens if token not in flags)
    return edges, Decimal(number)


def parse_sdc(text):
    entries, ports, units = {}, {}, {}
    metadata, protected, gating_checks = set(), set(), set()
    for raw in re.sub(r"\\\r?\n", " ", text).splitlines():
        line = " ".join(raw.split())
        if not line or line.startswith("#"):
            continue
        command, _, tail = line.partition(" ")
        if command in {"set", "set_wire_load_mode"}:
            expected = "sdc_version 2.0" if command == "set" else "segmented"
            assert command not in metadata and tail.strip('"') == expected, line
            metadata.add(command)
        elif command == "set_clock_gating_check":
            match = re.fullmatch(r"(?:-(rise|fall) )?-(setup|hold) (\S+)", tail)
            assert match and Decimal(match[3]) == 0, line
            edges = (match[1],) if match[1] else ("rise", "fall")
            checks = {(edge, match[2]) for edge in edges}
            assert gating_checks.isdisjoint(checks), line
            gating_checks.update(checks)
        elif command == "set_dont_touch":
            match = re.fullmatch(r"\[get_cells (?:\{([^}]+)\}|(\S+))\]", tail)
            assert match and (name := match[1] or match[2]) not in protected, line
            protected.add(name)
        elif command == "set_units":
            words = tail.split()
            assert len(words) % 2 == 0
            for name, unit in zip(words[::2], words[1::2], strict=True):
                key = name.removeprefix("-")
                assert key not in units and unit.lower() in UNITS[key], line
                units[key] = min(UNITS[key])
        elif command == "current_design":
            assert command not in entries and re.fullmatch(r"[A-Za-z_]\w*", tail), line
            entries[command] = tail
        elif command == "create_clock":
            arguments, pin = port_selector(line)
            wave, = WAVEFORM.findall(arguments)
            params = WAVEFORM.sub("", arguments).split()
            assert len(params) == 5 and params[1::2] == ["-name", "-period"]
            assert params[2].strip('"') == "core_clock" and pin == "clk" and command not in entries
            entries[command] = (pin, Decimal(params[4]), tuple(map(Decimal, wave)))
        elif command == "set_clock_uncertainty":
            match = re.fullmatch(r"(?:-(setup|hold) )?(\d+(?:\.\d+)?) core_clock", CLOCK.sub("core_clock", tail))
            assert match, line
            for check in (match[1],) if match[1] else ("setup", "hold"):
                assert (command, check) not in entries, line
                entries[command, check] = Decimal(match[2])
        elif command == "set_false_path":
            arguments, pin = port_selector(line)
            assert arguments == "set_false_path -from" and pin == "rst_n" and command not in entries
            entries[command] = pin
        else:
            assert command in PORT_CONSTRAINTS, line
            arguments, pin = port_selector(line)
            edges, number = delay_constraint(command, arguments)
            for edge in edges:
                key = command, pin, edge
                assert key not in ports, key
                ports[key] = number
    assert units.keys() == UNITS.keys()
    return entries, ports, protected


def verify_constraints(expected, exported, *, top):
    source, actual = parse_sdc(expected), parse_sdc(exported)
    assert source[0]["current_design"] == top
    assert source[0]["create_clock"] == ("clk", Decimal("1.72414"), (Decimal(0), Decimal("0.86207")))
    assert source[0]["set_clock_uncertainty", "setup"] == source[0]["set_clock_uncertainty", "hold"] == Decimal("0.05")
    assert source[0]["set_false_path"] == "rst_n"
    assert source[0] == actual[0], (source[0], actual[0])
    assert not actual[2] or source[2] == actual[2]
    difference = source[1].items() ^ actual[1].items()
    assert not difference, sorted(difference)[:8]
    counts = Counter(name for name, _, _ in actual[1])
    assert counts == {name: 2 * count for name, count in {
        "set_input_delay": 4732, "set_input_transition": 4732, "set_load": 7631, "set_output_delay": 7631,
    }.items()}
    return {name: count // 2 for name, count in sorted(counts.items())}
