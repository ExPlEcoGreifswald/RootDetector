"""Asynchronous training runs with explicit state and progress."""

import copy
import threading
import time
import traceback
import typing as tp
import uuid

from . import jobs
from . import training


TERMINAL_TRAINING_STATES = {'completed', 'cancelled', 'failed'}


class TrainingRun:
    def __init__(
        self,
        imagefiles:tp.List[str],
        targetfiles:tp.List[str],
        options:tp.Dict[str, tp.Any],
        settings:tp.Any,
        result_sink:tp.Optional[tp.Dict[str, training.TrainingResult]]=None,
        training_func=None,
    ):
        self.id = uuid.uuid4().hex
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.state = 'queued'
        self.progress = 0.0
        self.current = None
        self.error = None
        self.result = None
        self.attempts = 0
        self.imagefiles = list(imagefiles)
        self.targetfiles = list(targetfiles)
        self.options = copy.deepcopy(options)
        self.settings = settings
        self.result_sink = result_sink
        self.training_func = training_func or training.start_training
        self.cancel_event = threading.Event()
        self.lock = threading.RLock()
        self.thread = None

    def start(self) -> None:
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                raise RuntimeError('Training run is already active.')
            self.cancel_event.clear()
            self.thread = threading.Thread(
                target=self._execute,
                name='rootdetector-training-{}'.format(self.id[:8]),
                daemon=True,
            )
            self.thread.start()

    def request_cancel(self) -> None:
        with self.lock:
            if self.state in TERMINAL_TRAINING_STATES:
                return
            self.cancel_event.set()
            self.state = 'cancelling'
            self.updated_at = time.time()
        training.request_stop(self.settings, cancel_event=self.cancel_event)

    def wait(self, timeout:tp.Optional[float]=None) -> bool:
        thread = self.thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def snapshot(self) -> tp.Dict[str, tp.Any]:
        with self.lock:
            return {
                'id': self.id,
                'state': self.state,
                'current': copy.deepcopy(self.current),
                'created_at': self.created_at,
                'updated_at': self.updated_at,
                'progress': self.progress,
                'attempts': self.attempts,
                'training_type': self.options['training_type'],
                'file_count': len(self.imagefiles),
                'options': copy.deepcopy(self.options),
                'result': copy.deepcopy(self.result),
                'error': copy.deepcopy(self.error),
            }

    def _progress(self, value:float) -> None:
        jobs.raise_if_cancelled(event=self.cancel_event)
        with self.lock:
            self.progress = max(self.progress, min(1.0, max(0.0, float(value))))
            self.updated_at = time.time()
        training.training_progress_callback(value)

    def _execute(self) -> None:
        with self.lock:
            self.state = 'running'
            self.current = {'stage': 'training'}
            self.attempts += 1
            self.updated_at = time.time()
        try:
            result = self.training_func(
                self.imagefiles,
                self.targetfiles,
                self.options,
                self.settings,
                callback=self._progress,
                cancel_event=self.cancel_event,
            )
        except jobs.OperationCancelled:
            result = training.TrainingResult('cancelled', 'Training cancellation was requested.')
        except Exception as exc:
            traceback.print_exc()
            result = training.TrainingResult(
                'failed',
                str(exc) or exc.__class__.__name__,
                exc.__class__.__name__,
            )

        if self.result_sink is not None:
            # Publish the save gate before a poller can observe a terminal state.
            self.result_sink[self.options['training_type']] = result
        with self.lock:
            self.result = result.to_dict()
            self.state = result.state
            self.current = None
            if result.completed:
                self.progress = 1.0
            elif result.state == 'failed':
                self.error = jobs.error_payload(
                    'training_failed',
                    result.message or 'Training failed.',
                    'training',
                    item_id=self.id,
                    retryable=False,
                    error_type=result.error_type,
                )
                print(
                    '[ERROR {}] Training run {} failed: {}'.format(
                        self.error['diagnostic_id'],
                        self.id,
                        self.error['message'],
                    )
                )
            self.updated_at = time.time()


class TrainingManager:
    def __init__(
        self,
        settings:tp.Any,
        result_sink:tp.Optional[tp.Dict[str, training.TrainingResult]]=None,
        training_func=None,
        max_runs:int=20,
    ):
        self.settings = settings
        self.result_sink = result_sink
        self.training_func = training_func
        self.max_runs = max_runs
        self.runs = {}
        self.lock = threading.RLock()

    def create(
        self,
        imagefiles:tp.List[str],
        targetfiles:tp.List[str],
        options:tp.Dict[str, tp.Any],
    ) -> TrainingRun:
        with self.lock:
            if self.active_run() is not None:
                raise RuntimeError('Another training run is already active.')
            run = TrainingRun(
                imagefiles,
                targetfiles,
                options,
                self.settings,
                result_sink=self.result_sink,
                training_func=self.training_func,
            )
            self.runs[run.id] = run
            self._discard_old_runs()
            run.start()
            return run

    def get(self, run_id:str) -> TrainingRun:
        with self.lock:
            try:
                return self.runs[run_id]
            except KeyError:
                raise KeyError('Training run not found: {}'.format(run_id))

    def active_run(self) -> tp.Optional[TrainingRun]:
        with self.lock:
            return next(
                (run for run in self.runs.values() if run.state not in TERMINAL_TRAINING_STATES),
                None,
            )

    def _discard_old_runs(self) -> None:
        if len(self.runs) <= self.max_runs:
            return
        completed = sorted(
            (run for run in self.runs.values() if run.state in TERMINAL_TRAINING_STATES),
            key=lambda run: run.updated_at,
        )
        while len(self.runs) > self.max_runs and completed:
            self.runs.pop(completed.pop(0).id, None)
