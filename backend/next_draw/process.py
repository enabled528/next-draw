import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from threading import Thread


class ProcessPipeline:
    """Keep warm models in one child, but supervise deadlines outside that child."""
    def __init__(self, data_dir, command=None):
        self.data_dir = Path(data_dir)
        self.command = command or [sys.executable, "-u", "-m", "next_draw.worker"]
        self.process = None
        self.reader = None

    def _start(self):
        if self.process is not None and self.process.poll() is None: return
        self.close()
        environment = {**os.environ, "NEXT_DRAW_DATA": str(self.data_dir),
                       "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        text=True, encoding="utf-8", bufsize=1, env=environment)
        self.messages = Queue()
        stream, messages = self.process.stdout, self.messages
        def read():
            try:
                for line in stream: messages.put(json.loads(line))
            except (ValueError, OSError) as exc:
                messages.put({"kind": "error", "error": f"模型进程通信失败: {exc}"})
            finally: messages.put({"kind": "exit"})
        self.reader = Thread(target=read, name="model-events", daemon=True)
        self.reader.start()

    def __call__(self, game, progress, check):
        try:
            check(); self._start()
            self.process.stdin.write(json.dumps({"game": game}) + "\n"); self.process.stdin.flush()
            while True:
                check()
                try: message = self.messages.get(timeout=.05)
                except Empty: continue
                if message["kind"] == "progress": progress(message["stage"], message["message"])
                elif message["kind"] == "result": return message["result"]
                elif message["kind"] == "error": raise RuntimeError(message["error"])
                else: raise RuntimeError("模型进程已退出，请重试")
        except BaseException:
            self.close()
            raise

    def close(self):
        process = self.process
        if process is None: return
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=1)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=2)
        process.stdin.close(); process.stdout.close()
        if self.reader: self.reader.join(timeout=1)
        self.process = None; self.reader = None
