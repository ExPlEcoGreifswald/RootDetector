import os
import shutil
import zipfile

import numpy as np
import pytest

from backend.pipeline import PipelineManager
from backend import root_tracking
from backend import tracking_matcher
from backend.settings import Settings
from base.backend.app import get_cache_path, setup_cache
import torch


@pytest.fixture(scope='module')
def released_settings():
    return Settings()


@pytest.mark.real_model
def test_released_models_complete_detection_and_tracking_pipeline(released_settings):
    filenames = [
        'PD_T088_L004_17.10.18_140056_014_SS_crop.tiff',
        'PD_T088_L004_13.11.18_091057_015_SS_crop.tiff',
    ]
    setup_cache(get_cache_path())
    for filename in filenames:
        shutil.copy(
            os.path.join('tests', 'testcases', 'assets', filename),
            get_cache_path(filename),
        )

    manager = PipelineManager(released_settings, cache_path=get_cache_path())
    run = manager.create(filenames, [filenames])
    assert run.wait(180), 'real-model pipeline timed out'

    result = run.snapshot()
    assert result['state'] == 'completed'
    assert all(item['state'] == 'completed' for item in result['images'].values())
    assert result['pairs'][0]['state'] == 'completed'
    assert result['pairs'][0]['result']['success'] is True
    assert result['pairs'][0]['result']['n_matched_points'] >= 16
    assert result['pairs'][0]['result']['tracking_matcher'] == tracking_matcher.provenance()
    for item in result['images'].values():
        assert os.path.exists(get_cache_path(item['result']['segmentation']))
        assert os.path.exists(get_cache_path(item['result']['skeleton']))

    archive_name = root_tracking.compile_results_into_zip([filenames])
    archive_path = get_cache_path(archive_name)
    assert os.path.exists(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert 'statistics.csv' in names
        assert any(name.endswith('.growthmap.png') for name in names)
        assert any(name.endswith('.json') for name in names)


@pytest.mark.real_model
def test_cancellable_matcher_is_identical_to_released_descriptor_algorithm(
    released_settings,
):
    model = released_settings.models['tracking']
    method = getattr(model.match_images, '__func__', model.match_images)
    released_matcher = method.__globals__['bruteforce_match']

    torch.manual_seed(13)
    descriptors0 = torch.rand((24, 2, 4, 4), dtype=torch.float32)
    descriptors1 = torch.rand((24, 2, 4, 4), dtype=torch.float32)
    points0 = np.asarray([
        [index * 100, (index % 4) * 100]
        for index in range(24)
    ], dtype='int64')
    points1 = points0 + np.asarray([3, 5])

    np.random.seed(29)
    released = released_matcher(
        descriptors0,
        descriptors1,
        points0,
        points1,
        24,
        7,
        0,
        1000,
    )
    np.random.seed(29)
    cancellable = tracking_matcher.match_descriptors(
        descriptors0,
        descriptors1,
        points0,
        points1,
        n=24,
        step=7,
        ratio_threshold=0,
        cyclic_threshold=1000,
    )

    for key in ['points0', 'points1', 'scores', 'ratios']:
        np.testing.assert_array_equal(cancellable[key], released[key])
