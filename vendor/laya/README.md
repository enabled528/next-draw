# Local Model Artifacts

Large weights and tokenizer/config artifacts are not committed to Git.

Docker prepares the five SHA-256-pinned files automatically at build time.
For local development, run from the repository root:

```sh
python3.11 scripts/download_model.py
```

Source: <https://huggingface.co/convaiinnovations/laya/tree/55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851/multilingual>.
Upstream model and tokenizer terms apply; the project license does not relicense them.
