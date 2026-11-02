from contextlib import redirect_stdout
import json
import sys


def main():
    output = sys.stdout
    def emit(message):
        output.write(json.dumps(message, ensure_ascii=False, allow_nan=False) + "\n"); output.flush()
    # Library diagnostics must not corrupt the line-delimited job protocol.
    with redirect_stdout(sys.stderr):
        from .service import PredictionService
        service = PredictionService()
        for line in sys.stdin:
            try:
                game = json.loads(line)["game"]
                result = service.run(game, lambda stage, message: emit({"kind": "progress", "stage": stage, "message": message}))
                emit({"kind": "result", "result": result})
            except Exception as exc:
                emit({"kind": "error", "error": str(exc)[:400]})


if __name__ == "__main__": main()
