"""Cancellable implementation of the released RootDetector matcher.

The released tracking package owns descriptor extraction, while this module
owns the deterministic point-matching loop. Version 1 intentionally preserves
the released 2022 algorithm and constants, adding only progress and
cancellation checkpoints.
"""

import copy
import typing as tp

import numpy as np
import skimage.morphology
import torch
import torchvision


MATCHER_NAME = 'rootdetector-cancellable-bruteforce'
MATCHER_VERSION = 1
DEFAULT_BATCH_SIZE = 512
MAX_TRACKING_DIMENSION = np.iinfo(np.int16).max + 1

ProgressCallback = tp.Callable[[float, str], None]
CancellationCheck = tp.Callable[[], None]


def provenance(batch_size:int=DEFAULT_BATCH_SIZE) -> tp.Dict[str, tp.Any]:
    return {
        'name': MATCHER_NAME,
        'version': MATCHER_VERSION,
        'batch_size': batch_size,
        'algorithm_compatibility': 'released-2022-bruteforce',
    }


def _empty_result() -> tp.Dict[str, tp.Any]:
    return {
        'points0': np.array([], 'int16').reshape(-1, 2),
        'points1': np.array([], 'int16').reshape(-1, 2),
        'scores': np.array([], 'float32'),
        'ratios': np.array([], 'float32'),
        'matched_percentage': 0,
        'success': False,
    }


def _check(callback:tp.Optional[CancellationCheck]) -> None:
    if callback is not None:
        callback()


def _progress(
    callback:tp.Optional[ProgressCallback],
    value:float,
    phase:str,
) -> None:
    if callback is not None:
        callback(max(0.0, min(1.0, float(value))), phase)


def sample_points_mixed(points, n_uniform:int, n_random:int) -> np.ndarray:
    """Preserve the released spatially uniform plus random sampling rule."""
    points = np.asarray(points)
    p_min, p_max = points.min(0), points.max(0)
    grid_size = int(np.ceil(n_uniform ** 0.5))
    grid = np.stack(
        np.meshgrid(*np.linspace(p_min, p_max, grid_size).T, indexing='ij'),
        -1,
    ).reshape(-1, 2)
    distances = ((grid[:, None] - points[None]) ** 2).sum(-1)
    result = distances.argmin(1)
    result = np.concatenate([result, np.random.permutation(len(points))[:n_random]])
    return np.unique(result)


def filter_points(p0, p1, threshold:int=50) -> tp.Tuple[np.ndarray, np.ndarray]:
    delta = p1 - p0
    median = np.median(delta, axis=0)
    deviation = ((delta - median) ** 2).sum(-1) ** 0.5
    accepted = deviation < threshold
    return p0[accepted], p1[accepted]


def compute_descriptor_similarities(
    descriptors0:torch.Tensor,
    descriptors1:torch.Tensor,
) -> torch.Tensor:
    channels = descriptors0.shape[2]
    similarities = torch.einsum(
        'nchw,mchw->nm',
        descriptors0,
        descriptors1,
    ).cpu().float() / channels ** 2
    return similarities / 2 + 0.5


def compute_similarity_ratios(
    similarity_matrix:torch.Tensor,
    all_points:np.ndarray,
    matched_points:np.ndarray,
    threshold:int=64,
) -> np.ndarray:
    matched_similarity = similarity_matrix.max(-1)[0]
    point_distances = np.abs(all_points[None] - matched_points[:, None]).max(-1)
    alternatives = similarity_matrix.clone().numpy()
    alternatives[point_distances < threshold] = 0
    reverse_similarity = alternatives.max(-1)
    return matched_similarity / reverse_similarity


def compute_cyclic_distances(
    matched_descriptors1:torch.Tensor,
    descriptors0:torch.Tensor,
    all_points0:np.ndarray,
    batch_points0:np.ndarray,
) -> np.ndarray:
    cyclic_similarities = compute_descriptor_similarities(
        matched_descriptors1,
        descriptors0,
    )
    cyclic_points0 = all_points0[cyclic_similarities.argmax(-1)]
    return np.sum((cyclic_points0 - batch_points0) ** 2, axis=-1) ** 0.5


def match_descriptors(
    descriptors0:torch.Tensor,
    descriptors1:torch.Tensor,
    points0:np.ndarray,
    points1:np.ndarray,
    n:int,
    step:int=DEFAULT_BATCH_SIZE,
    ratio_threshold:float=1.1,
    cyclic_threshold:float=4,
    progress_callback:tp.Optional[ProgressCallback]=None,
    cancellation_check:tp.Optional[CancellationCheck]=None,
) -> tp.Dict[str, tp.Any]:
    """Match released-model descriptors with a checkpoint per batch."""
    if step < 1:
        raise ValueError('Tracking batch size must be at least 1.')
    points0 = np.asarray(points0)
    points1 = np.asarray(points1)
    if len(descriptors0) != len(points0) or len(descriptors1) != len(points1):
        raise ValueError('Descriptor and point counts must match.')
    if any(
        np.any(points < 0) or np.any(points >= MAX_TRACKING_DIMENSION)
        for points in (points0, points1)
    ):
        raise ValueError('Tracking coordinates exceed the supported 16-bit image range.')

    _check(cancellation_check)
    n = min(n, len(descriptors0), len(descriptors1))
    sampled_indices = sample_points_mixed(
        points0,
        n_uniform=512,
        n_random=n,
    )[:n]
    result = copy.deepcopy(_empty_result())
    starts = list(range(0, n - 1, step))
    total_batches = max(len(starts), 1)

    for batch_number, start in enumerate(starts):
        _check(cancellation_check)
        batch_indices = sampled_indices[start:][:step]
        batch_descriptors0 = descriptors0[batch_indices]
        batch_points0 = points0[batch_indices]

        similarity_matrix = compute_descriptor_similarities(
            batch_descriptors0,
            descriptors1,
        )
        matched_indices = similarity_matrix.argmax(-1)
        matched_points1 = points1[matched_indices]
        matched_similarity = similarity_matrix.max(-1)[0]

        similarity_ratios = compute_similarity_ratios(
            similarity_matrix,
            points1,
            matched_points1,
        )
        accepted_ratio = similarity_ratios > ratio_threshold

        cyclic_distances = compute_cyclic_distances(
            descriptors1[matched_indices],
            descriptors0,
            points0,
            batch_points0,
        )
        accepted_cycle = cyclic_distances < cyclic_threshold
        accepted = np.array(accepted_ratio & accepted_cycle).astype(bool)

        result['points0'] = np.concatenate([
            result['points0'],
            batch_points0[accepted],
        ]).astype('int16')
        result['points1'] = np.concatenate([
            result['points1'],
            matched_points1[accepted],
        ]).astype('int16')
        result['scores'] = np.concatenate([
            result['scores'],
            matched_similarity[accepted],
        ])
        result['ratios'] = np.concatenate([
            result['ratios'],
            similarity_ratios[accepted],
        ])

        _check(cancellation_check)
        _progress(
            progress_callback,
            (batch_number + 1) / total_batches,
            'matching batch {} of {}'.format(batch_number + 1, total_batches),
        )

    return result


def match_images(
    model:tp.Any,
    image0:torch.Tensor,
    image1:torch.Tensor,
    segmentation0:np.ndarray,
    segmentation1:np.ndarray,
    n:int=5000,
    ratio_threshold:float=1.1,
    cyclic_threshold:float=4,
    device:str='cpu',
    step:int=DEFAULT_BATCH_SIZE,
    progress_callback:tp.Optional[ProgressCallback]=None,
    cancellation_check:tp.Optional[CancellationCheck]=None,
) -> tp.Dict[str, tp.Any]:
    """Extract descriptors with released weights, then match cancellably."""
    if not hasattr(model, 'compute_descriptors_at_points'):
        raise TypeError(
            'The selected tracking model does not expose descriptor extraction.'
        )
    if len(image0.shape) != 3 or len(image1.shape) != 3:
        raise ValueError('Tracking images must have three dimensions.')
    if len(segmentation0.shape) != 2 or len(segmentation1.shape) != 2:
        raise ValueError('Tracking segmentations must have two dimensions.')
    image0_shape = image0.shape[-2:] if torch.is_tensor(image0) else image0.shape[:2]
    image1_shape = image1.shape[-2:] if torch.is_tensor(image1) else image1.shape[:2]
    if any(
        dimension > MAX_TRACKING_DIMENSION
        for shape in (image0_shape, image1_shape, segmentation0.shape, segmentation1.shape)
        for dimension in shape
    ):
        raise ValueError(
            'Tracking does not support images larger than {} pixels on either axis. '
            'Prepare a smaller, consistent region of interest before tracking.'.format(
                MAX_TRACKING_DIMENSION
            )
        )

    _check(cancellation_check)
    image0 = (
        torchvision.transforms.ToTensor()(image0)
        if not torch.is_tensor(image0)
        else image0
    )
    image1 = (
        torchvision.transforms.ToTensor()(image1)
        if not torch.is_tensor(image1)
        else image1
    )
    skeleton0 = skimage.morphology.skeletonize(np.asarray(segmentation0) > 0.5)
    skeleton1 = skimage.morphology.skeletonize(np.asarray(segmentation1) > 0.5)
    points0 = np.argwhere(skeleton0)
    points1 = np.argwhere(skeleton1)
    _check(cancellation_check)
    _progress(progress_callback, 0.05, 'preparing root points')

    if len(points0) == 0 or len(points1) == 0:
        return _empty_result()

    descriptor_size = 16
    try:
        with torch.no_grad():
            descriptors0 = model.compute_descriptors_at_points(
                image0,
                points0,
                device,
                box_size=64,
                dsc_size=descriptor_size,
            )
            _check(cancellation_check)
            _progress(progress_callback, 0.25, 'descriptors for observation 1')
            descriptors1 = model.compute_descriptors_at_points(
                image1,
                points1,
                device,
                box_size=64,
                dsc_size=descriptor_size,
            )
            _check(cancellation_check)
            _progress(progress_callback, 0.50, 'descriptors for observation 2')

        model.cpu()
        if device == 'cuda':
            torch.cuda.empty_cache()

        def matching_progress(value:float, phase:str) -> None:
            _progress(progress_callback, 0.50 + value * 0.45, phase)

        result = match_descriptors(
            descriptors0,
            descriptors1,
            points0,
            points1,
            n,
            step=step,
            ratio_threshold=ratio_threshold,
            cyclic_threshold=cyclic_threshold,
            progress_callback=matching_progress,
            cancellation_check=cancellation_check,
        )
        result['matched_percentage'] = len(result['points0']) / np.int32(len(points0))
        filtered0, filtered1 = filter_points(result['points0'], result['points1'])
        result['points0'] = filtered0
        result['points1'] = filtered1
        _check(cancellation_check)
        _progress(progress_callback, 1.0, 'filtering matched points')
        return result
    finally:
        model.cpu()
        if device == 'cuda':
            torch.cuda.empty_cache()
