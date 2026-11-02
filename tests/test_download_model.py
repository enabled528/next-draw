import hashlib

import pytest


def test_download_validates_cache_and_reuses_existing_model(tmp_path, monkeypatch):
    from scripts import download_model as model
    content = b'fixture public model'
    monkeypatch.setattr(model, 'ARTIFACTS', {'model.safetensors': hashlib.sha256(content).hexdigest()})
    calls = []
    def download(url, path): calls.append(url); path.write_bytes(content)
    target, cache = tmp_path / 'model', tmp_path / 'cache'
    model.prepare_model(target, cache, download)
    assert (target / 'model.safetensors').read_bytes() == content
    model.prepare_model(target, cache, lambda *a: pytest.fail('valid model must not download again'))
    (target / 'model.safetensors').unlink()
    model.prepare_model(target, cache, lambda *a: pytest.fail('valid cache must be reused'))
    assert len(calls) == 1 and model.REVISION in calls[0]


def test_bad_download_does_not_replace_existing_model(tmp_path, monkeypatch):
    from scripts import download_model as model
    monkeypatch.setattr(model, 'ARTIFACTS', {'model.safetensors': hashlib.sha256(b'expected').hexdigest()})
    target = tmp_path / 'model'; target.mkdir()
    (target / 'model.safetensors').write_bytes(b'old')
    with pytest.raises(ValueError, match='SHA-256'):
        model.prepare_model(target, tmp_path / 'cache', lambda url, path: path.write_bytes(b'corrupt'))
    assert (target / 'model.safetensors').read_bytes() == b'old'
    assert not list((tmp_path / 'cache').glob('*.part'))
