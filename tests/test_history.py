from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from next_draw.history import HistoryStore, parse_history
from next_draw.rules import validate_draw


def draw(issue="26001", date="2026-01-01", front=None, back=None):
    return {"issue": issue, "draw_date": date, "front": front or [1, 2, 3, 4, 5, 6],
            "back": back or [7], "retrieved_at": "2026-01-01T12:00:00+08:00"}


@pytest.mark.parametrize("bad", [
    {"front": [1, 1, 3, 4, 5, 6]}, {"front": [0, 2, 3, 4, 5, 6]},
    {"front": [1, 2, 3, 4, 5]}, {"back": [17]}, {"front": [True, 2, 3, 4, 5, 6]},
    {"draw_date": "2026-02-30"}, {"retrieved_at": "2026-01-01T12:00:00"},
])
def test_invalid_draw_is_rejected(bad):
    record = draw(); record.update(bad)
    with pytest.raises(ValueError): validate_draw("ssq", record)


def test_valid_cross_region_duplicate_is_allowed_for_ssq():
    assert validate_draw("ssq", draw(back=[1]))["issue"] == "26001"


def test_qlc_special_number_cannot_repeat_regular_number():
    with pytest.raises(ValueError): validate_draw("qlc", draw(front=[1, 2, 3, 4, 5, 6, 7], back=[7]))


def test_history_merge_corrects_with_provenance_and_is_idempotent(tmp_path):
    store = HistoryStore(tmp_path, seed_dir=tmp_path / "seed")
    store.merge("ssq", [draw("03001", "2003-02-23"), draw()])
    changed = draw(back=[8])
    snapshot = store.merge("ssq", [changed, draw("26002", "2026-01-03")])
    assert [r["issue"] for r in snapshot["records"]] == ["03001", "26001", "26002"]
    assert snapshot["records"][1]["back"] == [8]
    assert len(snapshot["corrections"]) == 1
    assert snapshot["corrections"][0]["previous"]["back"] == [7]
    assert len(store.merge("ssq", [changed])["corrections"]) == 1


def test_bad_update_does_not_change_previous_snapshot(tmp_path):
    store = HistoryStore(tmp_path)
    store.merge("ssq", [draw()])
    path = tmp_path / "history/ssq.json"; before = path.read_bytes()
    bad = draw("26002", "2026-01-03", back=[99])
    with pytest.raises(ValueError): store.merge("ssq", [bad])
    assert path.read_bytes() == before


def test_replace_failure_preserves_previous_snapshot(tmp_path, monkeypatch):
    store = HistoryStore(tmp_path); store.merge("ssq", [draw()])
    before = (tmp_path / "history/ssq.json").read_bytes()
    monkeypatch.setattr("next_draw.history.os.replace", lambda *a: (_ for _ in ()).throw(OSError("disk failure")))
    with pytest.raises(OSError): store.merge("ssq", [draw("26002", "2026-01-03")])
    assert (tmp_path / "history/ssq.json").read_bytes() == before


def test_sync_requests_overlap_and_keeps_cache_when_source_fails(tmp_path):
    class Source:
        def latest(self, game): return "26010"
        def fetch(self, game, start, end):
            assert (game, start, end) == ("ssq", "26002", "26010")
            raise TimeoutError("source unavailable")
    store = HistoryStore(tmp_path, source=Source(), freshness_seconds=0)
    store.merge("ssq", [draw(f"2600{i}", f"2026-01-0{i}") for i in range(1, 7)])
    snapshot, warnings = store.sync("ssq", lambda *a: None)
    assert snapshot["record_count"] == 6
    assert warnings and "缓存" in warnings[0]


def test_fresh_history_needs_no_network(tmp_path):
    class Source:
        def latest(self, game): raise AssertionError("must not fetch a fresh snapshot")
    store = HistoryStore(tmp_path, source=Source(), freshness_seconds=3600)
    store.merge("ssq", [draw()])
    snapshot, warnings = store.sync("ssq", lambda *a: None)
    assert snapshot["latest_issue"] == "26001" and warnings == []


def test_parser_keeps_dates_and_rejects_html_without_draw_table():
    html = '<table><tbody id="tdata"><tr>' + ''.join(f'<td>{v}</td>' for v in ['03001',1,2,3,4,5,6,7,'2003-02-23']) + '</tr></tbody></table>'
    records = parse_history("ssq", html)
    assert records[0]["issue"] == "03001" and records[0]["draw_date"] == "2003-02-23"
    with pytest.raises(ValueError): parse_history("ssq", '<html>temporarily unavailable</html>')


def test_snapshot_metadata_and_chronology_are_validated(tmp_path):
    store = HistoryStore(tmp_path)
    snapshot = store.merge('ssq', [draw(), draw('26002', '2026-01-03')])
    snapshot['records'].reverse()
    (tmp_path / 'history/ssq.json').write_text(json.dumps(snapshot))
    with pytest.raises(ValueError): store.load('ssq')


def test_duplicate_incoming_issue_preserves_snapshot(tmp_path):
    store = HistoryStore(tmp_path); store.merge('ssq', [draw()])
    path = tmp_path / 'history/ssq.json'; before = path.read_bytes()
    with pytest.raises(ValueError): store.merge('ssq', [draw('26002'), draw('26002', back=[8])])
    assert path.read_bytes() == before


@pytest.mark.parametrize('date', ['2099-01-01', '2026-01-01', '2025-12-31'])
def test_temporally_invalid_update_preserves_the_valid_snapshot(tmp_path, date):
    store = HistoryStore(tmp_path); store.merge('ssq', [draw()])
    path = tmp_path / 'history/ssq.json'; before = path.read_bytes()
    with pytest.raises(ValueError): store.merge('ssq', [draw('26002', date)])
    assert path.read_bytes() == before
