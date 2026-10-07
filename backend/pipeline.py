"""In-process orchestration for the automated detection and tracking workflow."""

import copy
import os
import threading
import time
import traceback
import typing as tp
import uuid

from base.backend.app import get_cache_path

from . import root_detection
from . import root_tracking
from . import jobs
from . import security
from . import diagnostics


TERMINAL_ITEM_STATES = {
    'completed',
    'failed',
    'skipped',
    'review_required',
    'cancelled',
}
TERMINAL_RUN_STATES = {
    'completed',
    'completed_with_errors',
    'cancelled',
    'failed',
}
SUPPORTED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tif', '.tiff'}


def _snapshot_settings(settings):
    """Freeze run options while retaining the already-loaded model objects."""
    snapshot = copy.copy(settings)
    if hasattr(settings, 'models'):
        snapshot.models = dict(settings.models)
    if hasattr(settings, 'active_models'):
        snapshot.active_models = copy.deepcopy(settings.active_models)
    return snapshot


def _error(
    stage:str,
    item_id:str,
    exc:Exception,
    retryable:bool=True,
    settings=None,
) -> dict:
    payload = jobs.error_payload(
        '{}_failed'.format(stage),
        str(exc) or exc.__class__.__name__,
        stage,
        item_id=item_id,
        retryable=retryable,
        error_type=exc.__class__.__name__,
    )
    diagnostics.log_exception(payload['diagnostic_id'], stage, item_id, exc, settings)
    return payload


def _serialize_detection(result:dict) -> dict:
    serialized = copy.deepcopy(result)
    for key in ['segmentation', 'skeleton']:
        if key in serialized:
            serialized[key] = os.path.basename(serialized[key])
    return serialized


def _serialize_tracking(result:dict) -> dict:
    return {
        'points0': result['points0'].tolist(),
        'points1': result['points1'].tolist(),
        'growthmap': os.path.basename(result['growthmap']),
        'growthmap_rgba': os.path.basename(result['growthmap_rgba']),
        'segmentation0': os.path.basename(result['segmentation0']),
        'segmentation1': os.path.basename(result['segmentation1']),
        'success': bool(result['success']),
        'n_matched_points': int(result['n_matched_points']),
        'tracking_model': result['tracking_model'],
        'segmentation_model': result['segmentation_model'],
        'tracking_matcher': copy.deepcopy(result.get('tracking_matcher', {
            'name': 'released-model-internal-matcher',
            'version': 0,
        })),
        'exclusion_mask_policy': result.get(
            'exclusion_mask_policy',
            root_tracking.DEFAULT_EXCLUSION_MASK_POLICY,
        ),
        'exclusion_masks': copy.deepcopy(result.get('exclusion_masks', {
            'observation0_present': False,
            'observation1_present': False,
            'observation0_pixels': 0,
            'observation1_pixels': 0,
            'combined_pixels': 0,
        })),
        'statistics': copy.deepcopy(result['statistics']),
    }


class PipelineRun:
    def __init__(
        self,
        filenames:tp.List[str],
        file_pairs:tp.List[tp.Tuple[str, str]],
        settings,
        cache_path:str,
        detection_func=None,
        tracking_func=None,
    ):
        self.id = uuid.uuid4().hex
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.state = 'queued'
        self.current = None
        self.settings = _snapshot_settings(settings)
        self.cache_path = cache_path
        self.detection_func = detection_func or root_detection.process_image
        self.tracking_func = tracking_func or root_tracking.process
        self.cancel_event = threading.Event()
        self.settings.cancel_event = self.cancel_event
        self.lock = threading.RLock()
        self.settings.operation_progress_callback = self._operation_progress
        self.thread = None

        self.images = {}
        for filename in filenames:
            self.images[filename] = {
                'id': filename,
                'filename': filename,
                'state': 'queued',
                'stage': 'detection',
                'result': None,
                'error': None,
                'attempts': 0,
                'elapsed_seconds': None,
            }

        self.pairs = []
        for filename0, filename1 in file_pairs:
            pair_id = '{}::{}'.format(filename0, filename1)
            self.pairs.append({
                'id': pair_id,
                'filename0': filename0,
                'filename1': filename1,
                'state': 'queued',
                'stage': 'tracking',
                'result': None,
                'error': None,
                'attempts': 0,
                'elapsed_seconds': None,
            })

    def start(self) -> None:
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                raise RuntimeError('Pipeline run is already active.')
            self.cancel_event.clear()
            self.thread = threading.Thread(
                target=self._execute,
                name='rootdetector-pipeline-{}'.format(self.id[:8]),
                daemon=True,
            )
            self.thread.start()

    def request_cancel(self) -> None:
        self.cancel_event.set()
        self._touch()

    def retry_failed(self) -> None:
        with self.lock:
            if self.state not in TERMINAL_RUN_STATES:
                raise RuntimeError('Cannot retry an active pipeline run.')
            for item in self.images.values():
                if item['state'] in ['failed', 'cancelled']:
                    item.update(state='queued', result=None, error=None)
            for item in self.pairs:
                if item['state'] in ['failed', 'skipped', 'cancelled']:
                    item.update(state='queued', result=None, error=None)
            if not self._queued_items():
                raise RuntimeError('No failed, skipped, or cancelled items are available to retry.')
            self.state = 'queued'
            self.start()

    def wait(self, timeout:tp.Optional[float]=None) -> bool:
        thread = self.thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def snapshot(self) -> dict:
        with self.lock:
            images = copy.deepcopy(self.images)
            pairs = copy.deepcopy(self.pairs)
            total = len(images) + len(pairs)
            finished = sum(
                item['state'] in TERMINAL_ITEM_STATES
                for item in list(images.values()) + pairs
            )
            counts = {}
            for item in list(images.values()) + pairs:
                counts[item['state']] = counts.get(item['state'], 0) + 1
            return {
                'id': self.id,
                'state': self.state,
                'current': copy.deepcopy(self.current),
                'created_at': self.created_at,
                'updated_at': self.updated_at,
                'progress': {
                    'finished': finished,
                    'total': total,
                    'fraction': (finished / total) if total else 1.0,
                },
                'summary': counts,
                'images': images,
                'pairs': pairs,
            }

    def _touch(self) -> None:
        with self.lock:
            self.updated_at = time.time()

    def _queued_items(self) -> bool:
        return any(item['state'] == 'queued' for item in self.images.values()) or any(
            item['state'] == 'queued' for item in self.pairs
        )

    def _set_item(self, item:dict, **changes) -> None:
        with self.lock:
            item.update(changes)
            self.updated_at = time.time()

    def _set_current(self, stage:str, item_id:str) -> None:
        with self.lock:
            self.current = {
                'stage': stage,
                'item_id': item_id,
                'progress': 0.0,
                'description': '',
            }
            self.updated_at = time.time()

    def _operation_progress(self, value:float, description:str='') -> None:
        with self.lock:
            if self.current is None:
                return
            self.current['progress'] = max(0.0, min(1.0, float(value)))
            self.current['description'] = description
            self.updated_at = time.time()

    def _cancel_remaining(self) -> None:
        for item in list(self.images.values()) + self.pairs:
            if item['state'] == 'queued':
                self._set_item(item, state='cancelled')

    def _execute(self) -> None:
        with self.lock:
            self.state = 'running'
            self.updated_at = time.time()

        diagnostics.logger().info(
            'Pipeline %s started with %d images and %d pairs.',
            self.id,
            len(self.images),
            len(self.pairs),
        )
        try:
            for filename, item in self.images.items():
                if item['state'] != 'queued':
                    continue
                if self.cancel_event.is_set():
                    self._cancel_remaining()
                    break

                self._set_current('detection', filename)
                item_started_at = time.time()
                self._set_item(
                    item,
                    state='detecting',
                    error=None,
                    attempts=item['attempts'] + 1,
                )
                try:
                    image_path = os.path.join(self.cache_path, filename)
                    result = self.detection_func(image_path, self.settings)
                    self._set_item(item, state='completed', result=_serialize_detection(result))
                except jobs.OperationCancelled:
                    self._set_item(item, state='cancelled', result=None, error=None)
                    self._cancel_remaining()
                    break
                except Exception as exc:
                    if (
                        getattr(self.settings, 'use_gpu', False)
                        and root_detection.is_retryable_accelerator_error(exc)
                    ):
                        first_error = _error(
                            'detection',
                            filename,
                            exc,
                            settings=self.settings,
                        )
                        diagnostics.logger().warning(
                            '[%s] Retrying %s once after accelerator cleanup.',
                            first_error['diagnostic_id'],
                            filename,
                        )
                        self._operation_progress(0.0, 'retrying once after GPU memory cleanup')
                        root_detection.recover_accelerator_memory()
                        self._set_item(item, attempts=item['attempts'] + 1)
                        try:
                            result = self.detection_func(image_path, self.settings)
                            self._set_item(
                                item,
                                state='completed',
                                result=_serialize_detection(result),
                            )
                            continue
                        except jobs.OperationCancelled:
                            self._set_item(item, state='cancelled', result=None, error=None)
                            self._cancel_remaining()
                            break
                        except Exception as retry_exc:
                            exc = retry_exc
                    self._set_item(
                        item,
                        state='failed',
                        error=_error(
                            'detection',
                            filename,
                            exc,
                            settings=self.settings,
                        ),
                    )
                finally:
                    self._set_item(item, elapsed_seconds=time.time() - item_started_at)

            for item in self.pairs:
                if item['state'] != 'queued':
                    continue
                if self.cancel_event.is_set():
                    self._cancel_remaining()
                    break

                filename0 = item['filename0']
                filename1 = item['filename1']
                dependencies = [self.images[filename0], self.images[filename1]]
                if any(dependency['state'] != 'completed' for dependency in dependencies):
                    self._set_item(item, state='skipped', error={
                        'code': 'dependency_failed',
                        'message': 'Tracking requires two successfully detected images.',
                        'item_id': item['id'],
                        'stage': 'tracking',
                        'retryable': True,
                        'diagnostic_id': jobs.new_diagnostic_id(),
                    })
                    continue

                self._set_current('tracking', item['id'])
                item_started_at = time.time()
                self._set_item(
                    item,
                    state='tracking',
                    error=None,
                    attempts=item['attempts'] + 1,
                )
                try:
                    path0 = os.path.join(self.cache_path, filename0)
                    path1 = os.path.join(self.cache_path, filename1)
                    result = self.tracking_func(path0, path1, self.settings)
                    if isinstance(result, root_tracking.TooManyRootsError):
                        self._set_item(item, state='skipped', error={
                            'code': 'too_many_roots',
                            'message': 'Tracking was skipped because the configured root threshold was exceeded.',
                            'item_id': item['id'],
                            'stage': 'tracking',
                            'retryable': True,
                            'diagnostic_id': jobs.new_diagnostic_id(),
                        })
                    else:
                        state = 'completed' if result['success'] else 'review_required'
                        self._set_item(item, state=state, result=_serialize_tracking(result))
                except jobs.OperationCancelled:
                    self._set_item(item, state='cancelled', result=None, error=None)
                    self._cancel_remaining()
                    break
                except Exception as exc:
                    traceback.print_exc()
                    self._set_item(
                        item,
                        state='failed',
                        error=_error(
                            'tracking',
                            item['id'],
                            exc,
                            settings=self.settings,
                        ),
                    )
                finally:
                    self._set_item(item, elapsed_seconds=time.time() - item_started_at)
        except Exception as exc:
            traceback.print_exc()
            with self.lock:
                self.state = 'failed'
                self.current = {
                    'stage': 'pipeline',
                    'error': _error(
                        'pipeline',
                        self.id,
                        exc,
                        retryable=False,
                        settings=self.settings,
                    ),
                }
                self.updated_at = time.time()
            return

        with self.lock:
            self.current = None
            all_items = list(self.images.values()) + self.pairs
            if self.cancel_event.is_set():
                self.state = 'cancelled'
            elif any(item['state'] in ['failed', 'skipped', 'review_required'] for item in all_items):
                self.state = 'completed_with_errors'
            else:
                self.state = 'completed'
            self.updated_at = time.time()
        diagnostics.logger().info(
            'Pipeline %s finished with state %s.',
            self.id,
            self.state,
        )


class PipelineManager:
    def __init__(
        self,
        settings,
        cache_path:tp.Optional[str]=None,
        detection_func=None,
        tracking_func=None,
        max_runs:int=20,
    ):
        self.settings = settings
        self.cache_path = cache_path or get_cache_path()
        self.detection_func = detection_func
        self.tracking_func = tracking_func
        self.max_runs = max_runs
        self.runs = {}
        self.lock = threading.RLock()

    def create(self, filenames:tp.List[str], file_pairs:tp.List[tp.List[str]]) -> PipelineRun:
        filenames, pairs = self._validate(filenames, file_pairs)
        with self.lock:
            if any(run.state not in TERMINAL_RUN_STATES for run in self.runs.values()):
                raise RuntimeError('Another pipeline run is already active.')
            run = PipelineRun(
                filenames,
                pairs,
                self.settings,
                self.cache_path,
                detection_func=self.detection_func,
                tracking_func=self.tracking_func,
            )
            self.runs[run.id] = run
            self._discard_old_runs()
            run.start()
            return run

    def get(self, run_id:str) -> PipelineRun:
        with self.lock:
            try:
                return self.runs[run_id]
            except KeyError:
                raise KeyError('Pipeline run not found: {}'.format(run_id))

    def _discard_old_runs(self) -> None:
        if len(self.runs) <= self.max_runs:
            return
        candidates = sorted(
            (run for run in self.runs.values() if run.state in TERMINAL_RUN_STATES),
            key=lambda run: run.updated_at,
        )
        while len(self.runs) > self.max_runs and candidates:
            old = candidates.pop(0)
            self.runs.pop(old.id, None)

    def _validate(
        self,
        filenames:tp.Iterable[str],
        file_pairs:tp.Iterable[tp.Iterable[str]],
    ) -> tp.Tuple[tp.List[str], tp.List[tp.Tuple[str, str]]]:
        if not isinstance(filenames, (list, tuple)):
            raise ValueError('Input filenames must be a JSON array.')
        if file_pairs is not None and not isinstance(file_pairs, (list, tuple)):
            raise ValueError('Tracking pairs must be a JSON array.')
        filenames = list(filenames or [])
        if not filenames:
            raise ValueError('At least one input image is required.')
        if len(filenames) != len(set(filenames)):
            raise ValueError('Input filenames must be unique.')

        for filename in filenames:
            try:
                security.safe_resolve(
                    self.cache_path,
                    filename,
                    SUPPORTED_IMAGE_EXTENSIONS,
                    must_exist=True,
                )
            except security.ValidationError as exc:
                if exc.code == 'file_not_found':
                    raise ValueError('Uploaded input is missing: {}'.format(filename))
                if exc.code == 'unsupported_file_type':
                    raise ValueError(
                        'Unsupported input format for {}. Use PNG, JPEG, TIFF, or TIF.'.format(filename)
                    )
                raise ValueError(str(exc))

        pairs = []
        known = set(filenames)
        for raw_pair in file_pairs or []:
            if not isinstance(raw_pair, (list, tuple)):
                raise ValueError('Each tracking pair must be a two-item array.')
            pair = tuple(raw_pair)
            if len(pair) != 2 or pair[0] == pair[1]:
                raise ValueError('Each tracking pair must contain two different images.')
            if pair[0] not in known or pair[1] not in known:
                raise ValueError('Tracking pair references an unknown image.')
            pairs.append((pair[0], pair[1]))
        if len(pairs) != len(set(pairs)):
            raise ValueError('Tracking pairs must be unique.')
        return filenames, pairs
