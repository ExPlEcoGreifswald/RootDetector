import math
import os
import types

import pytest

from backend import training
from backend.app import App


@pytest.mark.parametrize('key', ['learning_rate', 'lr'])
def test_training_accepts_public_and_legacy_learning_rate_names(key):
    options = training.parse_training_options({
        'training_type': 'detection',
        'epochs': 3,
        key: 0.0002,
    })

    assert options['learning_rate'] == pytest.approx(0.0002)
    assert options['lr'] == pytest.approx(0.0002)


def test_public_and_legacy_learning_rate_must_not_conflict():
    with pytest.raises(training.TrainingOptionsError, match='must match'):
        training.parse_training_options({
            'training_type': 'detection',
            'epochs': 3,
            'learning_rate': 0.0002,
            'lr': 0.001,
        })


@pytest.mark.parametrize('value', [None, 0, -0.1, 2, math.nan, math.inf, 'invalid'])
def test_training_rejects_missing_or_invalid_learning_rate(value):
    options = {'training_type': 'detection', 'epochs': 3}
    if value is not None:
        options['learning_rate'] = value

    with pytest.raises(training.TrainingOptionsError):
        training.parse_training_options(options)


def test_training_forwards_learning_rate_to_model():
    class Model:
        def __init__(self):
            self.kwargs = None

        def start_training(self, _images, _targets, **kwargs):
            self.kwargs = kwargs
            return True

        def cpu(self):
            return self

    class Settings:
        use_gpu = False
        active_models = {'detection': 'test-model'}
        models = {'detection': Model()}

    settings = Settings()
    result = training.start_training(
        ['image.tiff'],
        ['image.segmentation.png'],
        {
            'training_type': 'detection',
            'epochs': 2,
            'learning_rate': 0.0003,
        },
        settings,
    )

    assert result.state == 'completed'
    assert settings.models['detection'].kwargs['lr'] == pytest.approx(0.0003)


def test_stop_then_repeated_retries_reset_cancellation_and_complete():
    class Model:
        def __init__(self):
            self.runs = 0
            self.stop_calls = 0

        def start_training(self, _images, _targets, **kwargs):
            self.runs += 1
            if self.runs == 1:
                kwargs['callback'](0.25)
                training.request_stop(settings)
                return None
            kwargs['callback'](1.0)
            # Released model packages return None even after success.
            return None

        def stop_training(self):
            self.stop_calls += 1

        def cpu(self):
            return self

    class Settings:
        use_gpu = False
        active_models = {'detection': ''}
        models = {'detection': Model()}

    settings = Settings()
    options = {
        'training_type': 'detection',
        'epochs': 1,
        'learning_rate': 0.0007,
    }

    interrupted = training.start_training(['image'], ['target'], options, settings)
    first_retry = training.start_training(['image'], ['target'], options, settings)
    second_retry = training.start_training(['image'], ['target'], options, settings)

    assert interrupted.state == 'cancelled'
    assert first_retry.state == 'completed'
    assert second_retry.state == 'completed'
    assert settings.models['detection'].stop_calls == 1


def test_training_restores_saved_model_after_interruption():
    class PartialModel:
        def start_training(self, _images, _targets, **kwargs):
            kwargs['callback'](0.25)
            training.request_stop(settings)

        def stop_training(self):
            pass

        def cpu(self):
            return self

    restored_model = object()

    class Settings:
        use_gpu = False
        active_models = {'detection': 'released-model'}
        models = {'detection': PartialModel()}

        def load_model(self, modeltype, modelname):
            assert (modeltype, modelname) == ('detection', 'released-model')
            return restored_model

    settings = Settings()
    result = training.start_training(
        ['image'],
        ['target'],
        {
            'training_type': 'detection',
            'epochs': 1,
            'learning_rate': 0.0007,
        },
        settings,
    )

    assert result.state == 'cancelled'
    assert settings.models['detection'] is restored_model
    assert settings.active_models['detection'] == 'released-model'


def test_training_surfaces_exception_hidden_by_released_model_wrapper():
    class TrainingTask:
        def fit(self):
            return RuntimeError('legacy training failed')

    class SegmentationTask(TrainingTask):
        pass

    namespace = {'traininglib': types.SimpleNamespace(SegmentationTask=SegmentationTask)}
    exec(
        'def start_training(self, *args, **kwargs):\n'
        '    task = traininglib.SegmentationTask()\n'
        '    task.fit()\n',
        namespace,
    )

    class Model:
        start_training = namespace['start_training']

        def cpu(self):
            return self

    class Settings:
        use_gpu = False
        active_models = {'detection': ''}
        models = {'detection': Model()}

    result = training.start_training(
        ['image'],
        ['target'],
        {
            'training_type': 'detection',
            'epochs': 1,
            'learning_rate': 0.0007,
        },
        Settings(),
    )

    assert result.state == 'failed'
    assert result.error_type == 'RuntimeError'
    assert result.message == 'legacy training failed'


@pytest.mark.parametrize('key', ['learning_rate', 'lr'])
def test_training_api_reports_the_effective_learning_rate(key, tmp_path, monkeypatch):
    class Settings:
        active_models = {'detection': 'test-model'}
        models = {}
        use_gpu = False
        exmask_enabled = False
        too_many_roots = 100000

        def get_settings_as_dict(self):
            return {'settings': {}, 'available_models': {}}

    monkeypatch.setenv('ROOT_PATH', os.getcwd())
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setattr('backend.settings.ensure_pretrained_models', lambda: None)
    monkeypatch.setattr('backend.settings.Settings', Settings)
    captured = {}

    def start_training(_images, _targets, options, _settings, **_kwargs):
        captured.update(options)
        return training.TrainingResult('completed')

    monkeypatch.setattr(training, 'start_training', start_training)
    app = App()
    app.testing = True
    image = os.path.join(app.cache_path, 'image.png')
    target = os.path.join(app.cache_path, 'training-label-reviewed.png')
    os.makedirs(app.cache_path, exist_ok=True)
    open(image, 'wb').close()
    open(target, 'wb').close()

    headers = {
        'Host': 'localhost',
        'Origin': 'http://localhost',
        'X-RootDetector-Token': app.session_token,
    }
    response = app.test_client().post('/training', json={
        'filenames': ['image.png'],
        'label_filenames': ['training-label-reviewed.png'],
        'label_review': {'source': 'user_reviewed', 'confirmed': True},
        'options': {
            'training_type': 'detection',
            'epochs': 2,
            key: 0.0004,
        },
    }, headers=headers)

    assert response.status_code == 200
    assert response.get_json()['state'] == 'completed'
    assert response.get_json()['result'] == 'OK'
    assert response.get_json()['effective_options']['learning_rate'] == pytest.approx(0.0004)
    assert captured['learning_rate'] == pytest.approx(0.0004)
    assert captured['lr'] == pytest.approx(0.0004)


def test_interrupted_training_cannot_be_saved(tmp_path, monkeypatch):
    class Model:
        def __init__(self):
            self.saved_path = None

        def save(self, path):
            self.saved_path = path

    class Settings:
        active_models = {'detection': 'test-model'}
        models = {'detection': Model()}
        use_gpu = False
        exmask_enabled = False
        too_many_roots = 100000

        def get_settings_as_dict(self):
            return {'settings': {}, 'available_models': {}}

    monkeypatch.setenv('ROOT_PATH', os.getcwd())
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setattr('backend.settings.ensure_pretrained_models', lambda: None)
    monkeypatch.setattr('backend.settings.Settings', Settings)
    app = App()
    app.testing = True
    settings = app.settings
    app.training_results['detection'] = training.TrainingResult('cancelled')

    headers = {
        'Host': 'localhost',
        'Origin': 'http://localhost',
        'X-RootDetector-Token': app.session_token,
    }
    response = app.test_client().post('/save_model', json={
        'newname': 'partial-model',
        'options': {'training_type': 'detection'},
    }, headers=headers)

    assert response.status_code == 409
    assert response.get_json()['code'] == 'training_not_completed'

    app.training_results['detection'] = training.TrainingResult('completed')
    response = app.test_client().post('/save_model', json={
        'newname': 'completed-model',
        'options': {'training_type': 'detection'},
    }, headers=headers)

    assert response.status_code == 200
    assert settings.models['detection'].saved_path.endswith(
        os.path.join('models', 'detection', 'completed-model')
    )
    assert settings.active_models['detection'] == 'completed-model'
