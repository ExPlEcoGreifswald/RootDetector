import os
import threading
import io
import json
import zipfile

import PIL.Image

from backend.app import App


class FakeSettings:
    active_models = {'detection': 'fake-detection', 'tracking': 'fake-tracking'}
    models = {}
    use_gpu = False
    exmask_enabled = False
    too_many_roots = 100000

    def get_settings_as_dict(self):
        return {'settings': {}, 'available_models': {}}


def detection_result(path):
    basename = os.path.basename(path)
    return {
        'segmentation': basename + '.segmentation.png',
        'skeleton': basename + '.skeleton.png',
        'statistics': {'sum': 1},
    }


def request_headers(app):
    return {
        'Host': 'localhost',
        'Origin': 'http://localhost',
        'X-RootDetector-Token': app.session_token,
    }


def png_bytes(color=0):
    output = io.BytesIO()
    PIL.Image.new('RGB', (8, 8), color=(color, color, color)).save(output, format='PNG')
    return output.getvalue()


def test_pipeline_api_reports_validation_busy_completion_and_missing_run(tmp_path, monkeypatch):
    monkeypatch.setenv('ROOT_PATH', os.getcwd())
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setattr('backend.settings.ensure_pretrained_models', lambda: None)
    monkeypatch.setattr('backend.settings.Settings', FakeSettings)

    app = App()
    app.testing = True
    started = threading.Event()
    release = threading.Event()

    def detect(path, _settings):
        started.set()
        release.wait(5)
        return detection_result(path)

    app.pipeline_manager.detection_func = detect
    filename = 'input.png'
    with open(os.path.join(app.cache_path, filename), 'wb') as output:
        output.write(b'fixture')

    client = app.test_client()
    headers = request_headers(app)
    invalid = client.post('/api/pipeline/runs', json={'filenames': ['../input.png']}, headers=headers)
    assert invalid.status_code == 400
    assert invalid.get_json()['code'] == 'invalid_pipeline_request'

    wrong_shape = client.post('/api/pipeline/runs', json={'filenames': filename}, headers=headers)
    assert wrong_shape.status_code == 400
    assert wrong_shape.get_json()['code'] == 'invalid_pipeline_request'

    created = client.post(
        '/api/pipeline/runs',
        json={'filenames': [filename], 'file_pairs': []},
        headers=headers,
    )
    assert created.status_code == 202
    run_id = created.get_json()['id']
    assert started.wait(2)

    busy = client.post(
        '/api/pipeline/runs',
        json={'filenames': [filename], 'file_pairs': []},
        headers=headers,
    )
    assert busy.status_code == 409
    assert busy.get_json()['code'] == 'pipeline_busy'

    release.set()
    assert app.pipeline_manager.get(run_id).wait(5)
    completed = client.get('/api/pipeline/runs/' + run_id)
    assert completed.status_code == 200
    assert completed.get_json()['state'] == 'completed'

    missing = client.get('/api/pipeline/runs/not-a-run')
    assert missing.status_code == 404
    assert missing.get_json()['code'] == 'pipeline_not_found'


def test_local_request_protection_and_security_headers(tmp_path, monkeypatch):
    monkeypatch.setenv('ROOT_PATH', os.getcwd())
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setattr('backend.settings.ensure_pretrained_models', lambda: None)
    monkeypatch.setattr('backend.settings.Settings', FakeSettings)

    app = App()
    app.testing = True
    client = app.test_client()

    session = client.get('/api/session', headers={'Host': 'localhost'})
    assert session.status_code == 200
    assert session.get_json()['token'] == app.session_token
    assert session.get_json()['asset_schema'] == 'rootdetector-web-rc2-1'
    assert session.headers['X-Content-Type-Options'] == 'nosniff'
    assert session.headers['X-Frame-Options'] == 'DENY'
    assert "frame-ancestors 'none'" in session.headers['Content-Security-Policy']

    invalid_host = client.get('/api/session', headers={'Host': 'rootdetector.example'})
    assert invalid_host.status_code == 403
    assert invalid_host.get_json()['code'] == 'invalid_host'

    invalid_origin = client.post(
        '/clear_cache',
        headers={
            'Host': 'localhost',
            'Origin': 'https://attacker.example',
            'X-RootDetector-Token': app.session_token,
        },
    )
    assert invalid_origin.status_code == 403
    assert invalid_origin.get_json()['code'] == 'invalid_origin'

    missing_token = client.post('/clear_cache', headers={'Host': 'localhost'})
    assert missing_token.status_code == 403
    assert missing_token.get_json()['code'] == 'invalid_session_token'

    legacy_get = client.get('/clear_cache', headers={'Host': 'localhost'})
    assert legacy_get.status_code == 405
    assert legacy_get.get_json()['code'] == 'method_not_allowed'

    cleared = client.post('/clear_cache', headers=request_headers(app))
    assert cleared.status_code == 200
    assert cleared.get_json() == {'cleared': True}


def test_diagnostics_download_excludes_research_data(tmp_path, monkeypatch):
    monkeypatch.setenv('ROOT_PATH', os.getcwd())
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setattr('backend.settings.ensure_pretrained_models', lambda: None)
    monkeypatch.setattr('backend.settings.Settings', FakeSettings)

    app = App()
    app.testing = True
    with open(os.path.join(app.cache_path, 'private-input.png'), 'wb') as output:
        output.write(png_bytes())

    client = app.test_client()
    reported = client.post(
        '/api/diagnostics/client',
        json={
            'stage': 'manual_detection',
            'item_id': 'example.tiff',
            'message': 'Result fetch was interrupted.',
            'error_type': 'TypeError',
            'status': 0,
        },
        headers=request_headers(app),
    )
    assert reported.status_code == 202
    assert len(reported.get_json()['diagnostic_id']) == 12

    response = client.get('/api/diagnostics', headers={'Host': 'localhost'})
    assert response.status_code == 200
    assert response.mimetype == 'application/zip'
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        names = archive.namelist()
        assert 'diagnostics.json' in names
        assert 'logs/rootdetector.log' in names
        assert all('private-input.png' not in name for name in names)
        snapshot = json.loads(archive.read('diagnostics.json'))
        log_text = archive.read('logs/rootdetector.log').decode('utf-8')
    assert 'environment' not in snapshot
    assert str(tmp_path) not in json.dumps(snapshot)
    assert 'Browser manual_detection failed for example.tiff' in log_text
    assert 'Result fetch was interrupted.' in log_text


def test_upload_validation_rejects_paths_corruption_and_name_conflicts(tmp_path, monkeypatch):
    monkeypatch.setenv('ROOT_PATH', os.getcwd())
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setattr('backend.settings.ensure_pretrained_models', lambda: None)
    monkeypatch.setattr('backend.settings.Settings', FakeSettings)

    app = App()
    app.testing = True
    client = app.test_client()
    headers = request_headers(app)

    traversal = client.post(
        '/file_upload',
        data={'files': (io.BytesIO(png_bytes()), '../outside.png')},
        headers=headers,
    )
    assert traversal.status_code == 400
    assert traversal.get_json()['code'] == 'invalid_filename'
    assert not os.path.exists(os.path.join(str(tmp_path), 'outside.png'))

    corrupt = client.post(
        '/file_upload',
        data={'files': (io.BytesIO(b'not an image'), 'corrupt.png')},
        headers=headers,
    )
    assert corrupt.status_code == 415
    assert corrupt.get_json()['code'] == 'invalid_image'
    assert not os.path.exists(os.path.join(app.cache_path, 'corrupt.png'))

    first = client.post(
        '/file_upload',
        data={'files': (io.BytesIO(png_bytes(0)), 'input.png')},
        headers=headers,
    )
    assert first.status_code == 200
    assert first.get_json()['files'][0]['reused'] is False

    repeated = client.post(
        '/file_upload',
        data={'files': (io.BytesIO(png_bytes(0)), 'input.png')},
        headers=headers,
    )
    assert repeated.status_code == 200
    assert repeated.get_json()['files'][0]['reused'] is True

    conflict = client.post(
        '/file_upload',
        data={'files': (io.BytesIO(png_bytes(255)), 'input.png')},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.get_json()['code'] == 'filename_conflict'
    assert open(os.path.join(app.cache_path, 'input.png'), 'rb').read() == png_bytes(0)

    encoded_traversal = client.post(
        '/process_image/..%5Cinput.png',
        headers=headers,
    )
    assert encoded_traversal.status_code == 400
    assert encoded_traversal.get_json()['code'] == 'invalid_filename'

    downloaded = client.get('/images/input.png', headers={'Host': 'localhost'})
    assert downloaded.status_code == 200
    assert downloaded.data == png_bytes(0)

    unsafe_download = client.get('/images/..%5Cinput.png', headers={'Host': 'localhost'})
    assert unsafe_download.status_code == 400
    assert unsafe_download.get_json()['code'] == 'invalid_filename'

    unsafe_model = client.post(
        '/settings',
        json={'active_models': {'detection': '../outside'}},
        headers=headers,
    )
    assert unsafe_model.status_code == 400
    assert unsafe_model.get_json()['code'] == 'invalid_filename'

    unsafe_model_type = client.post(
        '/settings',
        json={'active_models': {'../detection': 'fake-detection'}},
        headers=headers,
    )
    assert unsafe_model_type.status_code == 400
    assert unsafe_model_type.get_json()['code'] == 'invalid_model_type'

    scientific_policy = client.post(
        '/settings',
        json={'active_models': {}, 'tracking_exclusion_policy': 'union'},
        headers=headers,
    )
    assert scientific_policy.status_code == 400
    assert scientific_policy.get_json()['code'] == 'invalid_settings'
    assert len(scientific_policy.get_json()['diagnostic_id']) == 12


def test_configured_upload_limit_is_reported_and_enforced(tmp_path, monkeypatch):
    monkeypatch.setenv('ROOT_PATH', os.getcwd())
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setenv('ROOTDETECTOR_MAX_UPLOAD_MIB', '1')
    monkeypatch.setattr('backend.settings.ensure_pretrained_models', lambda: None)
    monkeypatch.setattr('backend.settings.Settings', FakeSettings)

    app = App()
    app.testing = True
    client = app.test_client()
    assert client.get('/api/session').get_json()['limits']['max_upload_bytes'] == 1024 * 1024
    assert app.config['MAX_CONTENT_LENGTH'] == 2 * 1024 * 1024

    too_large_file = client.post(
        '/file_upload',
        data={'files': (io.BytesIO(b'x' * (1024 * 1024 + 1)), 'too-large.png')},
        headers=request_headers(app),
    )
    assert too_large_file.status_code == 413
    assert too_large_file.get_json()['code'] == 'upload_too_large'
    assert not os.path.exists(os.path.join(app.cache_path, 'too-large.png'))

    too_large_request = client.post(
        '/file_upload',
        data={'files': (io.BytesIO(b'x' * (2 * 1024 * 1024 + 1)), 'too-large.png')},
        headers=request_headers(app),
    )
    assert too_large_request.status_code == 413
    assert too_large_request.get_json()['code'] == 'upload_too_large'
