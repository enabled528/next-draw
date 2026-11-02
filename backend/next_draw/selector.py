import math
from pathlib import Path


WEIGHT_SHA = "9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204"
MODEL_REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"


class LayaSelector:
    def __init__(self, model_dir=None, agent=None):
        self.model_dir = Path(model_dir) if model_dir else None
        self.agent = agent

    def load(self, on_progress):
        if self.agent is None:
            on_progress("laya_loading", "正在加载 Laya 决策模型")
            if self.model_dir is None or not (self.model_dir / "model.safetensors").exists():
                raise RuntimeError("本地 Laya 权重尚未准备，请执行模型准备命令")
            import laya
            self.agent = laya.load(str(self.model_dir), device="cpu", expected_sha256={"model.safetensors": WEIGHT_SHA})

    def select(self, candidates, context):
        if self.agent is None: raise RuntimeError("Laya 尚未加载")
        options = {c["id"]: f"候选 {c['id']}" for c in candidates}
        compact = [{key: c[key] for key in ("id", "front", "back", "preference_summary", "features") if key in c} for c in candidates]
        state = {"context": context, "candidates": compact}
        instructions = "偏好奇偶与大小均衡、上期重号少、连号少；数字已校验合法。评分仅为偏好匹配度，不是中奖率。"
        questions = {"selection": {"type": "choice", "instructions": instructions + "选择最符合偏好的候选。", "criteria": options}}
        for candidate in candidates:
            questions[f"quality_{candidate['id']}"] = {"type": "score", "instructions": instructions + f"给候选 {candidate['id']} 评分。",
                "criteria": ["明显不符合上述偏好，多项特征极端", "部分符合偏好，但仍有偏向或集中", "整体符合偏好，分布较均衡"]}
        try:
            prediction = self.agent.predict(state, questions, max_len=1024)
            usage = prediction.get("usage", {})
            if usage.get("truncated"):
                raise RuntimeError("Laya 输入发生截断，不能据此选择候选")
            answers = prediction["answers"]
            selected = answers["selection"]["choice"]
            candidate = next(c for c in candidates if c["id"] == selected)
            level = float(answers[f"quality_{selected}"]["score"])
            if not math.isfinite(level) or not 0 <= level <= 2: raise ValueError("invalid score")
        except (KeyError, StopIteration, TypeError, ValueError) as exc:
            raise RuntimeError("Laya 没有返回有效的候选和实验评分") from exc
        return {"candidate": candidate, "score": round(level * 50, 2), "answers": answers, "usage": usage,
                "engine": "laya-0.4.21-multilingual", "revision": MODEL_REVISION}
