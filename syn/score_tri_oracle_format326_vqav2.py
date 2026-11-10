"""Official scoring of the completed format324 four-mode,64-question pilot.

The original floating and legacy dense answers/scores must reproduce the old
qualified pilot. New formats affect only22 language feed-forward sublayers;
the rest of the model remains floating. This reused validation subset does not
establish the paper's full benchmark, preprocessing, checkpoint or chip results.
"""
import contextlib
import copy
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


PROVENANCE_SHA = 'b17d793afc6949fe2fff451ab45690dbc0c1925e21b773bfce206613bfcc8d47'
CONVERTED_SHA = 'ba95df786a47077b046d9e5715dcfdaa32159c15fb6606b242f13e808e3b6f93'
INFERENCE_SHA = '357565db2a2a594cf90041b5026a8e584928b3467d030766f2368539f419999b'
MODES = ('floating', 'legacy_integer_dense', 'integer_dense', 'integer_predicted')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_official_sources(root):
    provenance = root / 'records/vqav2_evaluation_primary_sources.json'
    assert sha(provenance) == PROVENANCE_SHA
    sources = json.loads(provenance.read_text())['sources']
    assert len(sources) == 4
    for item in sources:
        assert sha(root / item['path']) == item['sha256'], item['path']
    evaluator_path = root / '.cache/model_reference/vqa_evaluation/VQA_vqaEval.py'
    original = evaluator_path.read_text()
    converted = original
    for literal in ('computing accuracy', 'Done computing accuracy'):
        before = 'print "' + literal + '"'
        assert converted.count(before) == 1
        converted = converted.replace(before, 'print("' + literal + '")')
    assert hashlib.sha256(converted.encode()).hexdigest() == CONVERTED_SHA
    evaluator_module = {'__name__': 'tri_oracle_pinned_vqa_evaluator'}
    exec(compile(converted, str(evaluator_path), 'exec'), evaluator_module)
    processor_path = root / '.cache/model_reference/vqa_evaluation/LLaVA_m4c_evaluator.py'
    processor_module = {'__name__': 'tri_oracle_pinned_answer_processor'}
    exec(compile(processor_path.read_text(), str(processor_path), 'exec'), processor_module)
    fingerprints = {str(root / item['path']): item['sha256'] for item in sources}
    fingerprints[str(provenance)] = PROVENANCE_SHA
    return evaluator_module['VQAEval'], processor_module['EvalAIAnswerProcessor'], fingerprints


class Questions:
    def __init__(self, qa):
        self.qa = qa

    def getQuesIds(self):
        return list(self.qa)


def score_cases(samples, cases, evaluator_type, processor_type):
    sample_ids = [item['question_id'] for item in samples]
    prediction_ids = [item['question_id'] for item in cases]
    if (not samples or len(set(sample_ids)) != len(sample_ids)
            or len(set(prediction_ids)) != len(prediction_ids)
            or set(sample_ids) != set(prediction_ids)):
        raise ValueError('Scoring requires exactly one prediction for every fixed question')
    expected = {item['question_id']: item['image_id'] for item in samples}
    if any(item['image_id'] != expected[item['question_id']] for item in cases):
        raise ValueError('Prediction image differs from its fixed question image')
    if any(len(item['answers']) != 10 for item in samples):
        raise ValueError('Official scoring requires ten human answers')
    processor = processor_type()
    normalized = {item['question_id']: processor(item['answer']) for item in cases}
    truth = Questions({item['question_id']: copy.deepcopy(item) for item in samples})
    predictions = Questions({key: {'answer': value} for key, value in normalized.items()})
    evaluator = evaluator_type(truth, predictions, n=2)
    with contextlib.redirect_stdout(io.StringIO()):
        evaluator.evaluate()
    return dict(official_vqa_consensus_percent_on64=evaluator.accuracy['overall'],
                per_answer_type=evaluator.accuracy['perAnswerType'],
                per_question_score={str(key): value for key, value in evaluator.evalQA.items()},
                normalized_predictions={str(key): value for key, value in normalized.items()})


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    started = time.monotonic()
    output = root / 'records/format326_official_scoring.json'
    assert not output.exists()
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:'))) * 1024
    assert available > 6 * 1024**3
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    evaluator_type, processor_type, inputs = load_official_sources(root)
    result_path = root / 'records/format324_vqav2_inference.json'
    guard_path = root / 'records/format325_gpu_guard_result.json'
    prior_path = root / 'records/vqav2_integer_pilot_01.json'
    prior_qualification_path = root / 'records/vqav2_integer_pilot_execution_qualification.json'
    prior_score_path = root / 'records/vqav2_integer_pilot_official_scoring.json'
    data_qualification_path = root / 'records/vqav2_pilot_data_qualification.json'
    manifest_path = root / '.cache/model_reference/vqav2_pilot/manifest.json'
    test_path = root / 'syn/test_tri_oracle_format326_scoring.py'
    result = json.loads(result_path.read_text())
    guard = json.loads(guard_path.read_text())
    prior = json.loads(prior_path.read_text())
    prior_qualification = json.loads(prior_qualification_path.read_text())
    prior_score = json.loads(prior_score_path.read_text())
    data_qualification = json.loads(data_qualification_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    assert guard['state'] == 'completed' and guard['native_exit_status'] == 0 and guard['input_drift'] == []
    assert sha(result_path) == guard['summary_sha256'] == INFERENCE_SHA
    assert result['state'] == 'completed' and result['sample_count'] == 64 and len(result['cases']) == 256
    assert prior['state'] == 'completed' and prior_qualification['all192_inference_cases_completed'] is True
    assert sha(prior_path) == prior_qualification['result_sha256'] == prior_score['inference_result_sha256']
    assert sha(prior_qualification_path) == prior_score['inference_qualification_sha256']
    assert prior_score['official_scoring_executed'] is True
    assert prior_score['source_provenance_sha256'] == PROVENANCE_SHA
    assert prior_score['converted_evaluator_sha256'] == CONVERTED_SHA
    assert data_qualification['dataset_preparation_passed'] is True
    assert sha(manifest_path) == data_qualification['manifest_sha256']
    samples = manifest['samples']
    assert len(samples) == len({item['question_id'] for item in samples}) == len({item['image_id'] for item in samples}) == 64
    inputs.update(result['source_sha256'])
    for path, digest in guard['source_sha256'].items():
        assert path not in inputs or inputs[path] == digest
        inputs[path] = digest
    for path in (Path(__file__), result_path, guard_path, prior_path, prior_qualification_path,
                 prior_score_path, data_qualification_path, manifest_path, test_path):
        key = str(path.resolve())
        assert key not in inputs or inputs[key] == sha(path)
        inputs[key] = sha(path)
    native_log = root / '.cache/format325_gpu_native.log'
    assert sha(native_log) == guard['native_log_sha256']
    inputs[str(native_log)] = guard['native_log_sha256']
    assert all(sha(path) == digest for path, digest in inputs.items())
    print('FORMAT326_ALL_INPUTS_FROZEN', len(inputs), flush=True)
    tests = subprocess.run([sys.executable, '-B', '-m', 'unittest',
                            'syn/test_tri_oracle_format326_scoring.py'], cwd=root,
                           capture_output=True, text=True, timeout=60, check=True)
    previous = {(item['mode'], item['question_id']): item for item in prior['cases']}
    assert len(previous) == 192
    assert {item['mode'] for item in result['cases']} == set(MODES)
    scored = {}
    for mode in MODES:
        cases = [item for item in result['cases'] if item['mode'] == mode]
        assert len(cases) == 64
        for item in cases:
            assert item['integer_layers'] == (0 if mode == 'floating' else 22)
            assert item['per_layer_calls'] == ([] if mode == 'floating' else [len(item['answer_tokens']) + 1] * 22)
        if mode in ('floating', 'legacy_integer_dense'):
            old_mode = 'floating' if mode == 'floating' else 'integer_dense'
            assert all(item['answer_tokens'] == previous[old_mode, item['question_id']]['answer_tokens'] for item in cases)
        scored[mode] = score_cases(samples, cases, evaluator_type, processor_type)
        if mode in ('floating', 'legacy_integer_dense'):
            assert scored[mode] == prior_score['results'][old_mode], 'Baseline score/predictions changed'
        print('FORMAT326_OFFICIAL_SCORE', mode, scored[mode]['official_vqa_consensus_percent_on64'], flush=True)
    assert all(sha(path) == digest for path, digest in inputs.items())
    record = dict(state='official_pilot_scoring_completed_baselines_reproduced',
                  created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  sample_count=64, inference_cases=256, source_sha256=inputs,
                  official_scoring_executed=True, converted_evaluator_sha256=CONVERTED_SHA,
                  compatibility_changes='Exactly two Python2 print statements converted; scoring algorithm unchanged.',
                  submission_normalization='Pinned unchanged LLaVA EvalAIAnswerProcessor.',
                  controls_stdout=tests.stdout, controls_stderr=tests.stderr,
                  controls_exit_status=tests.returncode, baseline_per_question_and_answers_reproduced=True,
                  results=scored, whole_model_integer=False, hardware_configuration_mapping_verified=False,
                  paper_accuracy_matched=False, full_paper_results_matched=False,
                  full_validation_question_count=214354, elapsed_seconds=time.monotonic() - started,
                  maximum_resident_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  scope=__doc__)
    with output.open('x') as stream:
        stream.write(json.dumps(record, indent=2) + '\n')
    print('FORMAT326_COMPLETED', sha(output), flush=True)


if __name__ == '__main__':
    main()
