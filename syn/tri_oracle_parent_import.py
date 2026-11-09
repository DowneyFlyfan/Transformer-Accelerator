"""Preserve mapped logic while declaring its original physical core interface."""
import re


def _module_pattern(name):
    return re.compile(r'^[ \t]*module[ \t]+' + re.escape(name) + r'(?=[ \t\r\n(#])', re.M)


def native_parent_netlist(mapped_text, canonical_interface_text):
    """Return mapped bytes unchanged, appending only a missing macro declaration.

    The canonical interface comes from the already native-imported core wrapper.
    This is a bounded tool-output transformation, not a general Verilog parser.
    Original core internals are supplied later through the complete timing model.
    """
    if not _module_pattern('tri_oracle_predicted_fabric').search(mapped_text):
        raise ValueError('Expected the mapped prediction/fabric parent')
    core = _module_pattern('tri_oracle_sram_memory_compute')
    if core.search(mapped_text):
        return mapped_text
    matches = list(core.finditer(canonical_interface_text))
    if len(matches) != 1:
        raise ValueError('Expected exactly one canonical core interface')
    start = matches[0].start()
    end = re.compile(r'^[ \t]*endmodule[ \t]*(?:\r?\n|$)', re.M).search(canonical_interface_text, start)
    if end is None:
        raise ValueError('Unterminated canonical core interface')
    declaration = canonical_interface_text[start:end.end()]
    if len(re.findall(r'^[ \t]*module\b', declaration, re.M)) != 1:
        raise ValueError('Canonical core interface contains another module')
    separator = '' if mapped_text.endswith('\n') else '\n'
    return mapped_text + separator + declaration
