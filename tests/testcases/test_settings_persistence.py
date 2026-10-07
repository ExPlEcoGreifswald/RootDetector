import json
import os

import backend.settings
from backend.app import App


def test_partial_settings_save_preserves_models_across_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('ROOT_PATH', os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setattr(backend.settings, 'ensure_pretrained_models', lambda: None)

    model_names = {
        'detection': ['detection-a', 'detection-b'],
        'exclusion_mask': ['mask-a'],
        'tracking': ['tracking-a'],
    }
    monkeypatch.setattr(
        backend.settings.Settings,
        'get_available_models',
        classmethod(lambda _cls, with_properties=False: model_names),
    )
    monkeypatch.setattr(
        backend.settings.Settings,
        'load_model',
        classmethod(lambda _cls, modeltype, modelname: (modeltype, modelname)),
    )

    app = App()
    app.testing = True
    headers = {
        'Host': 'localhost',
        'Origin': 'http://localhost',
        'X-RootDetector-Token': app.session_token,
    }
    response = app.test_client().post(
        '/settings',
        json={'active_models': {'detection': 'detection-b'}, 'use_gpu': True},
        headers=headers,
    )
    assert response.status_code == 200
    saved = json.loads((tmp_path / 'settings.json').read_text())
    assert saved['active_models'] == {
        'detection': 'detection-b',
        'exclusion_mask': 'mask-a',
        'tracking': 'tracking-a',
    }
    assert saved['use_gpu'] is True
    assert 'tracking_exclusion_policy' not in saved

    restarted = App()
    restarted.testing = True
    settings = restarted.test_client().get('/settings', headers={'Host': 'localhost'}).get_json()['settings']
    assert settings['active_models'] == saved['active_models']
    assert settings['use_gpu'] is True

    # A previously damaged file must also be recoverable through the API.
    (tmp_path / 'settings.json').write_text(json.dumps({
        'active_models': {'detection': 'detection-b'},
    }))
    damaged_restart = App()
    damaged_restart.testing = True
    repaired = damaged_restart.test_client().get(
        '/settings', headers={'Host': 'localhost'}
    ).get_json()['settings']
    assert repaired['active_models'] == saved['active_models']
    repair_headers = dict(headers, **{'X-RootDetector-Token': damaged_restart.session_token})
    response = damaged_restart.test_client().post(
        '/settings',
        json={'active_models': repaired['active_models']},
        headers=repair_headers,
    )
    assert response.status_code == 200
    assert json.loads((tmp_path / 'settings.json').read_text())['active_models'] == saved['active_models']
