import itertools
import math

import pytest
import torch

from next_draw.models import FrontModel, BackModel, LinearChain, RecurrentDropLSTM
from next_draw.training import make_windows, set_hits, Trainer, ModelConfig
from next_draw.rules import validate_draw


def test_crf_likelihood_and_decode_match_hand_enumerated_paths():
    crf = LinearChain(2)
    with torch.no_grad(): crf.crf.transitions.copy_(torch.tensor([[0., .2], [-.1, .3]]))
    emissions = torch.tensor([[[.1, .4], [.8, -.2]]])
    scores = [.9, .1, 1.1, .5]
    expected = 1.1 - math.log(sum(math.exp(x) for x in scores))
    assert crf.log_likelihood(emissions, torch.tensor([[1, 0]])).item() == pytest.approx(expected, abs=1e-6)
    assert crf.decode(emissions) == [[1, 0]]
    assert torch.count_nonzero(crf.crf.start_transitions) == 0
    assert not crf.crf.start_transitions.requires_grad


def test_constrained_decoding_returns_distinct_ascending_numbers_without_mutating_training_transitions():
    crf = LinearChain(4); before = crf.crf.transitions.detach().clone()
    result = crf.decode(torch.zeros(3, 3, 4), ordered=True)
    assert all(len(set(r)) == 3 and r == sorted(r) for r in result)
    assert torch.equal(crf.crf.transitions.detach(), before)


def test_model_shapes_and_gradients_are_real():
    model = FrontModel(33, 6, embedding=8, hidden=8)
    emissions = model(torch.randint(0, 33, (4, 3, 6)))
    assert emissions.shape == (4, 6, 33)
    loss = -model.chain.log_likelihood(emissions, torch.randint(0, 33, (4, 6))).sum()
    loss.backward()
    assert torch.isfinite(loss)
    assert model.embedding.weight.grad.abs().sum() > 0
    assert len(model.temporal) == 6


def test_recurrent_dropout_is_disabled_in_eval_and_bias_matches_forget_gate():
    layer = RecurrentDropLSTM(3, 4, dropout=.2)
    values = torch.randn(2, 3, 3)
    layer.eval()
    assert torch.equal(layer(values), layer(values))
    assert torch.equal(layer.bias[4:8], torch.ones(4))
    layer.train(); torch.manual_seed(1); first = layer(values)
    torch.manual_seed(2); second = layer(values)
    assert not torch.equal(first, second)


def test_back_model_outputs_logits_not_class_ids():
    model = BackModel(16, embedding=8, hidden=8)
    output = model(torch.randint(0, 16, (3, 3)))
    assert output.shape == (3, 16)
    torch.nn.functional.cross_entropy(output, torch.tensor([0, 3, 15])).backward()
    assert torch.isfinite(model.output.weight.grad).all()


def test_time_windows_never_contain_the_target_or_future_draw():
    records = [{"issue": str(i), "draw_date": f"2026-01-{i:02d}", "front": [i, i+1], "back": [i]} for i in range(1, 7)]
    front, back, y_front, y_back = make_windows(records, window=3)
    assert front.shape == (3, 3, 2)
    assert front[0].tolist() == [[0, 1], [1, 2], [2, 3]]
    assert y_front[0].tolist() == [3, 4]
    assert y_back[-1].tolist() == [5]


def test_hit_count_is_set_based_not_position_or_one_hot_comparison():
    assert set_hits([1, 2, 3, 4, 5, 6], [2, 3, 4, 5, 6, 7]) == 5
    assert set_hits([6], [1]) == 0


def test_training_windows_reject_equal_or_reversed_target_dates():
    records = [{'draw_date': '2026-01-01', 'front': [1], 'back': [2]}] * 5
    with pytest.raises(ValueError): make_windows(records)


def test_custom_recurrence_matches_pytorch_lstm_when_dropout_is_off():
    custom = RecurrentDropLSTM(3, 4, dropout=0).eval()
    reference = torch.nn.LSTM(3, 4, batch_first=True).eval()
    with torch.no_grad():
        reference.weight_ih_l0.copy_(custom.kernel)
        reference.weight_hh_l0.copy_(custom.recurrent)
        reference.bias_ih_l0.copy_(custom.bias); reference.bias_hh_l0.zero_()
    values = torch.randn(2, 5, 3)
    torch.testing.assert_close(custom(values), reference(values)[0][:, -1], rtol=1e-5, atol=1e-6)


def test_training_checkpoint_reuses_only_matching_data_and_preserves_causal_report(tmp_path):
    from datetime import date, timedelta
    torch.set_num_threads(2)
    records = [{"issue": f"26{i+1:03d}", "draw_date": str(date(2026, 1, 1) + timedelta(days=i)),
                "front": [1, 3, 6, 11, 18, 25], "back": [i % 16 + 1]} for i in range(36)]
    snapshot = {"game": "ssq", "latest_issue": "26036", "records": records}
    config = ModelConfig(embedding=4, hidden=4, epochs=1, batch_size=8)
    trainer = Trainer(tmp_path, config)
    bundle = trainer.prepare(snapshot, lambda *a: None)
    assert bundle.source == "trained"
    assert bundle.report["evaluation_training_end_issue"] < bundle.report["holdout_start_issue"]
    assert bundle.report["refit_through_issue"] == "26036"
    assert trainer.prepare(snapshot, lambda *a: None).source == "memory"
    restored = Trainer(tmp_path, config).prepare(snapshot, lambda *a: None)
    assert restored.source == "disk"
    with torch.inference_mode():
        x = torch.ones(1, 3, 6, dtype=torch.long)
        torch.testing.assert_close(bundle.front(x), restored.front(x))
    changed = {**snapshot, "records": [*records]}
    changed["records"][-1] = {**records[-1], "back": [16]}
    assert Trainer.fingerprint(changed, config) != bundle.fingerprint
