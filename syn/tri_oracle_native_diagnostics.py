"""Reject native tool errors even when the command exits zero."""
import re

def require_clean_native(text):
    bad=re.findall(r"^(?:\*\*?ERROR:|FATAL[: (]|ERROR[: (]).*$",text,re.M|re.I)
    crashes=re.findall(r"^(?:Segmentation fault|Aborted|.*core dumped).*$",text,re.M|re.I)
    assert not bad and not crashes, 'Native diagnostics rejected: '+repr((bad+crashes)[:4])
