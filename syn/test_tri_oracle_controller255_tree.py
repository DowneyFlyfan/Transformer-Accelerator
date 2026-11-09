"""Loss, overloading and malformed geometry must not enter a buffer-tree plan."""
import unittest
from collections import Counter
from tri_oracle_controller255_tree import plan_buffers


class TreePlanTests(unittest.TestCase):
    def test_998_loads_remain_reachable_once_with_four_buffer_stages(self):
        rows = [(f'gate/pin[{i}]/E', float(i % 32), float(i // 32)) for i in range(998)]
        nodes = plan_buffers(rows)
        self.assertEqual(len(nodes), 43)  #32leaves +8parents +2parents +1root.
        found = []
        visited = set()
        depths = []

        def visit(index, depth):
            self.assertNotIn(index, visited)
            visited.add(index)
            node = nodes[index]
            self.assertEqual(node['id'], index)
            self.assertLessEqual(len(node['children']), 4)
            if node['pins']:
                self.assertFalse(node['children'])
                self.assertLessEqual(len(node['pins']), 32)
                found.extend(node['pins'])
                depths.append(depth)
            else:
                self.assertTrue(node['children'])
                for child in node['children']:
                    self.assertLess(child, index)
                    visit(child, depth+1)
        visit(len(nodes)-1, 1)
        self.assertEqual(Counter(found), Counter(row[0] for row in rows))
        self.assertEqual(len(visited), 43)
        self.assertEqual(set(depths), {4})
        self.assertEqual(nodes[-1]['master'], 'BUFFD16BWP12T40P140')

    def test_far_apart_sinks_receive_separate_local_branches(self):
        nodes = plan_buffers([('d/E', 102., 0.), ('b/E', 2., 0.), ('c/E', 100., 0.), ('a/E', 0., 0.)], leaf_loads=2, branch_fanout=2)
        self.assertEqual(len(nodes), 3)
        self.assertEqual({frozenset(n['pins']) for n in nodes if n['pins']}, {frozenset(['a/E', 'b/E']), frozenset(['c/E', 'd/E'])})
        self.assertEqual((nodes[-1]['x'], nodes[-1]['y']), (51., 0.))

    def test_input_order_does_not_change_the_physical_plan(self):
        rows = [(f'p{i}/E', float(i % 3), float(i % 5)) for i in range(67)]
        self.assertEqual(plan_buffers(rows), plan_buffers(list(reversed(rows))))

    def test_empty_duplicate_nonfinite_and_unserializable_sinks_are_rejected(self):
        bad = [[], [('a/E', 0, 0), ('a/E', 1, 1)], [('a/E', float('nan'), 0)], [('a/E', 0, float('inf'))], [('bad pin/E', 0, 0)]]
        for rows in bad:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                plan_buffers(rows)

    def test_nonshrinking_or_invalid_branch_limits_are_rejected(self):
        for leaf, branch in [(0, 4), (32, 1), (32, 0), (1.5, 4), (True, 4)]:
            with self.subTest(leaf=leaf, branch=branch), self.assertRaises(ValueError):
                plan_buffers([('a/E', 0, 0)], leaf_loads=leaf, branch_fanout=branch)

    def test_single_sink_has_one_transparent_root_at_its_location(self):
        nodes = plan_buffers([('single/E', 11., 7.)])
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]['pins'], ['single/E'])
        self.assertEqual(nodes[0]['children'], [])
        self.assertEqual((nodes[0]['x'], nodes[0]['y']), (11., 7.))


if __name__ == '__main__':
    unittest.main()
