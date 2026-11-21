import unittest
from tri_oracle_control_row_packing import enumerate_leaves, pack

class PackingContract(unittest.TestCase):
    def test_exact_fit_and_residual_intervals(self):
        cells=[('a','BUF',5),('b','BUF',4),('c','BUF',1)]
        result=pack(cells,[(0,0,10)],(0,0),1,1)
        occupied=[]
        for _,_,row,col,width in result:occupied.extend((row,x) for x in range(col,col+width))
        self.assertEqual(len(occupied),len(set(occupied)))
        self.assertEqual(set(occupied),{(0,x) for x in range(10)})
    def test_disjoint_holes_do_not_cross_retained_cells(self):
        result=pack([('a','BUF',3),('b','BUF',2)],[(0,0,3),(0,7,2)],(8,0),1,1)
        self.assertEqual({x for *_,col,width in result for x in range(col,col+width)},{0,1,2,7,8})
    def test_fragmented_capacity_cannot_fit_wide_cell(self):
        with self.assertRaisesRegex(ValueError,'No free interval'):
            pack([('a','BUF',4)],[(0,0,3),(1,0,3)],(0,0),1,1)
    def test_duplicate_instance_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            pack([('a','BUF',1),('a','BUF',1)],[(0,0,4)],(0,0),1,1)
    def test_wrapped_and_escaped_mapped_hierarchy(self):
        text='module leaf(a);\n BUF \\q[0]\n (.I(a));\nendmodule\nmodule top(a);\n leaf\n child(.a(a));\n leaf other (.a(a));\nendmodule\n'
        self.assertEqual(enumerate_leaves(text,'top',{'BUF'}),[('child/q[0]','BUF'),('other/q[0]','BUF')])
    def test_unknown_leaf_and_recursion_are_rejected(self):
        for text in ['module top(a);\n WRONG u(.I(a));\nendmodule\n','module top(a);\n top u(.I(a));\nendmodule\n']:
            with self.subTest(text=text),self.assertRaises(ValueError):enumerate_leaves(text,'top',{'BUF'})

if __name__ == '__main__':unittest.main()
