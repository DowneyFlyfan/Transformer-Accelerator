"""Accepted traffic must prove its modes, rather than assume them."""
from pathlib import Path
import sys,unittest,z3
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prove_tri_oracle_head_intensity import WordBridge
from prove_tri_oracle_packaged_products import BooleanGraph


class AcceptedCommandTest(unittest.TestCase):
    def terms(self):
        bits={name:z3.BoolVal(value) for name,value in dict(reset=True,producer_valid=True,
            producer_ready=True,projection=False,owned=False,enabled=True,selected=True,
            wrapper_busy=False,paired=False,owner_valid=True,owner_ready=True).items()}
        bits.update(producer_state=z3.BitVecVal(2,3),layer=z3.BitVecVal(5,4),
                    arbiter=z3.BitVecVal(0,4),owner_state=z3.BitVecVal(0,5))
        return bits

    def test_accepted_disabled_attention_is_rejected_without_assuming_enable(self):
        from prove_tri_oracle_accepted_command import acceptance_queries
        terms=self.terms();terms['enabled']=z3.BoolVal(False)
        with self.assertRaisesRegex(AssertionError,'accepted_producer_implies_actual_attention_mode'):
            acceptance_queries(WordBridge(BooleanGraph()),terms)

    def test_accepted_receiver_with_dropped_valid_is_rejected(self):
        from prove_tri_oracle_accepted_command import acceptance_queries
        terms=self.terms();terms['owner_valid']=z3.BoolVal(False)
        with self.assertRaisesRegex(AssertionError,'accepted_producer_implies_actual_receiver_handshake'):
            acceptance_queries(WordBridge(BooleanGraph()),terms)

    def test_ready_without_valid_is_not_an_accepted_transfer(self):
        from prove_tri_oracle_accepted_command import acceptance_queries
        terms=self.terms();terms['producer_state']=z3.BitVecVal(0,3)
        terms['producer_valid']=z3.BoolVal(False);terms['enabled']=z3.BoolVal(False)
        bridge=WordBridge(BooleanGraph());acceptance_queries(bridge,terms)
        self.assertEqual(len(bridge.checks),4)

    def test_impossible_accepted_witness_fails_closed(self):
        from prove_tri_oracle_accepted_command import accepted_witness
        with self.assertRaisesRegex(AssertionError,'Accepted command witness absent'):
            accepted_witness([z3.BoolVal(False)])

    def test_asserted_reset_never_exports_an_accepted_command(self):
        from prove_tri_oracle_accepted_command import acceptance_queries
        terms=self.terms();terms['reset']=z3.BoolVal(False)
        contract=acceptance_queries(WordBridge(BooleanGraph()),terms)
        self.assertTrue(z3.is_false(z3.simplify(contract['accepted'])))

    def test_payload_composition_preserves_idle_producer_acceptance(self):
        from prove_tri_oracle_accepted_command import prove_accepted_payload
        from prove_tri_oracle_tile_command_routes import CommandRoutes
        widths={'cfg_channels':2560,'cfg_keep':2560,'cfg_tokens':5,'cfg_tag':32,
            'cfg_count':8,'cfg_dense_rows':17,'cfg_feature_words':10,'cfg_activation_stride':32,
            'cfg_activation_base':64,'cfg_weight_base':64}
        body=('module receiver('+','.join(widths)+');\n'+''.join(
            f'input [{width-1}:0] {name};\n' for name,width in widths.items())+'endmodule\n').encode()
        routes=CommandRoutes(lambda _:body,{'receiver'},{},{},'receiver')
        bridge=WordBridge(routes.graph);false=z3.BoolVal(False);true=z3.BoolVal(True)
        environment={'routes':routes,'paths':{'owner':''}}
        # The earlier key describes available capacity, even without a request.
        routed={'conditions':[true],'accepted':true}
        contract={'bridge':bridge,'conditions':[false],'accepted':false,
                  'terms':{'owner_valid':false,'owner_ready':true}}
        geometry={name:z3.BitVecVal(value,width) for name,value,width in (
            ('query',96,13),('tokens',1,5),('tag',7,32),('rows',1,11),('query_addr',0,64),('key_base',0,64))}
        command={'old_scalar':geometry,'scalar_invariant':true,'invariant':true}
        composed=prove_accepted_payload(environment,routed,contract,command,
            only_query='actual_acceptance_discharges_prior_route_mode_conditions')
        self.assertTrue(z3.is_false(z3.simplify(composed['accepted'])))


if __name__=='__main__':unittest.main()
