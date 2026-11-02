from types import SimpleNamespace

import pytest

from next_draw.service import PredictionService


@pytest.mark.parametrize('scores, rounds, expected', [([60, 40, 55], 3, 60), ([80, 90], 1, 80), ([60, 85, 90], 2, 85)])
def test_round_budget_keeps_the_best_without_fabricating_a_threshold(scores, rounds, expected, monkeypatch):
    record = {'front': [1, 2, 3, 4, 5, 6], 'back': [7], 'draw_date': '2026-11-01'}
    candidate = {'id': 'A', 'front': record['front'], 'back': record['back'],
                 'features': {'odd_count': 3, 'low_count': 4, 'last_draw_overlap': 0, 'consecutive_pairs': 2}}
    monkeypatch.setattr('next_draw.service.generate_candidates', lambda *a, **kw: [candidate.copy()])
    snapshot = {'records': [record], 'record_count': 1, 'latest_issue': '26125'}
    service = object.__new__(PredictionService)
    service.history = SimpleNamespace(sync=lambda *a: (snapshot, []))
    service.trainer = SimpleNamespace(prepare=lambda *a: SimpleNamespace(fingerprint='test', source='memory', report={}))
    iterator = iter(scores)
    service.selector = SimpleNamespace(load=lambda *a: None,
        select=lambda candidates, context: {'candidate': candidates[0], 'score': next(iterator), 'engine': 'test'})
    result = service.run('ssq', lambda *a: None)
    assert result['attempts'] == rounds
    assert result['score'] == expected
    assert result['threshold_met'] == (expected >= 75)
    assert len(result['selection_provenance']) == rounds
