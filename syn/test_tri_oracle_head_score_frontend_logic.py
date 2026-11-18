"""Check actual semantic port ordering and score-tag rejection gate cones."""
from pathlib import Path
import importlib.util
import subprocess
import sys
import unittest
import tempfile

SOURCE=Path(__file__).with_name('prove_tri_oracle_head_score_frontend.py')


class HeadScoreFrontendTests(unittest.TestCase):
    def engine(self):
        self.assertTrue(SOURCE.exists(),'Parent score frontend verifier is missing')
        spec=importlib.util.spec_from_file_location('score_frontend',SOURCE)
        engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
        return engine

    def fixture(self,*,swap=False,bypass=False):
        from prove_tri_oracle_head_configuration import ParentCone
        from prove_tri_oracle_parent_reset import Module
        data='{request[0],request[3:1]}' if swap else 'request'
        body=f'''module parent(clk,rst_n,saved,request,ready);
        input clk,rst_n,ready; input [1:0] saved; output [3:0] request;
        wire [1:0] rawtag,rawregion,guarded; wire a,b,mismatch;
        TILE tile(.score_data({data}),.score_tag(rawtag),.score_region(rawregion),.score_ready(ready));
        XOR2 x0(.A(rawtag[0]),.B(saved[0]),.Z(a)); XOR2 x1(.A(rawtag[1]),.B(saved[1]),.Z(b));
        OR2 combine(.A(a),.B(b),.Z(mismatch));
        OR2 region0(.A(rawregion[0]),.B({"1'b0" if bypass else 'mismatch'}),.Z(guarded[0]));
        OR2 region1(.A(rawregion[1]),.B(mismatch),.Z(guarded[1])); endmodule'''.encode()
        child=Module(b'module TILE(score_data,score_tag,score_region,score_ready); output [3:0] score_data; output [1:0] score_tag,score_region; input score_ready; endmodule')
        library={}
        for name,function in [('OR2','A | B'),('XOR2','A ^ B')]:
            library[name,'A']={'direction':'input'};library[name,'B']={'direction':'input'}
            library[name,'Z']={'direction':'output','function':function}
        model=ParentCone(body,library,{}, {'TILE':child})
        return model,model.module.cells['tile'][1]

    def test_tile_payload_bit_permutation_is_not_hidden_by_output_cutpoints(self):
        engine=self.engine()
        for swap in (False,True):
            model,pins=self.fixture(swap=swap);bridge=engine.WordBridge(model.graph)
            source=engine.port_value(model,bridge,pins,'score_data',4)
            actual=bridge.pack(bridge.convert([model.cone(f'request[{bit}]') for bit in range(4)]))
            if swap:
                with self.assertRaises(AssertionError):bridge.check([actual],[source],label='payload')
            else:bridge.check([actual],[source],label='payload')

    def test_guard_checks_actual_gates_for_matched_and_mismatched_tags(self):
        engine=self.engine()
        model,pins=self.fixture();bridge=engine.WordBridge(model.graph)
        engine.check_tag_guard(model,bridge,pins,['saved[0]','saved[1]'],['guarded[0]','guarded[1]'])
        model,pins=self.fixture(bypass=True);bridge=engine.WordBridge(model.graph)
        with self.assertRaises(AssertionError) as error:
            engine.check_tag_guard(model,bridge,pins,['saved[0]','saved[1]'],['guarded[0]','guarded[1]'],mismatch_only=True)
        self.assertEqual(error.exception.args[0][2],'sat')

    def test_optimized_python_is_rejected(self):
        self.engine()
        result=subprocess.run([sys.executable,'-O','-B','-c','import sys;sys.path.insert(0,"syn");import prove_tri_oracle_head_score_frontend'],
            cwd=SOURCE.parent.parent,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('requires Python assertions',result.stderr)

    def test_report_path_is_rejected_before_design_loading(self):
        engine=self.engine()
        self.assertTrue(hasattr(engine,'verify'),'Candidate-bound frontend verification is missing')
        with self.assertRaises(AssertionError):engine.verify(SOURCE.parent/'forbidden-report.json')

    def test_late_rehash_uses_file_hashes_and_rejects_changed_or_missing_inputs(self):
        engine=self.engine()
        self.assertTrue(hasattr(engine,'revalidate_evidence'),'Independent final rehash is missing')
        from hashlib import sha256
        with tempfile.TemporaryDirectory(dir=SOURCE.parent.parent/'.cache') as folder:
            root=Path(folder);(root/'first').write_bytes(b'alpha');(root/'second').write_bytes(b'beta')
            evidence={'first':sha256(b'alpha').hexdigest(),'second':sha256(b'beta').hexdigest()}
            self.assertEqual(engine.revalidate_evidence(evidence,root),2)
            (root/'first').write_bytes(b'changed')
            with self.assertRaises(AssertionError):engine.revalidate_evidence(evidence,root)
            (root/'first').write_bytes(b'alpha');(root/'second').unlink()
            with self.assertRaises(FileNotFoundError):engine.revalidate_evidence(evidence,root)
            with self.assertRaises(AssertionError):engine.revalidate_evidence({},root)


if __name__=='__main__':unittest.main()
