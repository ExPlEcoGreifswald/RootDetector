"""Validated training orchestration and legacy-model result adaptation."""

from dataclasses import dataclass
from contextlib import contextmanager
import math
import os
import sys
import threading
import typing as tp

import torch

from backend import jobs
from base.backend import GLOBALS
from base.backend import pubsub
from base.backend.app import get_cache_path


TRAINING_STATES = {'completed', 'cancelled', 'failed'}
_cancel_requested = threading.Event()


class TrainingValidationError(ValueError):
    """Raised when a training request cannot be executed as supplied."""


# Retain the exception name used by the Windows-tested compatibility layer.
TrainingOptionsError = TrainingValidationError


@dataclass(frozen=True)
class TrainingResult:
    state: str
    message: str = ''
    error_type: tp.Optional[str] = None

    @property
    def completed(self) -> bool:
        return self.state == 'completed'

    def to_dict(self) -> tp.Dict[str, tp.Any]:
        output = {'state': self.state, 'message': self.message}
        if self.error_type:
            output['error_type'] = self.error_type
        return output


def training_progress_callback(value):
    pubsub.PubSub.publish(
        {'progress': value, 'description': 'Training...'},
        event='training',
    )


def parse_training_options(options:tp.Any) -> tp.Dict[str, tp.Any]:
    """Normalize the public and legacy learning-rate field names."""
    if not isinstance(options, dict):
        raise TrainingValidationError('Training options must be a JSON object.')
    allowed = {'training_type', 'epochs', 'learning_rate', 'lr'}
    required = {'training_type', 'epochs'}
    unknown = set(options) - allowed
    missing = required - set(options)
    if unknown:
        raise TrainingValidationError(
            'Unknown training option(s): {}.'.format(', '.join(sorted(unknown)))
        )
    if missing:
        raise TrainingValidationError(
            'Missing training option(s): {}.'.format(', '.join(sorted(missing)))
        )
    if 'learning_rate' not in options and 'lr' not in options:
        raise TrainingValidationError('Missing training option: learning_rate.')

    training_type = options['training_type']
    if training_type not in {'detection', 'exclusion_mask'}:
        raise TrainingValidationError('Invalid training type.')
    if isinstance(options['epochs'], bool):
        raise TrainingValidationError('Epochs must be a whole number.')
    try:
        epochs = int(options['epochs'])
    except (TypeError, ValueError) as exc:
        raise TrainingValidationError('Epochs must be a whole number.') from exc
    if epochs < 1 or epochs > 10000 or epochs != options['epochs']:
        raise TrainingValidationError('Epochs must be between 1 and 10000.')

    public_rate = options.get('learning_rate')
    legacy_rate = options.get('lr')
    if public_rate is not None and legacy_rate is not None:
        try:
            rates_match = math.isclose(float(public_rate), float(legacy_rate))
        except (TypeError, ValueError):
            rates_match = False
        if not rates_match:
            raise TrainingValidationError(
                'learning_rate and the legacy lr option must match.'
            )
    rate = public_rate if public_rate is not None else legacy_rate
    if isinstance(rate, bool):
        raise TrainingValidationError('Learning rate must be a number.')
    try:
        learning_rate = float(rate)
    except (TypeError, ValueError) as exc:
        raise TrainingValidationError('Learning rate must be a number.') from exc
    if not math.isfinite(learning_rate) or learning_rate <= 0 or learning_rate > 1:
        raise TrainingValidationError('Learning rate must be greater than 0 and at most 1.')

    return {
        'training_type': training_type,
        'epochs': epochs,
        'learning_rate': learning_rate,
        # Normalized legacy alias for released model and CLI integrations.
        'lr': learning_rate,
    }


@contextmanager
def _capture_legacy_fit_result(model, cancel_event=None):
    """Expose errors swallowed by released model packages without repacking them."""
    captured = {}
    start_method = getattr(model, 'start_training', None)
    function = getattr(start_method, '__func__', start_method)
    namespace = getattr(function, '__globals__', {})
    training_module = namespace.get('traininglib')
    task_class = getattr(training_module, 'SegmentationTask', None)
    owner = next(
        (candidate for candidate in getattr(task_class, '__mro__', ()) if 'fit' in candidate.__dict__),
        None,
    )
    if owner is None:
        yield captured
        return

    original_fit = owner.fit

    def monitored_fit(task, *args, **kwargs):
        if _cancel_requested.is_set() or (cancel_event is not None and cancel_event.is_set()):
            captured['fit_result'] = 'cancelled'
            return 'cancelled'
        result = original_fit(task, *args, **kwargs)
        captured['fit_result'] = result
        if isinstance(result, BaseException):
            raise result
        return result

    owner.fit = monitored_fit
    try:
        yield captured
    finally:
        owner.fit = original_fit


def _normalize_model_result(
    value:tp.Any,
    captured:tp.Dict[str, tp.Any],
    maximum_progress:float,
    cancel_event=None,
) -> TrainingResult:
    if isinstance(value, TrainingResult):
        return value
    if isinstance(value, dict) and value.get('state') in TRAINING_STATES:
        return TrainingResult(
            value['state'],
            str(value.get('message', '')),
            value.get('error_type'),
        )
    if isinstance(value, str) and value.lower() in TRAINING_STATES:
        return TrainingResult(value.lower())
    if isinstance(value, BaseException):
        return TrainingResult('failed', str(value), value.__class__.__name__)
    if value is True:
        return TrainingResult('completed')
    if value is False:
        return TrainingResult('cancelled', 'Training was interrupted.')

    legacy_fit_result = captured.get('fit_result')
    if isinstance(legacy_fit_result, str) and legacy_fit_result.lower() in TRAINING_STATES:
        return TrainingResult(legacy_fit_result.lower())
    if _cancel_requested.is_set() or (cancel_event is not None and cancel_event.is_set()):
        return TrainingResult('cancelled', 'Training cancellation was requested.')
    # Released model packages return None after successful training. The fit
    # wrapper above converts their swallowed runtime exceptions into failures.
    if value is None:
        if maximum_progress >= 1:
            return TrainingResult('completed')
        return TrainingResult(
            'cancelled',
            'Legacy training ended before reporting 100% completion.',
        )
    return TrainingResult(
        'failed',
        'The model returned an unsupported training result.',
        type(value).__name__,
    )


def _restore_previous_model(settings, training_type, previous_model_name):
    """Discard partial weights by reloading the last saved model."""
    if not previous_model_name or not hasattr(settings, 'load_model'):
        return False
    try:
        restored = settings.load_model(training_type, previous_model_name)
    except Exception as exc:
        print('[WARNING] Could not restore the pre-training model: {}'.format(exc))
        return False
    if restored is None:
        return False
    settings.models[training_type] = restored
    settings.active_models[training_type] = previous_model_name
    return True


def start_training(
    imagefiles,
    targetfiles,
    training_options:dict,
    settings,
    callback=training_progress_callback,
    cancel_event=None,
) -> TrainingResult:
    options = parse_training_options(training_options)
    if len(imagefiles) == 0 or len(imagefiles) != len(targetfiles):
        raise TrainingValidationError('Training requires matching image and annotation files.')

    locked = GLOBALS.processing_lock.acquire(blocking=False)
    if not locked:
        raise RuntimeError('Cannot start training. Another operation is running.')

    training_type = options['training_type']
    previous_model_name = settings.active_models.get(training_type, '')
    _cancel_requested.clear()
    result = TrainingResult('failed', 'Training did not start.')
    progress = {'maximum': 0.0}
    model:tp.Any = None

    def monitored_callback(value):
        jobs.raise_if_cancelled(event=cancel_event)
        progress['maximum'] = max(progress['maximum'], float(value))
        callback(value)

    try:
        model = settings.models.get(training_type)
        if model is None:
            raise TrainingValidationError('No {} model is loaded.'.format(training_type))
        settings.active_models[training_type] = ''
        device = 'cuda' if settings.use_gpu and torch.cuda.is_available() else 'cpu'
        jobs.raise_if_cancelled(event=cancel_event)
        with _capture_legacy_fit_result(model, cancel_event) as captured:
            value = model.start_training(
                imagefiles,
                targetfiles,
                epochs=options['epochs'],
                lr=options['learning_rate'],
                num_workers='auto' if 'win' not in sys.platform else 0,
                callback=monitored_callback,
                ds_kwargs={'tmpdir': get_cache_path()},
                fit_kwargs={'device': device},
            )
        result = _normalize_model_result(value, captured, progress['maximum'], cancel_event)
    except jobs.OperationCancelled:
        result = TrainingResult('cancelled', 'Training cancellation was requested.')
    except KeyboardInterrupt:
        result = TrainingResult('cancelled', 'Training was interrupted.')
    except Exception as exc:
        result = TrainingResult('failed', str(exc) or exc.__class__.__name__, exc.__class__.__name__)
    finally:
        try:
            if model is not None:
                try:
                    model.cpu()
                except Exception as exc:
                    result = TrainingResult(
                        'failed',
                        'Training cleanup failed: {}'.format(
                            str(exc) or exc.__class__.__name__
                        ),
                        exc.__class__.__name__,
                    )
        finally:
            GLOBALS.processing_lock.release()

    if not result.completed:
        restored = _restore_previous_model(settings, training_type, previous_model_name)
        if not restored:
            # The object may have been partly modified; never expose it as a
            # named release model when an explicit reload was unavailable.
            settings.active_models[training_type] = ''
    return result


def request_stop(settings, cancel_event=None) -> None:
    if cancel_event is not None:
        cancel_event.set()
    _cancel_requested.set()
    for model in settings.models.values():
        if hasattr(model, 'stop_training'):
            try:
                model.stop_training()
            except Exception as exc:
                print('[WARNING] A model rejected the training stop request: {}'.format(exc))


def find_targetfiles(inputfiles):
    def find_targetfile(imgf):
        no_ext_imgf = os.path.splitext(imgf)[0]
        for candidate in [
            '{}.segmentation.png'.format(imgf),
            '{}.segmentation.png'.format(no_ext_imgf),
            '{}.png'.format(no_ext_imgf),
        ]:
            if os.path.exists(candidate):
                return candidate
        return None

    return list(map(find_targetfile, inputfiles))
