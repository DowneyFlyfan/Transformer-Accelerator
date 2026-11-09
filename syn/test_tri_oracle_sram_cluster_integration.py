"""Select both compiled core memories and compiled cluster result memories."""
from pathlib import Path

from test_tri_oracle_fabric_projection import FabricProjectionTest
from test_tri_oracle_sram_integration import BackendSelection, SramFeedforwardTest


class SramFabricTest(BackendSelection, FabricProjectionTest):
    def setUp(self):
        super().setUp()
        cluster = Path(self.directory.name)/'cluster.sv'
        cluster.write_text('`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n'
                           '`include "verilog/tri_oracle_sram_compute_cluster.sv"\n')
        self.dependency_overrides['compute_cluster'] = str(cluster)
