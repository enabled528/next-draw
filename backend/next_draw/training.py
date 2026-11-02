from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import random
import tempfile
import time

import torch
from torch import nn

from .models import FrontModel, BackModel
from .rules import GAMES


def make_windows(records, window=3):
    if len(records) <= window: raise ValueError("历史记录不足以构造训练窗口")
    if any(a["draw_date"] >= b["draw_date"] for a, b in zip(records, records[1:])):
        raise ValueError("训练输入日期必须严格早于目标日期")
    front = torch.tensor([r["front"] for r in records], dtype=torch.long) - 1
    back = torch.tensor([r["back"] for r in records], dtype=torch.long) - 1
    return (torch.stack([front[i-window:i] for i in range(window, len(records))]),
            torch.stack([back[i-window:i] for i in range(window, len(records))]),
            front[window:], back[window:])


def set_hits(expected, actual):
    return len(set(expected) & set(actual))


@dataclass(frozen=True)
class ModelConfig:
    window: int = 3
    embedding: int = 32
    hidden: int = 32
    epochs: int = 3
    batch_size: int = 32
    learning_rate: float = .001
    seed: int = 42


@dataclass
class ModelBundle:
    game: str
    front: FrontModel
    back: nn.Module
    config: ModelConfig
    fingerprint: str
    report: dict
    source: str = "trained"


def decode_regions(game, front, back, front_emissions, back_emissions):
    front_values = [[n + 1 for n in row] for row in front.chain.decode(front_emissions, ordered=True)]
    if game == "dlt":
        back_values = [[n + 1 for n in row] for row in back.chain.decode(back_emissions, ordered=True)]
    else:
        logits = back_emissions.clone()
        if game == "qlc":
            for i, values in enumerate(front_values): logits[i, torch.tensor(values) - 1] = -10000
        back_values = [[int(n) + 1] for n in logits.argmax(dim=-1)]
    return front_values, back_values


class Trainer:
    VERSION = 1

    def __init__(self, root, config=None):
        self.root = Path(root); self.config = config or ModelConfig(); self.cache = {}

    @staticmethod
    def fingerprint(snapshot, config):
        rows = [{k: r[k] for k in ["issue", "draw_date", "front", "back"]} for r in snapshot["records"]]
        return hashlib.sha256(json.dumps({"version": Trainer.VERSION, "game": snapshot["game"],
                "records": rows, "config": asdict(config)}, sort_keys=True).encode()).hexdigest()

    def _new(self, game, fingerprint):
        spec = GAMES[game]; cfg = self.config
        front = FrontModel(spec.front_max, spec.front_count, cfg.embedding, cfg.hidden)
        back = FrontModel(spec.back_max, 2, cfg.embedding, cfg.hidden) if game == "dlt" else BackModel(spec.back_max, cfg.embedding, cfg.hidden)
        return ModelBundle(game, front, back, cfg, fingerprint, {})

    def prepare(self, snapshot, on_progress):
        game = snapshot["game"]; fingerprint = self.fingerprint(snapshot, self.config)
        on_progress("model", "正在加载号码模型")
        if fingerprint in self.cache:
            bundle = self.cache[fingerprint]; bundle.source = "memory"; return bundle
        torch.manual_seed(self.config.seed)
        bundle = self._new(game, fingerprint)
        path = self.root / "checkpoints" / f"{game}-{fingerprint[:16]}.pt"
        if path.exists():
            state = torch.load(path, map_location="cpu", weights_only=True)
            if state["fingerprint"] != fingerprint: raise ValueError("模型指纹不匹配")
            bundle.front.load_state_dict(state["front"]); bundle.back.load_state_dict(state["back"])
            bundle.report = state["report"]; bundle.source = "disk"
        else:
            self._train(bundle, snapshot["records"], on_progress)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent); os.close(fd)
            try:
                with open(temporary, "wb") as stream:
                    torch.save({"fingerprint": fingerprint, "config": asdict(self.config),
                                "front": bundle.front.state_dict(), "back": bundle.back.state_dict(), "report": bundle.report}, stream)
                    stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
        bundle.front.eval(); bundle.back.eval()
        self.cache = {key: value for key, value in self.cache.items() if value.game != game}
        self.cache[fingerprint] = bundle
        return bundle

    def _train(self, bundle, records, on_progress):
        started = time.monotonic(); cfg = self.config
        if len(records) < 20: raise ValueError("至少需要20期开奖数据才能训练并留出验证记录")
        front, back, y_front, y_back = make_windows(records, cfg.window)
        split = max(1, int(len(front) * .8))
        parameters = list(bundle.front.parameters()) + list(bundle.back.parameters())
        optimizer = torch.optim.Adam(parameters, lr=cfg.learning_rate, betas=(.9, .999), eps=1e-8)

        def fit(count, epochs, label):
            bundle.front.train(); bundle.back.train()
            batches = math.ceil(count / cfg.batch_size); last_loss = 0.
            for epoch in range(epochs):
                for start in range(0, count, cfg.batch_size):
                    end = min(count, start + cfg.batch_size)
                    if start == 0 or start // cfg.batch_size % 10 == 0 or end == count:
                        on_progress("training", f"{label} · 第 {epoch + 1}/{epochs} 轮 · {end}/{count} 条样本")
                    optimizer.zero_grad()
                    front_emissions = bundle.front(front[start:end])
                    loss = -bundle.front.chain.log_likelihood(front_emissions, y_front[start:end]).mean()
                    if bundle.game == "dlt":
                        loss = loss - bundle.back.chain.log_likelihood(bundle.back(back[start:end]), y_back[start:end]).mean()
                    else:
                        loss = loss + nn.functional.cross_entropy(bundle.back(back[start:end, :, 0]), y_back[start:end, 0])
                    if not torch.isfinite(loss): raise RuntimeError("训练损失出现非有限值")
                    loss.backward(); nn.utils.clip_grad_norm_(parameters, 5.0); optimizer.step()
                    last_loss = float(loss.detach())
            return last_loss

        loss = fit(split, cfg.epochs, "正在训练号码模型")
        on_progress("evaluation", "正在用未参与训练的历史期次检查模型")
        bundle.front.eval(); bundle.back.eval()
        begin = max(split, len(front) - 100)
        with torch.inference_mode():
            front_pred, back_pred = decode_regions(bundle.game, bundle.front, bundle.back,
                bundle.front(front[begin:]), bundle.back(back[begin:]) if bundle.game == "dlt" else bundle.back(back[begin:, :, 0]))
        expected = records[cfg.window + begin:]
        rng = random.Random(cfg.seed); spec = GAMES[bundle.game]
        front_hits = [set_hits(r["front"], p) for r, p in zip(expected, front_pred)]
        back_hits = [set_hits(r["back"], p) for r, p in zip(expected, back_pred)]
        random_front = [set_hits(r["front"], rng.sample(range(1, spec.front_max + 1), spec.front_count)) for r in expected]
        bundle.report = {"holdout_count": len(expected), "evaluation_training_end_issue": records[cfg.window + split - 1]["issue"],
            "holdout_start_issue": expected[0]["issue"], "holdout_end_issue": expected[-1]["issue"],
            "mean_front_hits": sum(front_hits) / len(front_hits), "mean_back_hits": sum(back_hits) / len(back_hits),
            "random_mean_front_hits": sum(random_front) / len(random_front), "training_loss": loss,
            "objective": "per-example CRF NLL plus categorical/CRF back NLL", "epochs": cfg.epochs,
            "refit_through_issue": records[-1]["issue"], "records": len(records)}
        fit(len(front), 1, "正在用全部已知历史完成最终训练")
        bundle.report["training_seconds"] = round(time.monotonic() - started, 3)
