from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from curl_cffi import requests
from filelock import FileLock

from .rules import GAMES, validate_chronology, validate_draw

ZONE = ZoneInfo("Asia/Shanghai")


def now():
    return datetime.now(ZONE).isoformat(timespec="seconds")


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def parse_history(game, html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("tbody", id="tdata") or soup.find("div", class_="chart")
    if table is None: raise ValueError("数据页面缺少开奖表格")
    spec = GAMES[game]; records = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells: continue
        issue = cells[0].get_text(strip=True)
        if not re.fullmatch(r"\d{5,7}", issue): continue
        dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", row.get_text(" ", strip=True))
        if not dates: raise ValueError(f"期号 {issue} 缺少开奖日期")
        if game == "qlc":
            numbers = [int(n) for n in re.findall(r"\d+", cells[1].get_text(" ", strip=True))]
        else:
            numbers = [int(cell.get_text(strip=True)) for cell in cells[1:1 + spec.front_count + spec.back_count]]
        record = {"issue": issue, "draw_date": dates[-1], "front": numbers[:spec.front_count],
                  "back": numbers[spec.front_count:], "retrieved_at": now()}
        validate_draw(game, record); records.append(record)
    if not records: raise ValueError("开奖表格没有有效记录")
    if len({r['issue'] for r in records}) != len(records): raise ValueError("来源存在重复期号")
    return records


class LotterySource:
    def _get(self, url):
        response = requests.get(url, impersonate="chrome116", timeout=20,
                                headers={"Referer": "https://datachart.500.com/"})
        response.raise_for_status()
        return response.content.decode("gb18030", errors="replace")

    def latest(self, game):
        soup = BeautifulSoup(self._get(f"https://datachart.500.com/{game}/history/history.shtml"), "html.parser")
        field = soup.find("input", id="end")
        if field is None or not re.fullmatch(r"\d{5,7}", str(field.get("value", ""))):
            raise ValueError("无法读取来源最新期号")
        return str(field["value"])

    def fetch(self, game, start, end):
        return parse_history(game, self._get(f"https://datachart.500.com/{game}/history/newinc/history.php?start={start}&end={end}"))


class HistoryStore:
    def __init__(self, root, seed_dir=None, source=None, freshness_seconds=21600):
        self.root = Path(root); self.seed_dir = Path(seed_dir) if seed_dir else None
        self.source = source or LotterySource(); self.freshness_seconds = freshness_seconds

    def _path(self, game):
        if game not in GAMES: raise ValueError("不支持的彩种")
        return self.root / "history" / f"{game}.json"

    def load(self, game):
        path = self._path(game)
        if not path.exists() and self.seed_dir and (self.seed_dir / f"{game}.json").exists():
            seed = json.loads((self.seed_dir / f"{game}.json").read_text())
            self.merge(game, seed["records"], checked_at=seed.get("updated_at"))
        if not path.exists(): return None
        snapshot = json.loads(path.read_text())
        if snapshot.get("game") != game or snapshot.get("schema_version") != 1: raise ValueError("历史快照版本不符")
        records = snapshot.get("records", [])
        for record in records: validate_draw(game, record)
        if not records or len({r['issue'] for r in records}) != len(records): raise ValueError("历史快照为空或期号重复")
        if records != sorted(records, key=lambda r: (r["draw_date"], int(r["issue"]))): raise ValueError("历史记录时间顺序不符")
        validate_chronology(records)
        if snapshot.get("record_count") != len(records) or snapshot.get("latest_issue") != records[-1]["issue"]:
            raise ValueError("历史快照元数据与记录不符")
        if snapshot.get("timezone") != "Asia/Shanghai" or datetime.fromisoformat(snapshot["last_checked_at"]).tzinfo is None:
            raise ValueError("历史快照时区不符")
        return snapshot

    def merge(self, game, records, checked_at=None):
        records = deepcopy(records)
        for record in records: validate_draw(game, record)
        if len({r['issue'] for r in records}) != len(records): raise ValueError("更新存在重复期号")
        path = self._path(game); path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(path) + ".lock", timeout=30):
            previous = self.load(game) if path.exists() else {}
            by_id = {r["issue"]: r for r in previous.get("records", [])}
            corrections = list(previous.get("corrections", []))
            for record in records:
                old = by_id.get(record["issue"])
                if old and any(old[k] != record[k] for k in ["draw_date", "front", "back"]):
                    corrections.append({"issue": record["issue"], "observed_at": now(), "previous": old, "replacement": record})
                    record["first_retrieved_at"] = old.get("first_retrieved_at", old["retrieved_at"])
                elif old:
                    record = {**old, "last_verified_at": checked_at or now()}
                by_id[record["issue"]] = record
            ordered = sorted(by_id.values(), key=lambda r: (r["draw_date"], int(r["issue"])))
            if not ordered: raise ValueError("不能保存空历史快照")
            validate_chronology(ordered)
            snapshot = {"schema_version": 1, "game": game, "timezone": "Asia/Shanghai",
                        "source": {"name": "500.com datachart", "url": f"https://datachart.500.com/{game}/history/"},
                        "created_at": previous.get("created_at", now()), "updated_at": now(),
                        "last_checked_at": checked_at or now(), "latest_issue": ordered[-1]["issue"],
                        "record_count": len(ordered), "records": ordered, "corrections": corrections}
            atomic_json(path, snapshot)
            return snapshot

    def sync(self, game, on_progress):
        on_progress("history", "正在检查本地历史数据")
        cached = self.load(game)
        if cached:
            age = (datetime.now(ZONE) - datetime.fromisoformat(cached["last_checked_at"])).total_seconds()
            if age < self.freshness_seconds: return cached, []
        try:
            on_progress("sync", "正在获取新增开奖数据")
            latest = self.source.latest(game)
            records = cached["records"] if cached else []
            start = records[-5]["issue"] if len(records) >= 5 else "1"
            incoming = self.source.fetch(game, start, latest)
            if not any(r["issue"] == latest for r in incoming): raise ValueError("来源最新期号没有出现在返回记录中")
            return self.merge(game, incoming), []
        except Exception as exc:
            if cached:
                return cached, [f"来源暂不可用，使用缓存（截至 {cached['records'][-1]['draw_date']}）；{type(exc).__name__}"]
            raise RuntimeError("首次同步失败，且没有可用的本地历史数据") from exc
