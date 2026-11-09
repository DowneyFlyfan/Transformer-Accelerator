"""Reuse the existing system-level benches with explicit compiled-memory backends."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import test_tri_oracle_fabric_projection as fabric_tests
import test_tri_oracle_memory_feedforward as feedforward_tests
from test_tri_oracle_sram_memory_compute import models


class BackendSelection:
    def setUp(self):
        self.corner = os.environ.get('TRI_ORACLE_TEST_CORNER', 'tt1v25c')
        self.directory = tempfile.TemporaryDirectory(prefix='sram_backend_', dir='.cache')
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        core = root / 'core.sv'
        core.write_text('`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CORE_BIND_PUBLIC\n'
                        '`include "verilog/tri_oracle_sram_memory_compute.sv"\n' +
                        ''.join(f'`include "{path}"\n' for path in models(self.corner)))
        cache = root / 'cache.sv'
        bank = json.loads(Path('records/sram_activation_cache_bank_views.json').read_text())[
            'banks']['metadata']
        model = bank['models'][self.corner]
        assert hashlib.sha256(Path(model).read_bytes()).hexdigest() == bank['sha256'][model]
        cache.write_text('`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CACHE_BIND_PUBLIC\n'
                         '`include "verilog/tri_oracle_sram_activation_cache.sv"\n'
                         f'`include "{model}"\n')
        self.dependency_overrides = {'memory_compute': str(core), 'activation_cache': str(cache)}
        self.native_progress_path = f'records/sram_fabric_{self.corner}_native_progress.log'


class SramFeedforwardTest(BackendSelection, feedforward_tests.MemoryFeedforwardTest):
    pass


class SramFabricTest(BackendSelection, fabric_tests.FabricProjectionTest):
    pass


if __name__ == '__main__':
    unittest.main()
