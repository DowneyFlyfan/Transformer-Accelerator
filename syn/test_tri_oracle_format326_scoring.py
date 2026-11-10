"""Catch incorrect consensus, normalization, mutation and cohort admission."""
import copy
import importlib.util
from pathlib import Path
import unittest


class OfficialScoringTests(unittest.TestCase):
    def setUp(self):
        path = Path('syn/score_tri_oracle_format326_vqav2.py')
        self.assertTrue(path.is_file(), 'The qualified pilot scoring driver is missing')
        spec = importlib.util.spec_from_file_location('format326', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.evaluator, self.processor, _ = self.module.load_official_sources(Path.cwd())

    @staticmethod
    def sample(question_id, matching):
        return dict(question_id=question_id, image_id=question_id,
                    question_type='literal', answer_type='other',
                    answers=[dict(answer='two' if index < matching else 'other',
                                  answer_id=index + 1, answer_confidence='yes')
                             for index in range(10)])

    def test_literal_ten_voter_consensus_and_submission_normalization(self):
        # Removing normalization or changing leave-one-out voting breaks literals.
        samples = [self.sample(index, index) for index in range(1, 5)]
        cases = [dict(question_id=index, image_id=index, answer='The TWO!')
                 for index in range(1, 5)]
        result = self.module.score_cases(samples, cases, self.evaluator, self.processor)
        self.assertEqual(result['per_question_score'],
                         {'1': 30.0, '2': 60.0, '3': 90.0, '4': 100.0})
        self.assertEqual(result['official_vqa_consensus_percent_on64'], 70.0)
        self.assertEqual(set(result['normalized_predictions'].values()), {'2'})

    def test_wrong_answers_score_zero_without_mutating_labels(self):
        samples = [self.sample(1, 2)]
        samples[0]['answers'][0]['answer'] = '\ttwo\n'
        before = copy.deepcopy(samples)
        result = self.module.score_cases(samples, [dict(question_id=1, image_id=1,
                                        answer='impossible answer')],
                                        self.evaluator, self.processor)
        self.assertEqual(result['official_vqa_consensus_percent_on64'], 0.0)
        self.assertEqual(samples, before)

    def test_missing_extra_duplicate_and_wrong_image_predictions_rejected(self):
        # Silent dictionary overwrites or intersection-only scoring must fail.
        samples = [self.sample(1, 2)]
        valid = dict(question_id=1, image_id=1, answer='two')
        invalid = [[], [valid, valid],
                   [valid, dict(question_id=2, image_id=2, answer='two')],
                   [dict(valid, image_id=2)]]
        for cases in invalid:
            with self.subTest(cases=cases), self.assertRaises(ValueError):
                self.module.score_cases(samples, cases, self.evaluator, self.processor)


if __name__ == '__main__':
    unittest.main()
