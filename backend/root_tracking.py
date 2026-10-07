import csv
import io
import json
import os
import typing as tp
import warnings
import zipfile
import torch, torchvision
import numpy as np
import scipy.ndimage
import PIL.Image
import skimage.morphology

from backend import GLOBALS
from backend import jobs
from backend import postprocessing
from backend import root_detection
from backend import tracking_matcher
from base.backend.pubsub import PubSub
from base.backend import paths


class TooManyRootsError:
    """Sentinel returned when tracking is intentionally skipped for safety."""


TOO_MANY_ROOTS_ERROR = TooManyRootsError()
TrackingStatus = tp.Union[bool, TooManyRootsError]
TrackingResult = tp.Dict[str, tp.Any]
FilePairs = tp.Sequence[tp.Sequence[str]]
TRACKING_CSV_SCHEMA = 2
DEFAULT_EXCLUSION_MASK_POLICY = 'first'
TRACKING_CSV_FIELDS = [
    'Filename 1', 'Filename 2',
    'same pixels', 'decay pixels', 'growth pixels',
    'background pixels', 'mask pixels',
    'same skeleton pixels', 'decay skeleton pixels', 'growth skeleton pixels',
    'same kimura length', 'decay kimura length', 'growth kimura length',
    'status',
]



def process(
    filename0:str,
    filename1:str,
    settings:tp.Any,
    previous_data:tp.Optional[tp.Dict[str, tp.Any]]=None,
) -> tp.Union[TrackingResult, TooManyRootsError]:
    print(f'Performing root tracking on files {filename0} and {filename1}')
    jobs.raise_if_cancelled(settings)
    matchmodel = settings.models['tracking']

    seg0f, seg0 = ensure_segmentation(filename0, settings)
    jobs.raise_if_cancelled(settings)
    seg1f, seg1 = ensure_segmentation(filename1, settings)
    jobs.raise_if_cancelled(settings)
    validate_tracking_pair_shapes(seg0, seg1)
    TOO_MANY_ROOTS_THRESHOLD = settings.too_many_roots
    if should_skip_because_too_many_roots(seg0, seg1, TOO_MANY_ROOTS_THRESHOLD):
        cache_output_for_download(filename0, filename1, TOO_MANY_ROOTS_ERROR, {})
        return TOO_MANY_ROOTS_ERROR
    
    exmask0 = ensure_exclusionmask(filename0, settings)
    jobs.raise_if_cancelled(settings)

    outputname  = f'{filename0}.{os.path.basename(filename1)}'
    
    if previous_data is None:  #FIXME: better condition?
        img0    = torchvision.transforms.ToTensor()(PIL.Image.open(filename0))
        img1    = torchvision.transforms.ToTensor()(PIL.Image.open(filename1))
        with GLOBALS.processing_lock:
            jobs.raise_if_cancelled(settings)
            device  = 'cuda' if settings.use_gpu and torch.cuda.is_available() else 'cpu'
            def on_progress(value, phase):
                jobs.raise_if_cancelled(settings)
                operation_callback = getattr(
                    settings,
                    'operation_progress_callback',
                    None,
                )
                if operation_callback is not None:
                    operation_callback(value, phase)
                PubSub.publish({
                    'progress': value,
                    'image': '{} -> {}'.format(
                        os.path.basename(filename0),
                        os.path.basename(filename1),
                    ),
                    'stage': 'tracking',
                    'description': phase,
                })

            output = tracking_matcher.match_images(
                matchmodel,
                img0,
                img1,
                seg0,
                seg1,
                n=5000,
                cyclic_threshold=4,
                device=device,
                progress_callback=on_progress,
                cancellation_check=lambda: jobs.raise_if_cancelled(settings),
            )
            jobs.raise_if_cancelled(settings)
            print()
            print(len(output['points0']))
            print('Matched percentage:', output['matched_percentage'])
            print()
            output['success'] = success = (len(output['points0'])>=16)
            output['n_matched_points'] = len(output['points0'])
            output['tracking_model']     = settings.active_models['tracking']
            output['segmentation_model'] = settings.active_models['detection']
            output['tracking_matcher'] = tracking_matcher.provenance()
    else:
        output      = {
            'points0'            : np.asarray(previous_data['points0']).reshape(-1,2),
            'points1'            : np.asarray(previous_data['points1']).reshape(-1,2),
            'n_matched_points'   : previous_data['n_matched_points'],
            'tracking_model'     : previous_data['tracking_model'],
            'segmentation_model' : previous_data['segmentation_model'],
            'tracking_matcher'   : previous_data.get('tracking_matcher', {
                'name': 'released-model-internal-matcher',
                'version': 0,
            }),
        }
        corrections = np.array(previous_data['corrections']).reshape(-1,4)
        if len(corrections)>0:
            imap   = np.load(f'{outputname}.imap.npy').astype('float32')
            corrections_p0 = corrections[:,:2][:,::-1] #xy to yx
            corrections_p1 = corrections[:,2:][:,::-1]
            corrections_p0 = np.stack([
                scipy.ndimage.map_coordinates(imap[...,0], corrections_p0.T, order=1),
                scipy.ndimage.map_coordinates(imap[...,1], corrections_p0.T, order=1),
            ], axis=-1)
            output['points0'] = np.concatenate([output['points0'], corrections_p0])
            output['points1'] = np.concatenate([output['points1'], corrections_p1])
        success = output['success'] = (len(output['points1'])>=1)
    
    if success:
        imap    = matchmodel.interpolation_map(output['points1'], output['points0'], seg0.shape)
    else:
        #dummy interpolation map
        imap    = matchmodel.interpolation_map(np.zeros([1,2]), np.zeros([1,2]), seg0.shape)
    jobs.raise_if_cancelled(settings)
    
    np.save(f'{outputname}.imap.npy', imap.astype('float16'))  #f16 to save space & time

    warped_seg0    = matchmodel.warp(seg0, imap)
    warped_exmask0 = None
    if exmask0 is not None:
        warped_exmask0 = matchmodel.warp(exmask0, imap)
    gmap           = matchmodel.create_growth_map_rgba( warped_seg0>0.5, seg1>0.5, )
    gmap           = paste_exclusionmask(gmap, warped_exmask0)
    jobs.raise_if_cancelled(settings)

    output_file_rgb  = f'{outputname}.growthmap.png'
    output_file_rgba = f'{outputname}.growthmap_rgba.png'
    PIL.Image.fromarray(gmap).convert('RGB').save( output_file_rgb )
    PIL.Image.fromarray(gmap).save( output_file_rgba )

    output['growthmap']      = output_file_rgb
    output['growthmap_rgba'] = output_file_rgba
    output['segmentation0']  = seg0f
    output['segmentation1']  = seg1f
    output['exclusion_mask_policy'] = DEFAULT_EXCLUSION_MASK_POLICY
    output['exclusion_masks'] = {
        'observation0_present': exmask0 is not None,
        'observation1_present': False,
        'observation0_pixels': _mask_pixel_count(exmask0),
        'observation1_pixels': 0,
        'combined_pixels': _mask_pixel_count(warped_exmask0),
    }

    output['statistics']     = compute_statistics(gmap)
    
    cache_output_for_download(filename0, filename1, success, output)
    return output


def ensure_segmentation(input_image_path:str, settings:tp.Any) -> tp.Tuple[str, np.ndarray]:
    '''Run root detection (without a threshold) or load a cached result'''
    return root_detection.ensure_soft_segmentation(input_image_path, settings)


def ensure_exclusionmask(input_image_path:str, settings:tp.Any) -> tp.Optional[np.ndarray]:
    '''Return the released observation-1 exclusion mask for tracking.'''
    return root_detection.maybe_compute_exclusionmask(input_image_path, settings)


def validate_tracking_pair_shapes(
    segmentation0:np.ndarray,
    segmentation1:np.ndarray,
) -> tp.Tuple[int, ...]:
    """Require comparable pixel grids before matching or turnover analysis."""
    shape0 = tuple(np.asarray(segmentation0).squeeze().shape)
    shape1 = tuple(np.asarray(segmentation1).squeeze().shape)
    if len(shape0) != 2 or len(shape1) != 2:
        raise ValueError(
            'Tracking requires two-dimensional segmentations; received {} and {}.'.format(
                shape0,
                shape1,
            )
        )
    if shape0 != shape1:
        raise ValueError(
            'Tracking requires images with identical pixel dimensions; received '
            '{} and {}. Use comparable scans of the same location, or explicitly '
            'align and crop copies before tracking while preserving the originals '
            'and transformation record.'.format(shape0, shape1)
        )
    return shape0


def _mask_pixel_count(mask:tp.Optional[np.ndarray]) -> int:
    if mask is None:
        return 0
    return int((np.asarray(mask).squeeze() > 0.5).sum())


class COLORS:
    NEGATIVE = ( 39, 54, 59,  0)
    SAME     = (255,255,255,255)
    DECAY    = (226,106,116,255)
    GROWTH   = ( 96,209,130,255)
    EXMASK   = (255,  0,  0,255)

def paste_exclusionmask(turnovermap_rgba:np.ndarray, exmask:tp.Union[np.ndarray, None]) -> np.ndarray:
    if exmask is None:
        return turnovermap_rgba
    return np.where(np.asarray(exmask)[...,None]>0.5, COLORS.EXMASK, turnovermap_rgba).astype('uint8')


def skeletonized_turnovermap(gmap):
    seg0w = (gmap==1) | (gmap==2)  #warped segmentation 0 = same+decay
    seg1  = (gmap==1) | (gmap==3)  #segmentation 1        = same+growth
    sk0   = skimage.morphology.skeletonize(seg0w)
    sk1   = skimage.morphology.skeletonize(seg1)
    return np.stack([
        np.zeros_like(sk0),
        (sk1 == 1) & (gmap == 1),
        (sk0 == 1) & (gmap == 2),
        (sk1 == 1) & (gmap == 3),
    ]).argmax(0)

def turnovermap_from_rgba(rgba:np.ndarray) -> np.ndarray:
    '''Convert a RGBA encoded turnover map into a labeled array
       with classes 0(negative),1(same),2(decay),3(growth),4(exclude)'''
    
    return np.stack([
        (rgba == COLORS.NEGATIVE).all(-1),
        (rgba == COLORS.SAME).all(-1),
        (rgba == COLORS.DECAY).all(-1),
        (rgba == COLORS.GROWTH).all(-1),
        (rgba == COLORS.EXMASK).all(-1),
    ]).argmax(0)


def compute_statistics(turnovermap_rgba):
    turnovermap    = turnovermap_from_rgba(turnovermap_rgba)
    turnovermap_sk = skeletonized_turnovermap(turnovermap)

    kimura_same   = postprocessing.kimura_length(turnovermap_sk==1)
    kimura_decay  = postprocessing.kimura_length(turnovermap_sk==2)
    kimura_growth = postprocessing.kimura_length(turnovermap_sk==3)

    return {
        'sum_same' :        int( (turnovermap==1).sum() ),
        'sum_decay' :       int( (turnovermap==2).sum() ),
        'sum_growth':       int( (turnovermap==3).sum() ),
        'sum_negative':     int( (turnovermap==0).sum() ),
        'sum_exmask':       int( (turnovermap==4).sum() ),

        'sum_same_sk' :     int( (turnovermap_sk==1).sum() ),
        'sum_decay_sk' :    int( (turnovermap_sk==2).sum() ),
        'sum_growth_sk':    int( (turnovermap_sk==3).sum() ),
        'sum_negative_sk':  int( (turnovermap_sk==0).sum() ),

        'kimura_same':      int( kimura_same ),
        'kimura_decay':     int( kimura_decay ),
        'kimura_growth':    int( kimura_growth ),
    }

def should_skip_because_too_many_roots(
    seg0:np.ndarray, 
    seg1:np.ndarray, 
    threshold:int
) -> bool:
    n_roots0 = skimage.morphology.skeletonize(seg0>0.5).sum()
    n_roots1 = skimage.morphology.skeletonize(seg1>0.5).sum()
    return (n_roots0 > threshold) or (n_roots1 > threshold)


def cache_output_for_download(
    filename0: str,
    filename1: str,
    success:   TrackingStatus,
    output:    tp.Dict[str, tp.Any],
) -> None:
    dirname     =   paths.get_cache_path()
    filename0   =   os.path.basename(filename0)
    filename1   =   os.path.basename(filename1)
    outputname  =   os.path.join(dirname, f'{filename0}.{filename1}')
    
    open(f'{outputname}.csv', 'w').write(
        statistics_to_csv(
            output.get('statistics', {}),
            filename0, 
            filename1, 
            success
        )
    )

    if isinstance(success, TooManyRootsError):
        return

    open(f'{outputname}.json', 'w').write(
        json.dumps({
            'filename0'             : filename0,
            'filename1'             : filename1,
            'points0'               : output['points0'].tolist(),
            'points1'               : output['points1'].tolist(),
            'n_matched_points'      : output['n_matched_points'],
            'tracking_model'        : output['tracking_model'],
            'segmentation_model'    : output['segmentation_model'],
            'tracking_matcher'      : output['tracking_matcher'],
            'segmentation0'         : os.path.basename(output['segmentation0']),
            'segmentation1'         : os.path.basename(output['segmentation1']),
            'growthmap'             : os.path.basename(output['growthmap']),
            'exclusion_mask_policy' : output['exclusion_mask_policy'],
            'exclusion_masks'       : output['exclusion_masks'],
        })
    )


def _statistics_record(
    stats:tp.Dict[str, tp.Any],
    filename0:str,
    filename1:str,
    success:TrackingStatus,
) -> tp.Dict[str, tp.Any]:
    status_map = {
        True: 'OK',
        False: 'WARNING: No matching roots found',
        TOO_MANY_ROOTS_ERROR: 'SKIPPED: Too many roots',
    }
    return {
        'Filename 1': filename0,
        'Filename 2': filename1,
        'same pixels': stats.get('sum_same', ''),
        'decay pixels': stats.get('sum_decay', ''),
        'growth pixels': stats.get('sum_growth', ''),
        'background pixels': stats.get('sum_negative', ''),
        'mask pixels': stats.get('sum_exmask', ''),
        'same skeleton pixels': stats.get('sum_same_sk', ''),
        'decay skeleton pixels': stats.get('sum_decay_sk', ''),
        'growth skeleton pixels': stats.get('sum_growth_sk', ''),
        'same kimura length': stats.get('kimura_same', ''),
        'decay kimura length': stats.get('kimura_decay', ''),
        'growth kimura length': stats.get('kimura_growth', ''),
        'status': status_map[success],
    }

def statistics_to_csv(
    stats:     tp.Dict[str, tp.Any],
    filename0: str,
    filename1: str,
    success:   TrackingStatus,
    include_header=True
) -> str:
    '''Convert statistics from Python dicts as computed in process() to CSV'''
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=TRACKING_CSV_FIELDS, extrasaction='raise')
    if include_header:
        writer.writeheader()
    writer.writerow(_statistics_record(stats, filename0, filename1, success))
    return output.getvalue()


def collect_result_files(filename0:str, filename1:str) -> tp.Optional[tp.List[str]]:
    cache_path = paths.get_cache_path()
    metadata_path = os.path.join(cache_path, f'{filename0}.{filename1}.json')
    try:
        with open(metadata_path, 'r') as source:
            metadata = json.load(source)
    except (OSError, ValueError, json.JSONDecodeError):
        return None

    segmentation0 = metadata.get('segmentation0', filename0 + '.segmentation.cache.png')
    segmentation1 = metadata.get('segmentation1', filename1 + '.segmentation.cache.png')
    growthmap = metadata.get('growthmap', f'{filename0}.{filename1}.growthmap.png')
    files = [
        os.path.join(cache_path, os.path.basename(segmentation0)),
        os.path.join(cache_path, os.path.basename(segmentation1)),
        os.path.join(cache_path, os.path.basename(growthmap)),
        os.path.join(cache_path, f'{filename0}.{filename1}.csv'),
        metadata_path,

    ]
    if all(map(os.path.exists, files)):
        return files
    #else: return None

def combine_csv_statistics(file_pairs:FilePairs) -> str:
    cache_path         = paths.get_cache_path()
    combined = io.StringIO(newline='')
    writer = csv.writer(combined)
    header_written = False
    for filename0, filename1 in file_pairs:
        csv_file   = os.path.join(cache_path, f'{filename0}.{filename1}.csv')
        with open(csv_file, 'r', newline='') as source:
            rows = list(csv.reader(source))
        if len(rows) < 2:
            warnings.warn('Skipping incomplete tracking CSV: {}'.format(csv_file))
            continue
        if rows[0] != TRACKING_CSV_FIELDS:
            warnings.warn(
                'Skipping tracking CSV with an unsupported or legacy schema: {}'.format(csv_file)
            )
            continue
        if not header_written:
            writer.writerow(rows[0])
            header_written = True
        for row in rows[1:]:
            if len(row) != len(TRACKING_CSV_FIELDS):
                warnings.warn('Skipping malformed tracking CSV row in {}'.format(csv_file))
                continue
            writer.writerow(row)
    return combined.getvalue()

    

def compile_results_into_zip(file_pairs:FilePairs) -> str:
    '''Create a zip file containing the processed tracking results.
       (Doing this here in Python because frontend passes out if too many files)'''
    
    cache_path = paths.get_cache_path()
    resultpath = os.path.join(cache_path, 'tracking_results.zip')
    pair_exclusion_masks = []
    with zipfile.ZipFile(resultpath, 'w') as resultzip:
        for filename0, filename1 in file_pairs:
            outputname   = f'{filename0}.{filename1}'
            result_files = collect_result_files(filename0, filename1)
            if result_files is None:
                print(f'[ERROR] could not find tracking results for {outputname}')
                continue

            archive_names = [
                filename0 + '.segmentation.cache.png',
                filename1 + '.segmentation.cache.png',
            ] + [os.path.basename(path) for path in result_files[2:]]
            for path, archive_name in zip(result_files, archive_names):
                resultzip.write(path, os.path.join(outputname, archive_name))
            try:
                with open(os.path.join(cache_path, f'{filename0}.{filename1}.json'), 'r') as source:
                    pair_metadata = json.load(source)
                pair_exclusion_masks.append({
                    'filename0': filename0,
                    'filename1': filename1,
                    'policy': pair_metadata.get(
                        'exclusion_mask_policy',
                        DEFAULT_EXCLUSION_MASK_POLICY,
                    ),
                    'masks': pair_metadata.get('exclusion_masks'),
                    'matcher': pair_metadata.get('tracking_matcher'),
                })
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        combined_stats = combine_csv_statistics(file_pairs)
        resultzip.writestr('statistics.csv', combined_stats)
        resultzip.writestr(
            'tracking-results-manifest.json',
            json.dumps({
                'tracking_csv_schema': TRACKING_CSV_SCHEMA,
                'exclusion_mask_coordinate_system': 'observation1',
                'pair_exclusion_masks': pair_exclusion_masks,
                'tracking_matcher_schema': 1,
                'migration_warning': (
                    'Tracking CSV files exported by RootDetector before schema 2 may have '
                    'background, mask, same, decay, and growth values under incorrect headers. '
                    'Re-export those analyses before comparing or aggregating them.'
                ),
            }, indent=2, sort_keys=True),
        )
    return os.path.basename(resultpath)
