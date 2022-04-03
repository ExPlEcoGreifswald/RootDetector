import os, glob
import numpy as np

import PIL.Image
from backend import postprocessing
from backend import GLOBALS, PubSub, write_as_png





def process_image(image_path, no_exmask=False, **kwargs):
    basename      = os.path.basename(image_path)
    output_folder = os.path.dirname(image_path)
    with GLOBALS.processing_lock:
        progress_callback=lambda x: PubSub.publish({'progress':x, 'image':os.path.basename(image_path), 'stage':'roots'})
        segmentation_result = GLOBALS.model.process_image(image_path, progress_callback=progress_callback)
        if GLOBALS.settings.exmask_enabled and not no_exmask:
            progress_callback=lambda x: PubSub.publish({'progress':x, 'image':os.path.basename(image_path), 'stage':'mask'})
            exmask_result = GLOBALS.exmask_model.process_image(image_path, progress_callback=progress_callback)
            segmentation_result = paste_exmask(segmentation_result, exmask_result)
    
    skelresult   = postprocessing.skeletonize(segmentation_result)
    mask         = search_mask(image_path)

    stats        = postprocessing.compute_statistics(segmentation_result, skelresult, mask)

    result_rgb     = result_to_rgb(segmentation_result)
    skelresult_rgb = result_to_rgb(skelresult)

    if mask is not None:
        result_rgb       = add_mask(result_rgb, mask)
        skelresult_rgb   = add_mask(skelresult_rgb, mask)


    segmentation_fname = os.path.join(output_folder, f'{basename}.segmented.png')
    skeleton_fname     = os.path.join(output_folder, f'{basename}.skeletonized.png')
    write_as_png(segmentation_fname, result_rgb)
    write_as_png(skeleton_fname, skelresult_rgb)

    return {
        'segmentation': segmentation_fname,
        'skeleton'    : skeleton_fname,
        'statistics'  : stats,
    }

def result_to_rgb(x):
    assert len(x.shape)==2
    x     = x[...,np.newaxis]
    WHITE = (1.,1.,1.)
    RED   = (1.,0.,0.)
    x     = (x==1) * WHITE   +  (x==2) * RED
    return x

def paste_exmask(segmask, exmask):
    exmask     = exmask.squeeze()
    TAPE_VALUE = 2
    return np.where(exmask>0, TAPE_VALUE, segmask)

def search_mask(input_image_path):
    '''Looks for a file with prefix "mask_" in the same directory as input_image_path'''
    basename = os.path.splitext(os.path.basename(input_image_path))[0]
    pattern  = os.path.join( os.path.dirname(input_image_path), 'mask_'+basename+'*.png' )
    masks    = glob.glob(pattern)
    if len(masks)==1:
        return PIL.Image.open(masks[0]).convert('RGB') / np.float32(255)

def add_mask(image_rgb, mask):
    masked_image  = np.where( np.any(mask, axis=-1, keepdims=True)>0, mask, image_rgb )
    return masked_image



