import hashlib
import os

import pytest

import backend.settings as settings


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def test_model_fetch_and_validation_use_declared_checksum(tmp_path, monkeypatch):
    source_data = b'verified model package'
    source = tmp_path / 'source.pt.zip'
    source.write_bytes(source_data)
    models = tmp_path / 'models'
    manifest = {
        'detection/model.pt.zip': {
            'url': source.as_uri(),
            'sha256': sha256(source_data),
        }
    }
    monkeypatch.setattr(settings, 'get_models_path', lambda: str(models))
    monkeypatch.setattr(settings, 'parse_pretrained_models_file', lambda: manifest)

    with pytest.raises(RuntimeError, match='missing'):
        settings.validate_pretrained_models()

    settings.ensure_pretrained_models()
    destination = models / 'detection' / 'model.pt.zip'
    assert destination.read_bytes() == source_data
    assert not os.path.exists(str(destination) + '.download')
    settings.validate_pretrained_models()

    destination.write_bytes(b'corrupt')
    with pytest.raises(RuntimeError, match='checksum mismatch'):
        settings.validate_pretrained_models()
    settings.ensure_pretrained_models()
    assert destination.read_bytes() == source_data
    settings.validate_pretrained_models()
