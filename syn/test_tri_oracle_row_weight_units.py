"""Independent literal fixtures catch wrong row units, float32 ties and channel packing."""
from pathlib import Path
import hashlib
import json
import math
import os
import struct
import tempfile
import unittest
from tri_oracle_row_weight_units import inspect_matrix,pack_metadata,quantize_row

WORK=Path(__file__).resolve().parents[1]/".cache"
WORK.mkdir(exist_ok=True)


class WeightUnits(unittest.TestCase):
    def matrix(self,values,shape,dtype='F32',offset_extra=0):
        # values[R*F] are literal trained-row stand-ins; shape=[rows,features].
        payload=struct.pack('<'+'f'*len(values),*values)
        header=json.dumps({'weight':dict(dtype=dtype,shape=shape,data_offsets=[0,len(payload)+offset_extra])}).encode()
        fd,name=tempfile.mkstemp(prefix='literal_weights_',dir=WORK);os.close(fd)
        path=Path(name);path.write_bytes(struct.pack('<Q',len(header))+header+payload)
        self.addCleanup(path.unlink,missing_ok=True)
        return path

    def test_different_row_scales_preserve_their_signed_codes(self):
        path=self.matrix([0,1,-1,.5,.125,-.125,0,.0625,127/128,-127/128,1/256,-1/256],[3,4])
        result=inspect_matrix(path,'weight',rows_per_chunk=2)
        self.assertEqual(result['row_exponents'],[-6,-9,-7])
        self.assertEqual(result['global_exponent'],-6)
        self.assertEqual(result['relative_row_deltas'],[0,3,1])
        self.assertEqual(result['code_sha256'],hashlib.sha256(bytes([0,64,192,32,64,192,0,32,127,129,1,255])).hexdigest())

    def test_exact_maximum_boundary_and_next_float_do_not_share_exponent(self):
        codes,unit=quantize_row([127/128,-127/128,1/256,-1/256])
        self.assertEqual((codes,unit),(bytes([127,129,1,255]),-7))
        codes,unit=quantize_row([127/128+2**-24])
        self.assertEqual((codes,unit),(bytes([64]),-6))

    def test_half_addition_is_float32_before_floor(self):
        # F32 addition makes the value immediately below +0.5 round to 1.
        # The maximum 1 fixes the unit at -6; +/-2^-7 are code-half ties.
        codes,unit=quantize_row([1,-1,2**-7,-2**-7,(.5-2**-25)/64])
        self.assertEqual((codes,unit),(bytes([64,192,1,255,1]),-6))

    def test_zero_and_negative_zero_use_canonical_zero_unit(self):
        self.assertEqual(quantize_row([0.,-0.,0.]),(bytes([0,0,0]),0))

    def test_nonfinite_trained_weights_are_rejected(self):
        for value in [math.inf,-math.inf,math.nan]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):quantize_row([value,1])

    def test_wrong_dtype_shape_offsets_and_truncation_are_rejected(self):
        for dtype,shape,extra in [('F16',[1,4],0),('F32',[1,3],0),('F32',[1,4],4)]:
            with self.subTest(dtype=dtype,shape=shape,extra=extra):
                path=self.matrix([1,2,3,4],shape,dtype,extra)
                with self.assertRaises(ValueError):inspect_matrix(path,'weight')

    def test_packed_gate_up_pairs_have_literal_bit_order_and_zero_tail(self):
        packets=pack_metadata([0,3,1],[1,0,7])
        self.assertEqual(packets,[dict(start=0,count=3,word_hex=f'{0x390c8:0120x}')])

    def test_maximum_packet_and_next_original_channel_are_distinct(self):
        gate=[0]*80+[7];up=[1]*80+[3]
        packets=pack_metadata(gate,up)
        self.assertEqual([(p['start'],p['count']) for p in packets],[(0,80),(80,1)])
        self.assertEqual(packets[-1]['word_hex'],f'{31:0120x}')

    def test_invalid_offset_range_and_unpaired_rows_are_not_clamped(self):
        for gate,up in [([8],[0]),([-1],[0]),([0],[])]:
            with self.subTest(gate=gate,up=up):
                with self.assertRaises(ValueError):pack_metadata(gate,up)


if __name__=='__main__':unittest.main()
