"""Memory-span boundaries and receiver header interpretation use literal cases."""
from pathlib import Path
import sys,unittest,z3
sys.path.insert(0,str(Path(__file__).resolve().parent))

class CommandAdmissionTest(unittest.TestCase):
    def test_last_byte_distinguishes_maximum_address_from_overflow(self):
        from prove_tri_oracle_command_admission import last_byte
        for base,wanted in ((2**64-64,2**64-1),(2**64-56,2**64+7)):
            value=last_byte(z3.BitVecVal(base,64),z3.BitVecVal(1,65))
            self.assertEqual(z3.simplify(value).as_long(),wanted)

    def test_parent_config_rejects_short_misaligned_zero_ratio_and_wrapped_spans(self):
        from prove_tri_oracle_command_admission import reference_parent_bad
        for total,den,query,key,wanted in ((97,1,0,0,False),(96,1,0,0,True),
            (97,0,0,0,True),(97,1,1,0,True),(97,1,0,1,True),
            (97,1,2**64-64,2**64-97*64,False),(97,1,2**64-56,0,True),
            (97,1,0,2**64-97*64+8,True)):
            value=reference_parent_bad(z3.BitVecVal(total,11),z3.BitVecVal(den,8),
                z3.BitVecVal(query,64),z3.BitVecVal(key,64))
            self.assertEqual(z3.is_true(z3.simplify(value)),wanted)

    def test_parent_scope_does_not_invent_unobserved_upper_token_bits(self):
        from prove_tri_oracle_command_admission import reference_parent_bad
        with self.assertRaisesRegex(AssertionError,'observed'):
            reference_parent_bad(z3.BitVecVal(97,13),z3.BitVecVal(1,8),z3.BitVecVal(0,64),z3.BitVecVal(0,64))

    def parent(self,state,query,total,base,key=0):
        return dict(state=z3.BitVecVal(state,3),query=z3.BitVecVal(query,13),tokens=z3.BitVecVal(total,11),
                    query_addr=z3.BitVecVal(base,64),key_base=z3.BitVecVal(key,64))

    def test_remaining_queries_determine_the_stored_query_span(self):
        from prove_tri_oracle_command_admission import address_invariant
        self.assertTrue(z3.is_true(z3.simplify(address_invariant(self.parent(3,112,113,2**64-64)))))
        self.assertFalse(z3.is_true(z3.simplify(address_invariant(self.parent(3,96,113,2**64-64)))))

    def test_idle_reset_does_not_require_an_active_query_span(self):
        from prove_tri_oracle_command_admission import address_invariant
        self.assertTrue(z3.is_true(z3.simplify(address_invariant(self.parent(0,96,0,0)))))

    def test_active_query_and_key_addresses_remain_aligned(self):
        from prove_tri_oracle_command_admission import address_invariant
        for base,key in ((1,0),(0,1)):
            self.assertFalse(z3.is_true(z3.simplify(address_invariant(self.parent(2,96,97,base,key)))))

    def test_header_partition_uses_feature_words_divided_by_four(self):
        from prove_tri_oracle_command_admission import header_source
        self.assertEqual(header_source('part_words',0),'cfg_feature_words[2]')
        self.assertEqual(header_source('part_words',7),'cfg_feature_words[9]')
        self.assertEqual(header_source('paired',0),'cfg_paired')
        self.assertEqual(header_source('tag',31),'cfg_tag[31]')
        with self.assertRaisesRegex(AssertionError,'header'):
            header_source('paired',1)

    def test_single_core_score_mode_keeps_the_full_feature_word_count(self):
        from prove_tri_oracle_command_admission import reference_part_words
        for single,wanted in ((False,2),(True,8)):
            actual=reference_part_words(z3.BitVecVal(8,10),z3.BoolVal(single))
            self.assertEqual(z3.simplify(actual).as_long(),wanted)

    def test_captured_auxiliary_modes_use_the_actual_command_fields(self):
        from prove_tri_oracle_command_admission import header_source
        for field,index,wanted in (
            ('packed_weights',0,'cfg_packed_weights'),('local_scores',0,'softmax_request[score_tile]'),
            ('single_core_scores',0,'softmax_request[score_core]'),('score_core',1,'softmax_request[owner][1]'),
            ('score_cluster',2,'softmax_request[owner][4]')):
            self.assertEqual(header_source(field,index),wanted)

    def route_with_unrelated_memory(self):
        from prove_tri_oracle_command_admission import AdmissionRoutes
        body=b'module m(d, q);\ninput d;\noutput q;\nwire other;\nF state (.D(d),.Q(q));\nRAM unrelated (.Q(other));\nendmodule\n'
        library={('F','D'):{'direction':'input'},('F','Q'):{'direction':'output','function':'IQ'}}
        return AdmissionRoutes(lambda _:body,{'m'},library,{'F':{'ff':1}},'m',tile='')

    def test_unrelated_unsupported_memory_pin_does_not_block_a_known_route(self):
        route=self.route_with_unrelated_memory();root=route.trace('','q')
        self.assertEqual(route.graph.dependencies(root),{'tile.q'})

    def test_relevant_unknown_pin_still_fails_closed(self):
        route=self.route_with_unrelated_memory()
        with self.assertRaisesRegex(ValueError,'Unknown library pin'):
            route.trace('','other')

    def test_escaped_partition_pin_keeps_original_name_nets_and_body_hash(self):
        from hashlib import sha256
        from prove_tri_oracle_command_admission import parse_admission_module
        body=b'module m(a);\ninput a;\nC cell (.\\scale_score_650_52:srl_553_97_Z (a));\nendmodule\n'
        parsed=parse_admission_module(body)
        self.assertEqual(parsed.cells['cell'][1],{'scale_score_650_52:srl_553_97_Z':'a'})
        self.assertEqual(parsed.sha256,sha256(body).hexdigest())

    def test_unescaped_colon_pin_and_duplicate_escaped_pin_still_fail(self):
        from prove_tri_oracle_command_admission import parse_admission_module
        for ports in (b'.bad:pin(a)',b'.\\bad:pin (a),.\\bad:pin (a)'):
            with self.assertRaises(AssertionError):
                parse_admission_module(b'module m(a);\ninput a;\nC cell ('+ports+b');\nendmodule\n')

    def test_escaped_instance_is_never_rewritten_as_a_pin_token(self):
        from prove_tri_oracle_command_admission import parse_admission_module
        body=b'module m(a);\ninput a;\n'+rb'C \cell.\bad:pin (.Q(a));'+b'\nendmodule\n'
        with self.assertRaisesRegex(ValueError,'Unsupported identifier'):
            parse_admission_module(body)

if __name__=='__main__':unittest.main()
