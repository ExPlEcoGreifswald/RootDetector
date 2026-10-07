import threading

from backend import training
from backend import training_jobs


class Settings:
    models = {}


def options():
    return {'training_type': 'detection', 'epochs': 2, 'lr': 0.001}


def test_training_job_reports_progress_and_completion():
    def train(_images, _targets, _options, _settings, callback, cancel_event):
        assert not cancel_event.is_set()
        callback(0.25)
        callback(1.0)
        return training.TrainingResult('completed')

    results = {}
    manager = training_jobs.TrainingManager(
        Settings(),
        result_sink=results,
        training_func=train,
    )
    run = manager.create(['image.png'], ['target.png'], options())
    assert run.wait(2)
    snapshot = run.snapshot()
    assert snapshot['state'] == 'completed'
    assert snapshot['progress'] == 1.0
    assert snapshot['attempts'] == 1
    assert results['detection'].completed


def test_training_job_cancels_cooperatively():
    started = threading.Event()

    def train(_images, _targets, _options, _settings, callback, cancel_event):
        callback(0.1)
        started.set()
        assert cancel_event.wait(2)
        return training.TrainingResult('cancelled', 'Training cancellation was requested.')

    manager = training_jobs.TrainingManager(Settings(), training_func=train)
    run = manager.create(['image.png'], ['target.png'], options())
    assert started.wait(1)
    run.request_cancel()
    assert run.wait(2)
    assert run.snapshot()['state'] == 'cancelled'


def test_training_job_failure_has_diagnostic_id():
    def train(*_args, **_kwargs):
        return training.TrainingResult('failed', 'bad model', 'RuntimeError')

    manager = training_jobs.TrainingManager(Settings(), training_func=train)
    run = manager.create(['image.png'], ['target.png'], options())
    assert run.wait(2)
    error = run.snapshot()['error']
    assert error['code'] == 'training_failed'
    assert error['message'] == 'bad model'
    assert len(error['diagnostic_id']) == 12
