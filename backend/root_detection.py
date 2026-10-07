import hashlib
import json
import os
import tempfile
import typing as tp
import numpy as np

import PIL.Image
from backend import postprocessing
from backend import jobs
import backend
from base.backend.pubsub import PubSub
from base.backend.app import get_cache_path, get_models_path

import torch


SEGMENTATION_CACHE_SCHEMA = 2
EXCLUSIONMASK_CACHE_SCHEMA = 1
_FILE_HASH_CACHE = {}
_FILE_HASH_CACHE_LIMIT = 32


def run_model(image_path:str, settings:tp.Any, modeltype:str, **kwargs) -> np.ndarray:
    basename   = os.path.basename(image_path)
    device     = 'cuda' if settings.use_gpu and torch.cuda.is_available() else 'cpu'
    jobs.raise_if_cancelled(settings)
    with backend.GLOBALS.processing_lock:
        def progress_callback(value):
            jobs.raise_if_cancelled(settings)
            PubSub.publish({'progress':value, 'image':basename, 'stage':modeltype})

        model = settings.models[modeltype]
        try:
            model.to(device)
            result = model.process_image(image_path, progress_callback=progress_callback, **kwargs)
            jobs.raise_if_cancelled(settings)
        finally:
            try:
                model.cpu()
            except Exception:
                pass
            if device == 'cuda':
                recover_accelerator_memory()
    return result


def is_retryable_accelerator_error(exc:Exception) -> bool:
    """Identify allocation failures for which one clean retry can be useful."""
    message = str(exc).lower()
    markers = (
        'cuda out of memory',
        'cudnn_status_alloc_failed',
        'cublas_status_alloc_failed',
        'cuda error: out of memory',
        'cuda error: memory allocation',
    )
    return any(marker in message for marker in markers)


def recover_accelerator_memory() -> None:
    """Release unreferenced CUDA allocations without masking cleanup errors."""
    if not torch.cuda.is_available():
        return
    try:
        torch.cuda.empty_cache()
        if hasattr(torch.cuda, 'ipc_collect'):
            torch.cuda.ipc_collect()
    except Exception:
        # The original inference failure remains the actionable error.
        pass


def _sha256(path:str) -> str:
    stat = os.stat(path)
    key = (
        os.path.realpath(path),
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )
    cached = _FILE_HASH_CACHE.get(key)
    if cached is not None:
        return cached

    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    value = digest.hexdigest()
    if len(_FILE_HASH_CACHE) >= _FILE_HASH_CACHE_LIMIT:
        _FILE_HASH_CACHE.pop(next(iter(_FILE_HASH_CACHE)))
    _FILE_HASH_CACHE[key] = value
    return value


def _model_identity(settings:tp.Any, modeltype:str='detection') -> dict:
    modelname = settings.active_models.get(modeltype, '')
    identity = {'name': modelname}
    for ending in ['.pt.zip', '.pt', '.pkl']:
        candidate = os.path.join(get_models_path(), modeltype, modelname + ending)
        if modelname and os.path.isfile(candidate):
            identity.update({
                'sha256': _sha256(candidate),
                'size': os.path.getsize(candidate),
            })
            break
    return identity


def _cache_key(manifest:dict) -> str:
    serialized = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(serialized).hexdigest()


def _artifact_cache_paths(image_path:str, kind:str, cache_key:str) -> dict:
    prefix = os.path.join(
        os.path.dirname(image_path),
        'rootdetector-{}-{}'.format(kind, cache_key),
    )
    return {
        'array': prefix + '.npy',
        'preview': prefix + '.png',
        'manifest': prefix + '.json',
    }


def segmentation_cache_manifest(image_path:str, settings:tp.Any) -> dict:
    return {
        'schema': SEGMENTATION_CACHE_SCHEMA,
        'kind': 'root-probability-map',
        'operation': {
            'name': 'soft-root-segmentation',
            'version': 1,
            'threshold': None,
            'storage_dtype': 'float32',
        },
        'input': {
            'name': os.path.basename(image_path),
            'sha256': _sha256(image_path),
            'size': os.path.getsize(image_path),
        },
        'model': _model_identity(settings, 'detection'),
    }


def segmentation_cache_paths(image_path:str, settings:tp.Any) -> dict:
    manifest = segmentation_cache_manifest(image_path, settings)
    return _artifact_cache_paths(image_path, 'segmentation', _cache_key(manifest))


def _custom_mask_path(input_image_path:str) -> tp.Optional[str]:
    basename = os.path.splitext(os.path.basename(input_image_path))[0]
    candidate = os.path.join(
        os.path.dirname(input_image_path),
        '{}.exclusionmask.png'.format(basename),
    )
    return candidate if os.path.isfile(candidate) else None


def exclusionmask_cache_manifest(
    image_path:str,
    settings:tp.Any,
) -> tp.Optional[dict]:
    custom_mask = _custom_mask_path(image_path)
    if custom_mask:
        source = {
            'kind': 'custom-mask',
            'name': os.path.basename(custom_mask),
            'sha256': _sha256(custom_mask),
            'size': os.path.getsize(custom_mask),
        }
    elif getattr(settings, 'exmask_enabled', False):
        source = {
            'kind': 'model',
            'model': _model_identity(settings, 'exclusion_mask'),
        }
    else:
        return None

    return {
        'schema': EXCLUSIONMASK_CACHE_SCHEMA,
        'kind': 'exclusion-mask',
        'operation': {
            'name': 'binary-exclusion-mask',
            'version': 1,
            'storage_dtype': 'float32',
        },
        'input': {
            'name': os.path.basename(image_path),
            'sha256': _sha256(image_path),
            'size': os.path.getsize(image_path),
        },
        'source': source,
    }


def exclusionmask_cache_paths(image_path:str, settings:tp.Any) -> tp.Optional[dict]:
    manifest = exclusionmask_cache_manifest(image_path, settings)
    if manifest is None:
        return None
    return _artifact_cache_paths(image_path, 'exclusionmask', _cache_key(manifest))


def _atomic_save_array(path:str, value:np.ndarray) -> None:
    folder = os.path.dirname(path) or '.'
    os.makedirs(folder, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.segmentation-', suffix='.npy', dir=folder)
    try:
        with os.fdopen(handle, 'wb') as output:
            np.save(output, np.asarray(value, dtype='float32'), allow_pickle=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _atomic_save_json(path:str, value:dict) -> None:
    folder = os.path.dirname(path) or '.'
    os.makedirs(folder, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.manifest-', suffix='.json', dir=folder)
    try:
        with os.fdopen(handle, 'w') as output:
            json.dump(value, output, sort_keys=True, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def ensure_soft_segmentation(image_path:str, settings:tp.Any) -> tp.Tuple[str, np.ndarray]:
    """Return a model-specific probability map, computing it only when stale."""
    expected = segmentation_cache_manifest(image_path, settings)
    cache_key = _cache_key(expected)
    paths = _artifact_cache_paths(image_path, 'segmentation', cache_key)

    try:
        with open(paths['manifest'], 'r') as source:
            actual = json.load(source)
        comparable_actual = {
            key: actual.get(key)
            for key in expected
        }
        if comparable_actual == expected and os.path.exists(paths['array']) and os.path.exists(paths['preview']):
            cached = np.load(paths['array'], allow_pickle=False)
            artifact = actual.get('artifact', {})
            artifact_valid = (
                artifact.get('shape') == list(cached.shape)
                and artifact.get('dtype') == str(cached.dtype)
                and artifact.get('array_sha256') == _sha256(paths['array'])
                and artifact.get('preview_sha256') == _sha256(paths['preview'])
            )
            if artifact_valid:
                return paths['preview'], cached.astype('float32')
    except (OSError, EOFError, ValueError, json.JSONDecodeError):
        pass

    segmentation = np.asarray(
        run_model(image_path, settings, 'detection', threshold=None),
        dtype='float32',
    )
    _atomic_save_array(paths['array'], segmentation)

    preview_tmp = paths['preview'] + '.tmp.png'
    try:
        backend.write_as_png(preview_tmp, segmentation)
        os.replace(preview_tmp, paths['preview'])
    finally:
        if os.path.exists(preview_tmp):
            os.remove(preview_tmp)
    manifest = dict(expected)
    manifest['cache_key'] = cache_key
    manifest['artifact'] = {
        'shape': list(segmentation.shape),
        'dtype': str(segmentation.dtype),
        'array_sha256': _sha256(paths['array']),
        'preview_sha256': _sha256(paths['preview']),
    }
    _atomic_save_json(paths['manifest'], manifest)
    return paths['preview'], segmentation

def process_image(image_path:str, settings:tp.Any) -> dict:
    _, probability = ensure_soft_segmentation(image_path, settings)
    segmentation = (probability > 0.5).astype('uint8')
    exmask       = maybe_compute_exclusionmask(image_path, settings)
    result       = paste_exmask(segmentation, exmask)
    result       = postprocess(result)
    return save_result(result, image_path)


def postprocess_segmentation_file(path:str) -> dict:
    assert path.endswith('.segmentation.png')
    image_path   = path.replace('.segmentation.png', '')
    segmentation = PIL.Image.open(path).convert('RGB') / np.float32(255)
    segmentation = result_from_rgb(segmentation)

    result = postprocess(segmentation)
    return save_result(result, image_path)


def postprocess(segmentation_result:np.ndarray) -> dict:
    skeleton           = postprocessing.skeletonize(segmentation_result)
    stats              = postprocessing.compute_statistics(segmentation_result, skeleton)
    segmentation_rgb   = result_to_rgb(segmentation_result)
    skeleton_rgb       = result_to_rgb(skeleton)

    return {
        'segmentation': segmentation_rgb,
        'skeleton'    : skeleton_rgb,
        'statistics'  : stats,
    }

def save_result(result:dict, image_path:str) -> dict:
    basename           = os.path.basename(image_path)
    output_folder      = get_cache_path()
    segmentation_fname = f'{basename}.segmentation.png'
    skeleton_fname     = f'{basename}.skeleton.png'
    segmentation_path  = os.path.join(output_folder, segmentation_fname)
    skeleton_path      = os.path.join(output_folder, skeleton_fname)
    
    backend.write_as_png(segmentation_path, result['segmentation'])
    backend.write_as_png(skeleton_path, result['skeleton'])

    return {
        'segmentation': segmentation_fname,
        'skeleton'    : skeleton_fname,
        'statistics'  : result['statistics'],
    }


def result_to_rgb(x:np.ndarray) -> np.ndarray:
    '''Convert a segmentation map with classes 0,1,2 to RGB format'''
    assert len(x.shape)==2
    x     = x[...,np.newaxis]
    WHITE = (1.,1.,1.)
    RED   = (1.,0.,0.)
    x     = (x==1) * WHITE   +  (x==2) * RED
    return x

def result_from_rgb(x:np.ndarray) -> np.ndarray:
    '''Convert a RGB array to a segmentation map with classes 0,1,2'''
    assert len(x.shape)==3
    WHITE  = (1.,1.,1.)
    RED    = (1.,0.,0.)
    result = (x == WHITE).all(-1) *1 \
           + (x == RED  ).all(-1) *2
    return result


def paste_exmask(segmentation:np.ndarray, exmask:tp.Union[np.ndarray,None]) -> np.ndarray:
    '''Combine two binary masks into a label map with classes 0,1,2'''
    if exmask is None:
        return segmentation
    exmask_array = np.asarray(exmask).squeeze()
    TAPE_VALUE = 2
    return np.where(exmask_array>0, TAPE_VALUE, segmentation)

def maybe_compute_exclusionmask(image_path:str, settings:tp.Any) -> tp.Optional[np.ndarray]:
    '''Return a content-addressed custom or model-generated exclusion mask.'''
    expected = exclusionmask_cache_manifest(image_path, settings)
    if expected is None:
        return None
    cache_key = _cache_key(expected)
    paths = _artifact_cache_paths(image_path, 'exclusionmask', cache_key)

    try:
        with open(paths['manifest'], 'r') as source:
            actual = json.load(source)
        comparable_actual = {key: actual.get(key) for key in expected}
        if comparable_actual == expected and os.path.exists(paths['array']):
            cached = np.load(paths['array'], allow_pickle=False)
            artifact = actual.get('artifact', {})
            artifact_valid = (
                artifact.get('shape') == list(cached.shape)
                and artifact.get('dtype') == str(cached.dtype)
                and artifact.get('array_sha256') == _sha256(paths['array'])
                and artifact.get('preview_sha256') == _sha256(paths['preview'])
            )
            if artifact_valid:
                return cached.astype('float32')
    except (OSError, EOFError, ValueError, json.JSONDecodeError):
        pass

    custom_mask = _custom_mask_path(image_path)
    if custom_mask:
        with PIL.Image.open(custom_mask) as image:
            mask = np.any(np.asarray(image.convert('RGB'), dtype='float32') / 255, axis=-1)
    else:
        mask = run_model(image_path, settings, 'exclusion_mask')
    mask = np.asarray(mask, dtype='float32').squeeze()
    _atomic_save_array(paths['array'], mask)

    preview_tmp = paths['preview'] + '.tmp.png'
    try:
        backend.write_as_png(preview_tmp, mask)
        os.replace(preview_tmp, paths['preview'])
    finally:
        if os.path.exists(preview_tmp):
            os.remove(preview_tmp)
    manifest = dict(expected)
    manifest['cache_key'] = cache_key
    manifest['artifact'] = {
        'shape': list(mask.shape),
        'dtype': str(mask.dtype),
        'array_sha256': _sha256(paths['array']),
        'preview_sha256': _sha256(paths['preview']),
    }
    _atomic_save_json(paths['manifest'], manifest)
    return mask

def search_for_custom_maskfile(input_image_path:str) -> tp.Union[np.ndarray, None]:
    '''Search for a mask file that was manually uploaded by user in the same directory as input_image_path'''
    mask_path = _custom_mask_path(input_image_path)
    if mask_path:
        mask = PIL.Image.open(mask_path).convert('RGB') / np.float32(255)
        #convert rgb to binary array
        mask = np.any(mask, axis=-1)
        return mask
