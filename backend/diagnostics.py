"""Persistent, privacy-conscious diagnostics for local RootDetector runs."""

import datetime
import io
import json
import logging
import logging.handlers
import os
import platform
import sys
import traceback
import zipfile

from base.backend.paths import get_instance_path


LOGGER_NAME = 'rootdetector'
LOG_FOLDER_NAME = 'logs'
LOG_FILENAME = 'rootdetector.log'
MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 3


def get_log_folder():
    return os.path.join(get_instance_path(), LOG_FOLDER_NAME)


def get_log_path():
    return os.path.join(get_log_folder(), LOG_FILENAME)


def configure_logging():
    """Configure one rotating UTF-8 log file and return its logger."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    expected_path = os.path.abspath(get_log_path())
    for handler in list(logger.handlers):
        if os.path.abspath(getattr(handler, 'baseFilename', '')) == expected_path:
            return logger
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            logger.removeHandler(handler)
            handler.close()

    os.makedirs(get_log_folder(), exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        expected_path,
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUPS,
        encoding='utf-8',
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s %(threadName)s %(message)s'
    ))
    logger.addHandler(handler)
    logger.info('RootDetector diagnostics started.')
    return logger


def logger():
    return configure_logging()


def log_exception(diagnostic_id, stage, item_id, exc, settings=None):
    logger().error(
        '[%s] %s failed for %s: %s context=%s\n%s',
        diagnostic_id,
        stage,
        item_id,
        str(exc) or exc.__class__.__name__,
        json.dumps(system_snapshot(settings), sort_keys=True),
        ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    )


def _torch_details():
    try:
        import torch
        details = {
            'version': getattr(torch, '__version__', 'unknown'),
            'cuda_available': bool(torch.cuda.is_available()),
            'cuda_version': getattr(getattr(torch, 'version', None), 'cuda', None),
            'effective_inference_device': (
                'cuda' if torch.cuda.is_available() else 'cpu'
            ),
        }
        if details['cuda_available'] and details['cuda_version'] is None:
            details['runtime_note'] = (
                'The portable build loads CUDA runtime libraries at first launch; '
                'the packaged Python metadata can retain the original CPU build label.'
            )
        if details['cuda_available']:
            details['devices'] = [
                torch.cuda.get_device_name(index)
                for index in range(torch.cuda.device_count())
            ]
            details['memory'] = [
                {
                    'allocated_bytes': int(torch.cuda.memory_allocated(index)),
                    'reserved_bytes': int(torch.cuda.memory_reserved(index)),
                }
                for index in range(torch.cuda.device_count())
            ]
        return details
    except Exception as exc:
        return {'available': False, 'error_type': exc.__class__.__name__}


def system_snapshot(settings=None):
    """Return support metadata without environment variables or user images."""
    instance_path = get_instance_path()
    disk = {}
    try:
        usage = __import__('shutil').disk_usage(instance_path)
        disk = {
            'total_bytes': usage.total,
            'used_bytes': usage.used,
            'free_bytes': usage.free,
        }
    except OSError:
        pass

    selected_settings = {}
    if settings is not None:
        selected_settings = {
            'active_models': dict(getattr(settings, 'active_models', {})),
            'use_gpu': bool(getattr(settings, 'use_gpu', False)),
            'exmask_enabled': bool(getattr(settings, 'exmask_enabled', False)),
            'tracking_exclusion_mask_source': 'first_observation_warped',
        }

    return {
        'generated_utc': datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
        'platform': platform.platform(),
        'python': sys.version,
        'frozen': bool(getattr(sys, 'frozen', False)),
        'torch': _torch_details(),
        'disk': disk,
        'settings': selected_settings,
        'privacy': (
            'The snapshot excludes input images, results, environment variables, '
            'and absolute filesystem paths. Logs may contain filenames and technical paths.'
        ),
    }


def build_diagnostics_archive(settings=None):
    """Build a ZIP containing the system snapshot, build provenance, and logs."""
    active_logger = configure_logging()
    for handler in active_logger.handlers:
        handler.flush()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            'diagnostics.json',
            json.dumps(system_snapshot(settings), indent=2, sort_keys=True),
        )

        build_info = os.path.join(get_instance_path(), 'BUILD-INFO.txt')
        if os.path.isfile(build_info):
            archive.write(build_info, 'BUILD-INFO.txt')

        for index in range(LOG_BACKUPS, 0, -1):
            rotated = '{}.{}'.format(get_log_path(), index)
            if os.path.isfile(rotated):
                archive.write(rotated, 'logs/{}.{}'.format(LOG_FILENAME, index))
        if os.path.isfile(get_log_path()):
            archive.write(get_log_path(), 'logs/' + LOG_FILENAME)
    output.seek(0)
    return output
