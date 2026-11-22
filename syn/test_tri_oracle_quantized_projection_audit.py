"""Reject incomplete, corrupted or prematurely released real native outputs."""
from pathlib import Path
from contextlib import redirect_stdout
import io
import json
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

import audit_tri_oracle_quantized_projection as audit


class QuantizedProjectionAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.log = (audit.WORK / 'native_integration_v3/xrun.log').read_text()
        cls.lines = cls.log.splitlines()
        cls.words = [i for i, line in enumerate(cls.lines) if line.startswith('SHARED_QUANTIZED_WORD ')]
        assert len(cls.words) == 256, 'Tests require a completed real native run'

    def reject(self, lines):
        with self.assertRaises(AssertionError):
            audit.check_quantized('\n'.join(lines))

    def test_accepts_every_real_word(self):
        self.assertEqual(audit.check_quantized(self.log)['exact_quantized_projection_codes'], 2048)

    def test_raw_projection_does_not_qualify_quantized_output(self):
        raw = audit.WORK.parent / 'shared_attention_projection_v1/native_positive_v2/xrun.log'
        with self.assertRaises(AssertionError):
            audit.check_quantized(raw.read_text())

    def test_rejects_missing_word(self):
        lines = self.lines.copy(); del lines[self.words[5]]
        self.reject(lines)

    def test_rejects_duplicate_word(self):
        lines = self.lines.copy(); lines.insert(self.words[5], lines[self.words[5]])
        self.reject(lines)

    def test_rejects_reordered_words(self):
        lines = self.lines.copy(); a, b = self.words[4:6]; lines[a], lines[b] = lines[b], lines[a]
        self.reject(lines)

    def test_rejects_wrong_code(self):
        lines = self.lines.copy(); i = self.words[0]
        data = int(audit.raw_audit.fields(lines[i])['data'], 16) ^ 1
        lines[i] = re.sub(r'data=[0-9a-f]+', f'data={data:016x}', lines[i])
        self.reject(lines)

    def test_rejects_wrong_channel(self):
        lines = self.lines.copy(); i = self.words[0]
        channels = int(audit.raw_audit.fields(lines[i])['channels'], 16) ^ 1
        lines[i] = re.sub(r'channels=[0-9a-f]+', f'channels={channels:032x}', lines[i])
        self.reject(lines)

    def test_rejects_wrong_tag(self):
        lines = self.lines.copy(); i = self.words[0]
        lines[i] = lines[i].replace('tag=80000000', 'tag=80000001')
        self.reject(lines)

    def test_rejects_wrong_packet_last(self):
        lines = self.lines.copy(); i = self.words[0]
        lines[i] = lines[i].replace('packet_last=0', 'packet_last=1')
        self.reject(lines)

    def test_rejects_wrong_context_unit(self):
        lines = [line.replace('context=-7', 'context=-6') if line.startswith('SHARED_PROJECTION_UNITS ') else line
                 for line in self.lines]
        self.reject(lines)

    def test_rejects_release_before_last_word(self):
        lines = self.lines.copy(); lines.remove('COMMIT_FINISH_ACCEPTED')
        lines.insert(self.words[0], 'COMMIT_FINISH_ACCEPTED')
        self.reject(lines)

    def test_rejects_packet_words_after_its_completion(self):
        moved = [self.lines[i] for i in self.words[:20]]
        lines = [line for i, line in enumerate(self.lines) if i not in self.words[:20]]
        after = lines.index('SHARED_PROJECTION_GROUP_PASS group=0 values=160') + 1
        lines[after:after] = moved
        self.reject(lines)

    def test_rejects_packet_words_before_its_raw_dots(self):
        moved = [self.lines[i] for i in self.words[:20]]
        lines = [line for i, line in enumerate(self.lines) if i not in self.words[:20]]
        before = next(i for i, line in enumerate(lines) if line.startswith('SHARED_PROJECTION_DOT channel=0 '))
        lines[before:before] = moved
        self.reject(lines)

    def test_rejects_unit_log_bound_to_another_top(self):
        path = audit.WORK / 'green_v1/invocation.json'
        invocation = json.loads(path.read_text())
        argv = invocation['argv']
        argv[argv.index('-top') + 1] = 'different_top_with_no_converter'
        original_read = Path.read_text
        def changed_read(target, *args, **kwargs):
            if target == path:
                return json.dumps(invocation)
            return original_read(target, *args, **kwargs)
        with patch.object(Path, 'read_text', changed_read), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'Native command differs'):
                audit.qualify()

    def test_rejects_missing_completion(self):
        self.reject([line for line in self.lines if not line.startswith('SHARED_QUANTIZED_PROJECTION_PASS ')])

    def test_optimized_python_cannot_bypass_verification(self):
        result = subprocess.run([sys.executable, '-O', str(Path(audit.__file__))], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Verification requires Python assertions', result.stderr)


if __name__ == '__main__':
    unittest.main()
