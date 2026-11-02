from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time

import pytest
import torch

from next_draw.candidates import generate_candidates
from next_draw.jobs import JobManager
from next_draw.selector import LayaSelector
from next_draw.training import Trainer
from next_draw.rules import validate_numbers


@pytest.mark.parametrize("game", ["ssq", "dlt", "qlc"])
def test_candidates_are_legal_deduplicated_and_repeatable_with_a_seed(game, tmp_path):
    bundle = Trainer(tmp_path)._new(game, "fixture-untrained-only-for-rules-test")
    bundle.front.eval(); bundle.back.eval()
    spec = {"ssq": ([1, 3, 5, 8, 20, 30], [7]), "dlt": ([1, 3, 5, 8, 20], [2, 11]), "qlc": ([1, 3, 5, 8, 12, 20, 30], [7])}[game]
    recent = [{"front": spec[0], "back": spec[1]}] * 3
    a = generate_candidates(bundle, recent, seed=37, count=4)
    b = generate_candidates(bundle, recent, seed=37, count=4)
    assert a == b and len(a) == 4
    assert len({(tuple(c['front']), tuple(c['back'])) for c in a}) == 4
    for c in a: validate_numbers(game, c['front'], c['back'])


def test_laya_score_is_level_score_not_entropy_confidence():
    class Agent:
        def predict(self, state, questions, **kwargs):
            assert len(state['candidates']) == 2
            assert questions['quality_A']['type'] == 'score'
            return {'answers': {'selection': {'choice': 'A'}, 'quality_A': {'score': 1.6, 'confidence': .01}, 'quality_B': {'score': 1.4}}}
    selector = LayaSelector(agent=Agent())
    result = selector.select([{'id': 'A', 'front': [1], 'back': [2]}, {'id': 'B', 'front': [3], 'back': [4]}], {'game': 'ssq'})
    assert result['score'] == 80 and result['candidate']['id'] == 'A'


def test_laya_invalid_choice_or_missing_score_is_a_real_error():
    class Agent:
        def predict(self, *a, **kw): return {'answers': {'selection': {'choice': 'outside'}}}
    with pytest.raises(RuntimeError): LayaSelector(agent=Agent()).select([{'id': 'A'}], {})


def wait_terminal(manager, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = manager.get(job_id)
        if state['status'] in ['complete', 'failed', 'cancelled']: return state
        time.sleep(.01)
    raise AssertionError('job did not finish')


def test_job_progress_and_results_survive_reload_without_duplicate_submission(tmp_path):
    gate = Event()
    def pipeline(game, progress, check):
        progress('history', '正在读取数据'); gate.wait(2)
        progress('prediction', '正在预测'); return {'front': [1, 2], 'back': [3]}
    manager = JobManager(tmp_path, pipeline)
    try:
        first = manager.submit('ssq', 'same-request')
        assert manager.submit('ssq', 'same-request')['id'] == first['id']
        gate.set(); result = wait_terminal(manager, first['id'])
        assert result['status'] == 'complete'
        assert [e['stage'] for e in result['events']] == ['queued', 'history', 'prediction', 'complete']
        reloaded = JobManager(tmp_path, pipeline)
        try: assert reloaded.get(first['id'])['result']['back'] == [3]
        finally: reloaded.close()
    finally: gate.set(); manager.close()


def test_worker_exception_and_cancel_are_terminal(tmp_path):
    def failing(game, progress, check): progress('model', '加载中'); raise RuntimeError('model unavailable')
    manager = JobManager(tmp_path, failing)
    try: assert wait_terminal(manager, manager.submit('ssq', 'failure')['id'])['status'] == 'failed'
    finally: manager.close()
    gate = Event()
    def cancellable(game, progress, check):
        gate.wait(2); progress('model', '加载中'); return {}
    manager = JobManager(tmp_path / 'cancel', cancellable)
    try:
        job = manager.submit('ssq', 'cancel'); manager.cancel(job['id']); gate.set()
        assert wait_terminal(manager, job['id'])['status'] == 'cancelled'
    finally: gate.set(); manager.close()


def test_laya_refuses_a_decision_that_dropped_candidate_context():
    class Agent:
        def predict(self, state, questions, **kwargs):
            return {'answers': {'selection': {'choice': 'A'}, 'quality_A': {'score': 2}},
                    'usage': {'truncated': True, 'state_tokens_dropped': 20}}
    with pytest.raises(RuntimeError, match='截断'):
        LayaSelector(agent=Agent()).select([{'id': 'A', 'front': [1], 'back': [2]}], {})


def test_request_identity_survives_restart_and_cannot_change_game(tmp_path):
    def pipeline(game, progress, check): return {'game': game}
    manager = JobManager(tmp_path, pipeline)
    first = manager.submit('ssq', 'persistent-request')
    wait_terminal(manager, first['id']); manager.close()
    manager = JobManager(tmp_path, pipeline)
    try:
        assert manager.submit('ssq', 'persistent-request')['id'] == first['id']
        with pytest.raises(ValueError, match='彩种'):
            manager.submit('dlt', 'persistent-request')
    finally: manager.close()


def test_cancelled_queued_job_never_enters_the_pipeline(tmp_path):
    gate = Event(); entered = Event(); calls = []
    def pipeline(game, progress, check):
        calls.append(game); entered.set(); gate.wait(2); progress('result', '完成'); return {}
    manager = JobManager(tmp_path, pipeline, limit=2)
    try:
        first = manager.submit('ssq', 'first-request'); assert entered.wait(1)
        second = manager.submit('dlt', 'second-request')
        with pytest.raises(OverflowError): manager.submit('qlc', 'over-limit')
        manager.cancel(second['id']); gate.set()
        assert wait_terminal(manager, first['id'])['status'] == 'complete'
        assert wait_terminal(manager, second['id'])['status'] == 'cancelled'
        assert calls == ['ssq']
    finally: gate.set(); manager.close()
