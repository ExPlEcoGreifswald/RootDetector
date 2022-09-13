import os, glob, typing as tp
import numpy as np

import PIL.Image
from backend import postprocessing
import backend
from base.backend.pubsub import PubSub
from base.backend.app import get_cache_path

import torch


def run_model(image_path:str, settings:'backend.Settings', modeltype:str, **kwargs) -> np.ndarray:
    basename   = os.path.basename(image_path)
    device     = 'cuda' if settings.use_gpu and torch.cuda.is_available() else 'cpu'
    with backend.GLOBALS.processing_lock:
        progress_callback = lambda x: PubSub.publish({'progress':x, 'image':basename, 'stage':modeltype})
        model  = settings.models[modeltype].to(device)
        result = model.process_image(image_path, progress_callback=progress_callback, **kwargs)
        model.cpu()
    return result

def process_image(image_path:str, settings:'backend.Settings') -> dict:
    segmentation = run_model(image_path, settings, 'detection')
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


def paste_exmask(segmentation:np.ndarray, exmask:np.ndarray) -> np.ndarray:
    '''Combine two binary masks into a label map with classes 0,1,2'''
    exmask     = exmask.squeeze()
    TAPE_VALUE = 2
    return np.where(exmask>0, TAPE_VALUE, segmentation)

def maybe_compute_exclusionmask(image_path:str, settings:'backend.Settings') -> np.ndarray:
    '''Compute the exclusion mask if enabled or load a custom mask file'''
    exmask  = search_for_custom_maskfile(image_path)
    if settings.exmask_enabled and exmask is None:
        exmask   = run_model(image_path, settings, 'exclusion_mask')
    return exmask

def search_for_custom_maskfile(input_image_path:str) -> tp.Union[np.ndarray, None]:
    '''Search for a mask file that was manually uploaded by user in the same directory as input_image_path'''
    basename = os.path.splitext(os.path.basename(input_image_path))[0]
    pattern  = os.path.join( os.path.dirname(input_image_path), f'{basename}.exclusionmask.png')
    masks    = glob.glob(pattern)
    if len(masks)==1:
        mask = PIL.Image.open(masks[0]).convert('RGB') / np.float32(255)
        #convert rgb to binary array
        mask = np.any(mask, axis=-1)
        return mask

