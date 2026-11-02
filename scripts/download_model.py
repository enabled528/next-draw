"""Prepare pinned public Laya artifacts without requiring host Python dependencies."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import time
from urllib.request import Request, urlopen

REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
ARTIFACTS = {
    "model.safetensors": "9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204",
    "rl_agent_config.json": "25061739243b617ad88d1219ba6f8a9c86c5881ca28df024fa2d9b3b2fcc30c6",
    "encoder/config.json": "83f6916d13ef0f556ac461f28308dc2bffa7ebeadee8ec9e2db5812020ea5bb4",
    "tokenizer/tokenizer_config.json": "6c6b2d8e3c84ce0e671c129cd6b374b235d6f9863042a5836358d00a89bbb5a1",
    "tokenizer/tokenizer.json": "609d8f4c067cd3950f88594c5a802616cea245823836ef5848ee4fc40aab5b6f",
}


def digest(path):
    if not path.is_file(): return None
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(url, path):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'NextDraw/0.1'}), timeout=60) as response, path.open('wb') as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            return
        except OSError:
            if attempt == 2: raise
            time.sleep(attempt + 1)


def prepare_model(target, cache_dir, downloader=download):
    target, cache_dir = Path(target), Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    for name, expected in ARTIFACTS.items():
        destination = target / name
        if digest(destination) == expected: continue
        cached = cache_dir / expected
        if digest(cached) != expected:
            fd, temporary = tempfile.mkstemp(suffix='.part', dir=cache_dir); os.close(fd)
            temporary = Path(temporary)
            try:
                url = f'https://huggingface.co/convaiinnovations/laya/resolve/{REVISION}/multilingual/{name}'
                print(f'Downloading {name}', flush=True)
                downloader(url, temporary)
                if digest(temporary) != expected: raise ValueError(f'SHA-256 mismatch: {name}')
                os.replace(temporary, cached)
            finally: temporary.unlink(missing_ok=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(suffix='.part', dir=destination.parent); os.close(fd)
        try:
            shutil.copyfile(cached, temporary)
            os.replace(temporary, destination)
        finally: Path(temporary).unlink(missing_ok=True)
    print(f'Verified {len(ARTIFACTS)} pinned Laya artifacts in {target}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=Path('vendor/laya'))
    parser.add_argument('--cache-dir', type=Path, default=Path('.cache/laya-downloads'))
    args = parser.parse_args()
    prepare_model(args.target, args.cache_dir)
