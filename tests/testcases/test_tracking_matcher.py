import threading

import numpy as np
import pytest
import torch

from backend import jobs
from backend import tracking_matcher


def descriptors(count, offset=0):
    values = torch.arange(
        offset,
        offset + count * 4,
        dtype=torch.float32,
    ).reshape(count, 1, 2, 2)
    return values / max(float(values.max()), 1.0)


def points(count):
    return np.asarray([
        [index * 100, (index % 3) * 100]
        for index in range(count)
    ], dtype='int64')


def test_matcher_provenance_is_versioned():
    assert tracking_matcher.provenance() == {
        'name': 'rootdetector-cancellable-bruteforce',
        'version': 1,
        'batch_size': 512,
        'algorithm_compatibility': 'released-2022-bruteforce',
    }


def test_descriptor_matching_is_deterministic_and_reports_each_batch():
    progress = []
    np.random.seed(7)
    first = tracking_matcher.match_descriptors(
        descriptors(9),
        descriptors(9, offset=4),
        points(9),
        points(9) + np.asarray([2, 3]),
        n=9,
        step=3,
        ratio_threshold=0,
        cyclic_threshold=1000,
        progress_callback=lambda value, phase: progress.append((value, phase)),
    )
    np.random.seed(7)
    second = tracking_matcher.match_descriptors(
        descriptors(9),
        descriptors(9, offset=4),
        points(9),
        points(9) + np.asarray([2, 3]),
        n=9,
        step=3,
        ratio_threshold=0,
        cyclic_threshold=1000,
    )

    for key in ['points0', 'points1', 'scores', 'ratios']:
        np.testing.assert_array_equal(first[key], second[key])
    assert [round(value, 3) for value, _phase in progress] == [0.333, 0.667, 1.0]
    assert progress[-1][1] == 'matching batch 3 of 3'


def test_descriptor_matching_cancels_before_the_next_batch():
    cancel_event = threading.Event()
    completed_batches = []

    def progress(value, phase):
        completed_batches.append((value, phase))
        cancel_event.set()

    with pytest.raises(jobs.OperationCancelled):
        tracking_matcher.match_descriptors(
            descriptors(12),
            descriptors(12, offset=4),
            points(12),
            points(12) + np.asarray([2, 3]),
            n=12,
            step=3,
            ratio_threshold=0,
            cyclic_threshold=1000,
            progress_callback=progress,
            cancellation_check=lambda: jobs.raise_if_cancelled(event=cancel_event),
        )

    assert len(completed_batches) == 1
    assert completed_batches[0][1] == 'matching batch 1 of 4'


def test_descriptor_matching_validates_batch_size():
    with pytest.raises(ValueError, match='batch size'):
        tracking_matcher.match_descriptors(
            descriptors(2),
            descriptors(2),
            points(2),
            points(2),
            n=2,
            step=0,
        )


def test_tracking_rejects_dimensions_that_overflow_point_coordinates():
    class Model:
        def compute_descriptors_at_points(self, *_args, **_kwargs):
            raise AssertionError('oversize inputs must fail before descriptor extraction')

    image = np.zeros((32769, 1, 3), dtype='uint8')
    segmentation = np.zeros((32769, 1), dtype='uint8')
    with pytest.raises(ValueError, match='32768 pixels'):
        tracking_matcher.match_images(Model(), image, image, segmentation, segmentation)


def test_descriptor_matching_rejects_coordinate_overflow():
    with pytest.raises(ValueError, match='16-bit image range'):
        tracking_matcher.match_descriptors(
            descriptors(2),
            descriptors(2),
            np.asarray([[0, 0], [32768, 0]]),
            np.asarray([[0, 0], [1, 0]]),
            n=2,
        )
