import types
import typing as tp

import pytest

from backend import training
from backend.app import App


class FakeModel:
    def __init__(self, result:tp.Any=training.TrainingResult('completed')):
        self.result = result
        self.calls = []
        self.cpu_calls = 0
        self.stop_calls = 0

    def start_training(self, imagefiles, targetfiles, **kwargs):
        self.calls.append((imagefiles, targetfiles, kwargs))
        if isinstance(self.result, BaseException):
            raise self.result
        if self.result is None:
            kwargs['callback'](1)
        return self.result

    def cpu(self):
        self.cpu_calls += 1
        return self

    def stop_training(self):
        self.stop_calls += 1


class FakeSettings:
    use_gpu = False

    def __init__(self, model):
        self.models = {'detection': model}
        self.active_models = {'detection': 'model-a'}


def options(**overrides):
    value = {'training_type': 'detection', 'epochs': 3, 'lr': 0.0002}
    value.update(overrides)
    return value


@pytest.mark.parametrize('invalid', [
    {'training_type': 'tracking', 'epochs': 3, 'lr': 0.1},
    {'training_type': 'detection', 'epochs': 0, 'lr': 0.1},
    {'training_type': 'detection', 'epochs': 3, 'lr': float('nan')},
])
def test_training_options_reject_unknown_or_invalid_values(invalid):
    with pytest.raises(training.TrainingValidationError):
        training.parse_training_options(invalid)


def test_training_forwards_learning_rate_and_reports_completion(monkeypatch, tmp_path):
    monkeypatch.setattr(training, 'get_cache_path', lambda: str(tmp_path))
    model = FakeModel('completed')
    settings = FakeSettings(model)
    result = training.start_training(['image.png'], ['target.png'], options(), settings)

    assert result.state == 'completed'
    assert model.calls[0][2]['lr'] == 0.0002
    assert model.calls[0][2]['epochs'] == 3
    assert model.cpu_calls == 1
    assert settings.active_models['detection'] == ''


@pytest.mark.parametrize('model_result, expected_state', [
    (False, 'cancelled'),
    ('cancelled', 'cancelled'),
    (RuntimeError('training exploded'), 'failed'),
])
def test_training_propagates_cancel_and_failure(model_result, expected_state, monkeypatch, tmp_path):
    monkeypatch.setattr(training, 'get_cache_path', lambda: str(tmp_path))
    model = FakeModel(model_result)
    result = training.start_training(
        ['image.png'],
        ['target.png'],
        options(),
        FakeSettings(model),
    )
    assert result.state == expected_state


def test_training_adapts_released_model_that_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(training, 'get_cache_path', lambda: str(tmp_path))
    model = FakeModel(None)
    result = training.start_training(
        ['image.png'],
        ['target.png'],
        options(),
        FakeSettings(model),
    )
    assert result.state == 'completed'


def test_training_does_not_treat_unconfirmed_legacy_none_as_success(monkeypatch, tmp_path):
    monkeypatch.setattr(training, 'get_cache_path', lambda: str(tmp_path))

    class SilentLegacyModel(FakeModel):
        def start_training(self, *_args, **_kwargs):
            return None

    result = training.start_training(
        ['image.png'],
        ['target.png'],
        options(),
        FakeSettings(SilentLegacyModel()),
    )
    assert result.state == 'cancelled'
    assert '100%' in result.message


def test_training_surfaces_exception_swallowed_by_released_fit(monkeypatch, tmp_path):
    monkeypatch.setattr(training, 'get_cache_path', lambda: str(tmp_path))

    class TrainingTask:
        def fit(self, *_args, **_kwargs):
            return RuntimeError('legacy failure')

    class SegmentationTask(TrainingTask):
        pass

    namespace = {'traininglib': types.SimpleNamespace(SegmentationTask=SegmentationTask)}
    exec(
        'def start_training(self, *args, **kwargs):\n'
        '    task = traininglib.SegmentationTask()\n'
        '    task.fit()\n',
        namespace,
    )

    LegacyModel = type('LegacyModel', (FakeModel,), {'start_training': namespace['start_training']})

    result = training.start_training(
        ['image.png'],
        ['target.png'],
        options(),
        FakeSettings(LegacyModel()),
    )
    assert result.state == 'failed'
    assert result.error_type == 'RuntimeError'
    assert result.message == 'legacy failure'


def test_request_stop_reaches_all_loaded_models():
    model = FakeModel()
    settings = FakeSettings(model)
    training.request_stop(settings)
    assert model.stop_calls == 1


def test_training_endpoint_accepts_public_field_and_reports_result(tmp_path, monkeypatch):
    class WebSettings(FakeSettings):
        exmask_enabled = False
        too_many_roots = 100000

        def get_settings_as_dict(self):
            return {'settings': {}, 'available_models': {}}

    model = FakeModel()
    settings = WebSettings(model)
    monkeypatch.setenv('ROOT_PATH', str(tmp_path))
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setattr('backend.settings.ensure_pretrained_models', lambda: None)
    monkeypatch.setattr('backend.settings.Settings', lambda: settings)
    app = App()
    app.testing = True
    image_path = tmp_path / 'cache' / 'sample.tiff'
    annotation_path = tmp_path / 'cache' / 'sample.png'
    image_path.write_bytes(b'image')
    annotation_path.write_bytes(b'annotation')
    client = app.test_client()
    headers = {
        'Host': 'localhost',
        'Origin': 'http://localhost',
        'X-RootDetector-Token': app.session_token,
    }

    unreviewed = client.post('/training', json={
        'filenames': ['sample.tiff'],
        'options': options(),
    }, headers=headers)
    assert unreviewed.status_code == 400
    assert unreviewed.get_json()['code'] == 'unreviewed_training_labels'

    public_field = client.post('/training', json={
        'filenames': ['sample.tiff'],
        'label_review': {'source': 'user_reviewed', 'confirmed': True},
        'options': {
            'training_type': 'detection',
            'epochs': 3,
            'learning_rate': 0.1,
        },
    }, headers=headers)
    assert public_field.status_code == 200
    assert public_field.get_json()['state'] == 'completed'

    monkeypatch.setattr(
        training,
        'start_training',
        lambda *_args, **_kwargs: training.TrainingResult('completed'),
    )
    completed = client.post('/training', json={
        'filenames': ['sample.tiff'],
        'label_review': {'source': 'user_reviewed', 'confirmed': True},
        'options': options(),
    }, headers=headers)
    assert completed.status_code == 200
    assert completed.get_json()['state'] == 'completed'


def test_save_model_requires_completed_training(tmp_path, monkeypatch):
    class WebSettings(FakeSettings):
        exmask_enabled = False
        too_many_roots = 100000

        def get_settings_as_dict(self):
            return {'settings': {}, 'available_models': {}}

    monkeypatch.setenv('ROOT_PATH', str(tmp_path))
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setattr('backend.settings.ensure_pretrained_models', lambda: None)
    monkeypatch.setattr('backend.settings.Settings', lambda: WebSettings(FakeModel()))
    app = App()
    app.testing = True
    client = app.test_client()
    response = client.post('/save_model', json={
        'newname': 'unfinished-model',
        'options': options(),
    }, headers={
        'Host': 'localhost',
        'Origin': 'http://localhost',
        'X-RootDetector-Token': app.session_token,
    })
    assert response.status_code == 409
    assert response.get_json()['code'] == 'training_not_completed'


def test_training_job_api_reports_progress_and_cooperative_cancellation(tmp_path, monkeypatch):
    class WebSettings(FakeSettings):
        exmask_enabled = False
        too_many_roots = 100000

        def get_settings_as_dict(self):
            return {'settings': {}, 'available_models': {}}

    settings = WebSettings(FakeModel())
    monkeypatch.setenv('ROOT_PATH', str(tmp_path))
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setattr('backend.settings.ensure_pretrained_models', lambda: None)
    monkeypatch.setattr('backend.settings.Settings', lambda: settings)
    app = App()
    app.testing = True
    image_path = tmp_path / 'cache' / 'sample.tiff'
    annotation_path = tmp_path / 'cache' / 'sample.png'
    image_path.write_bytes(b'image')
    annotation_path.write_bytes(b'annotation')
    started = __import__('threading').Event()

    def blocking_training(
        _images,
        _targets,
        _options,
        _settings,
        callback,
        cancel_event,
    ):
        callback(0.25)
        started.set()
        assert cancel_event.wait(2)
        return training.TrainingResult('cancelled', 'cancelled by test')

    monkeypatch.setattr(training, 'start_training', blocking_training)
    client = app.test_client()
    headers = {
        'Host': 'localhost',
        'Origin': 'http://localhost',
        'X-RootDetector-Token': app.session_token,
    }
    unreviewed = client.post('/api/training/runs', json={
        'filenames': ['sample.tiff'],
        'options': options(),
    }, headers=headers)
    assert unreviewed.status_code == 400
    assert unreviewed.get_json()['code'] == 'unreviewed_training_labels'
    created = client.post('/api/training/runs', json={
        'filenames': ['sample.tiff'],
        'label_review': {'source': 'user_reviewed', 'confirmed': True},
        'options': options(),
    }, headers=headers)
    assert created.status_code == 202
    run_id = created.get_json()['id']
    assert started.wait(1)

    active = client.get('/api/training/runs/' + run_id)
    assert active.status_code == 200
    assert active.get_json()['state'] == 'running'
    assert active.get_json()['progress'] == 0.25

    cancelled = client.post(
        '/api/training/runs/{}/cancel'.format(run_id),
        headers=headers,
    )
    assert cancelled.status_code == 202
    assert app.training_manager.get(run_id).wait(2)
    assert client.get('/api/training/runs/' + run_id).get_json()['state'] == 'cancelled'

    missing = client.get('/api/training/runs/missing')
    assert missing.status_code == 404
    assert missing.get_json()['code'] == 'training_not_found'
