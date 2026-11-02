import os
from pathlib import Path
import secrets
import time

import torch

from .candidates import generate_candidates
from .history import HistoryStore, now
from .rules import GAMES, validate_numbers
from .selector import LayaSelector
from .training import ModelConfig, Trainer

ROOT = Path(__file__).resolve().parents[2]


class PredictionService:
    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir or os.environ.get("NEXT_DRAW_DATA", ROOT / ".data"))
        self.history = HistoryStore(self.data_dir, seed_dir=ROOT / "seed",
            freshness_seconds=int(os.environ.get("NEXT_DRAW_FRESHNESS_SECONDS", "21600")))
        self.trainer = Trainer(self.data_dir, ModelConfig(epochs=int(os.environ.get("NEXT_DRAW_EPOCHS", "3"))))
        self.selector = LayaSelector(os.environ.get("NEXT_DRAW_LAYA_DIR", str(ROOT / "vendor/laya")))
        torch.set_num_threads(max(1, min(4, int(os.environ.get("NEXT_DRAW_THREADS", "4")))))

    def games(self):
        result = []
        for game, spec in GAMES.items():
            snapshot = self.history.load(game)
            result.append({"id": game, "name": spec.name, "enabled": True,
                "front_count": spec.front_count, "back_count": spec.back_count,
                "latest_issue": snapshot["latest_issue"] if snapshot else None,
                "data_date": snapshot["records"][-1]["draw_date"] if snapshot else None,
                "records": snapshot["record_count"] if snapshot else 0})
        result.append({"id": "qxc", "name": "七星彩", "enabled": False, "reason": "数据来源与模型尚未验证"})
        return result

    def run(self, game, progress):
        started = time.monotonic()
        snapshot, warnings = self.history.sync(game, progress)
        bundle = self.trainer.prepare(snapshot, progress)
        provenance = []; best = None
        for attempt in range(1, 4):
            progress("prediction", f"正在预测候选号码 · 第 {attempt} 轮")
            seed = secrets.randbelow(2**31)
            candidates = generate_candidates(bundle, snapshot["records"][-30:], seed=seed, count=4)
            for candidate in candidates:
                features = candidate["features"]; size = GAMES[game].front_count
                candidate["preference_summary"] = (f"奇{features['odd_count']}偶{size-features['odd_count']}，"
                    f"小{features['low_count']}大{size-features['low_count']}，与上期重合{features['last_draw_overlap']}，"
                    f"连号对数{features['consecutive_pairs']}")
            self.selector.load(progress)
            progress("laya", f"Laya 正在比较候选 · 第 {attempt} 轮")
            decision = self.selector.select(candidates, {"game": GAMES[game].name, "front_count": GAMES[game].front_count,
                "history_count": snapshot["record_count"], "data_date": snapshot["records"][-1]["draw_date"]})
            provenance.append({"attempt": attempt, "seed": seed, "candidates": candidates, "decision": decision})
            if best is None or decision["score"] > best["score"]: best = decision
            if decision["score"] >= 75: break
        progress("result", "正在整理本次结果")
        candidate = best["candidate"]
        validate_numbers(game, candidate["front"], candidate["back"])
        return {"game": game, "game_name": GAMES[game].name, "front": candidate["front"], "back": candidate["back"],
            "score": best["score"], "score_label": "Laya 实验评分", "threshold": 75,
            "threshold_met": best["score"] >= 75, "attempts": len(provenance),
            "candidates_compared": sum(len(p["candidates"]) for p in provenance),
            "engine": best["engine"], "model_fingerprint": bundle.fingerprint,
            "model_source": bundle.source, "model_report": bundle.report,
            "latest_issue": snapshot["latest_issue"], "data_date": snapshot["records"][-1]["draw_date"],
            "history_count": snapshot["record_count"], "created_at": now(), "warnings": warnings,
            "elapsed_seconds": round(time.monotonic() - started, 3), "selection_provenance": provenance}
