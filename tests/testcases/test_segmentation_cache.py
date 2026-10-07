import json
import os

import numpy as np
import PIL.Image

from backend import root_detection
from backend import root_tracking


class FakeSettings:
    use_gpu = False
    exmask_enabled = False

    def __init__(self):
        self.active_models = {'detection': 'model-a', 'exclusion_mask': 'mask-a'}


def test_soft_segmentation_cache_reuse_and_invalidation(tmp_path, monkeypatch):
    image_path = str(tmp_path / 'input.png')
    PIL.Image.fromarray(np.zeros([8, 8, 3], dtype='uint8')).save(image_path)
    calls = []

    def run_model(path, settings, modeltype, **kwargs):
        calls.append((path, settings.active_models[modeltype], kwargs))
        return np.full([8, 8], 0.75, dtype='float32')

    monkeypatch.setattr(root_detection, 'run_model', run_model)
    settings = FakeSettings()

    preview, first = root_detection.ensure_soft_segmentation(image_path, settings)
    tracking_preview, second = root_tracking.ensure_segmentation(image_path, settings)
    assert preview == tracking_preview
    assert len(calls) == 1
    assert np.array_equal(first, second)

    paths = root_detection.segmentation_cache_paths(image_path, settings)
    assert all(os.path.exists(path) for path in paths.values())
    with open(paths['manifest']) as source:
        manifest = json.load(source)
    assert manifest['schema'] == root_detection.SEGMENTATION_CACHE_SCHEMA
    assert manifest['model']['name'] == 'model-a'
    assert manifest['operation']['storage_dtype'] == 'float32'
    assert manifest['artifact']['shape'] == [8, 8]
    assert manifest['artifact']['dtype'] == 'float32'
    assert len(manifest['artifact']['array_sha256']) == 64
    assert len(manifest['artifact']['preview_sha256']) == 64

    settings.active_models['detection'] = 'model-b'
    third_preview, _ = root_detection.ensure_soft_segmentation(image_path, settings)
    assert len(calls) == 2
    assert third_preview != preview

    PIL.Image.fromarray(np.ones([8, 8, 3], dtype='uint8')).save(image_path)
    fourth_preview, _ = root_detection.ensure_soft_segmentation(image_path, settings)
    assert len(calls) == 3
    assert fourth_preview != third_preview


def test_exclusionmask_cache_tracks_model_and_custom_mask_hashes(tmp_path, monkeypatch):
    image_path = str(tmp_path / 'input.png')
    PIL.Image.fromarray(np.zeros([8, 8, 3], dtype='uint8')).save(image_path)
    calls = []

    def run_model(path, settings, modeltype, **_kwargs):
        calls.append((path, settings.active_models[modeltype]))
        return np.ones([8, 8], dtype='float32')

    monkeypatch.setattr(root_detection, 'run_model', run_model)
    settings = FakeSettings()
    settings.exmask_enabled = True

    first = root_detection.maybe_compute_exclusionmask(image_path, settings)
    second = root_detection.maybe_compute_exclusionmask(image_path, settings)
    first_paths = root_detection.exclusionmask_cache_paths(image_path, settings)
    assert np.array_equal(first, second)
    assert len(calls) == 1
    assert first_paths is not None
    assert all(os.path.exists(path) for path in first_paths.values())

    settings.active_models['exclusion_mask'] = 'mask-b'
    root_detection.maybe_compute_exclusionmask(image_path, settings)
    second_paths = root_detection.exclusionmask_cache_paths(image_path, settings)
    assert len(calls) == 2
    assert second_paths != first_paths

    custom_path = str(tmp_path / 'input.exclusionmask.png')
    PIL.Image.fromarray(np.zeros([8, 8], dtype='uint8')).save(custom_path)
    custom = root_detection.maybe_compute_exclusionmask(image_path, settings)
    custom_paths = root_detection.exclusionmask_cache_paths(image_path, settings)
    assert len(calls) == 2
    assert custom is not None
    assert not custom.any()
    assert custom_paths != second_paths

    PIL.Image.fromarray(np.ones([8, 8], dtype='uint8') * 255).save(custom_path)
    changed = root_detection.maybe_compute_exclusionmask(image_path, settings)
    changed_paths = root_detection.exclusionmask_cache_paths(image_path, settings)
    assert changed is not None
    assert changed.all()
    assert changed_paths != custom_paths


def test_segmentation_cache_key_includes_model_file_hash(tmp_path, monkeypatch):
    image_path = str(tmp_path / 'input.png')
    PIL.Image.fromarray(np.zeros([8, 8, 3], dtype='uint8')).save(image_path)
    models_path = tmp_path / 'models'
    model_folder = models_path / 'detection'
    model_folder.mkdir(parents=True)
    model_path = model_folder / 'model-a.pt.zip'
    model_path.write_bytes(b'first model')
    monkeypatch.setattr(root_detection, 'get_models_path', lambda: str(models_path))
    settings = FakeSettings()

    first = root_detection.segmentation_cache_paths(image_path, settings)
    model_path.write_bytes(b'second model')
    second = root_detection.segmentation_cache_paths(image_path, settings)
    assert first != second


def test_segmentation_cache_recomputes_corrupt_artifact(tmp_path, monkeypatch):
    image_path = str(tmp_path / 'input.png')
    PIL.Image.fromarray(np.zeros([8, 8, 3], dtype='uint8')).save(image_path)
    calls = []

    def run_model(*_args, **_kwargs):
        calls.append(True)
        return np.full([8, 8], 0.5, dtype='float32')

    monkeypatch.setattr(root_detection, 'run_model', run_model)
    settings = FakeSettings()
    root_detection.ensure_soft_segmentation(image_path, settings)
    paths = root_detection.segmentation_cache_paths(image_path, settings)
    with open(paths['array'], 'wb') as output:
        output.write(b'corrupt')

    _, restored = root_detection.ensure_soft_segmentation(image_path, settings)
    assert len(calls) == 2
    assert np.array_equal(restored, np.full([8, 8], 0.5, dtype='float32'))
