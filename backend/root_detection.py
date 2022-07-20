import os, glob
import numpy as np

import PIL.Image
from backend import postprocessing
import backend
from base.backend.pubsub import PubSub
from base.backend.app import get_cache_path

import torch

def process_image(image_path, settings,  no_exmask=False, **kwargs):
    basename      = os.path.basename(image_path)
    output_folder = get_cache_path()

    device = 'cuda' if settings.use_gpu and torch.cuda.is_available() else 'cpu'
    with backend.GLOBALS.processing_lock:
        progress_callback   = lambda x: PubSub.publish({'progress':x, 'image':os.path.basename(image_path), 'stage':'roots'})
        segmentation_model  = settings.models['detection'].to(device)
        segmentation_result = segmentation_model.process_image(image_path, progress_callback=progress_callback)
        segmentation_model.cpu()

        if settings.exmask_enabled and not no_exmask:
            progress_callback = lambda x: PubSub.publish({'progress':x, 'image':os.path.basename(image_path), 'stage':'mask'})
            exmask_model  = settings.models['exclusion_mask'].to(device)
            exmask_result = exmask_model.process_image(image_path, progress_callback=progress_callback)
            exmask_model.cpu()

            segmentation_result = paste_exmask(segmentation_result, exmask_result)
    
    #FIXME: code duplication
    skelresult   = postprocessing.skeletonize(segmentation_result)
    mask         = search_mask(image_path)

    stats        = postprocessing.compute_statistics(segmentation_result, skelresult, mask)

    result_rgb     = result_to_rgb(segmentation_result)
    skelresult_rgb = result_to_rgb(skelresult)

    if mask is not None:
        result_rgb       = add_mask(result_rgb, mask)
        skelresult_rgb   = add_mask(skelresult_rgb, mask)


    segmentation_fname = f'{basename}.segmentation.png'
    segmentation_path  = os.path.join(output_folder, segmentation_fname)
    skeleton_fname     = f'{basename}.skeleton.png'
    skeleton_path      = os.path.join(output_folder, skeleton_fname)
    backend.write_as_png(segmentation_path, result_rgb)
    backend.write_as_png(skeleton_path, skelresult_rgb)

    return {
        'segmentation': segmentation_fname,
        'skeleton'    : skeleton_fname,
        'statistics'  : stats,
    }

def result_to_rgb(x:np.array) -> np.array:
    '''Convert a segmentation map with labels 0,1,2 to RGB format'''
    assert len(x.shape)==2
    x     = x[...,np.newaxis]
    WHITE = (1.,1.,1.)
    RED   = (1.,0.,0.)
    x     = (x==1) * WHITE   +  (x==2) * RED
    return x

def result_from_rgb(x:np.array) -> np.array:
    '''Convert a RGB array to a segmentation map with labels 0,1,2'''
    assert len(x.shape)==3
    WHITE  = (1.,1.,1.)
    RED    = (1.,0.,0.)
    result = (x == WHITE).all(-1) *1 \
           + (x == RED  ).all(-1) *2
    return result


def paste_exmask(segmask, exmask):
    exmask     = exmask.squeeze()
    TAPE_VALUE = 2
    return np.where(exmask>0, TAPE_VALUE, segmask)

def search_mask(input_image_path):
    '''Looks for a file with prefix "mask_" in the same directory as input_image_path'''
    basename = os.path.splitext(os.path.basename(input_image_path))[0]
    pattern  = os.path.join( os.path.dirname(input_image_path), f'{basename}.excludemask.png')
    masks    = glob.glob(pattern)
    if len(masks)==1:
        return PIL.Image.open(masks[0]).convert('RGB') / np.float32(255)

def add_mask(image_rgb, mask):
    masked_image  = np.where( np.any(mask, axis=-1, keepdims=True)>0, mask, image_rgb )
    return masked_image


def postprocess(segmentation_filename):
    #FIXME: code duplication

    assert segmentation_filename.endswith('.segmentation.png')
    segmentation = PIL.Image.open(segmentation_filename).convert('RGB') / np.float32(255)
    segmentation = result_from_rgb(segmentation)
    skeleton     = postprocessing.skeletonize(segmentation)
    mask         = None
    #mask         = search_mask(image_path)  #TODO
    stats        = postprocessing.compute_statistics(segmentation, skeleton, mask)

    #segmentation_rgb     = result_to_rgb(segmentation)
    skeleton_rgb         = result_to_rgb(skeleton)

    #segmentation_fname = os.path.join(output_folder, f'{basename}.segmentation.png')
    skeleton_fname     = segmentation_filename.replace('.segmentation.png', '.skeleton.png')
    #write_as_png(segmentation_fname, result_rgb)
    backend.write_as_png(skeleton_fname, skeleton_rgb)

    return {
        'segmentation': segmentation_filename,
        'skeleton'    : skeleton_fname,
        'statistics'  : stats,
    }


