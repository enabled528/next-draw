"""Run a real prediction and retain its provenance for verification."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from next_draw.service import PredictionService
from next_draw.history import atomic_json

parser = argparse.ArgumentParser()
parser.add_argument("--game", choices=["ssq", "dlt", "qlc"], default="ssq")
args = parser.parse_args()
service = PredictionService()
result = service.run(args.game, lambda stage, message: print(f"[{stage}] {message}", flush=True))
atomic_json(ROOT / "verification" / f"prediction-{args.game}.json", result)
print(json.dumps({k: result[k] for k in ["game", "front", "back", "score", "attempts", "model_source", "elapsed_seconds"]}, ensure_ascii=False), flush=True)
