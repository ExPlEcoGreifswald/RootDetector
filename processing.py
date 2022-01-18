import os

import glob
import dill
dill._dill._reverse_typemap['ClassType'] = type
import numpy as np
import itertools
import threading
import glob
import json

import tensorflow as tf
import tensorflow.keras as keras
K = keras.backend
print('TensorFlow version: %s'%tf.__version__)
print('Keras version: %s'%keras.__version__)

import skimage.io         as skio
import skimage.util       as skimgutil

import postprocessing



class GLOBALS:
    active_model           = ''                #modelname
    model                  = None              #TF model
    exmask_enabled         = False
    exmask_active_model    = ''                #modelname
    exmask_model           = None              #TF model

    processing_progress    = dict()            #filename:percentage
    processing_lock        = threading.Lock()





def init():
    load_settings()

def load_model(name):
    '''Loads the root segmentation model'''
    filepath             = os.path.join('models', name+'.dill')
    print('Loading model', filepath)
    GLOBALS.model        = dill.load(open(filepath, 'rb'))
    GLOBALS.active_model = name
    print('Finished loading', filepath)

def load_exmask_model(name):
    '''Loads the exclusion mask model'''
    filepath                    = os.path.join('models/exclusionmask_models', name+'.dill')
    print('Loading model', filepath)
    GLOBALS.exmask_model        = dill.load(open(filepath, 'rb'))
    GLOBALS.exmask_active_model = name
    print('Finished loading', filepath)


def load_image(path):
    x = GLOBALS.model.load_image(path)
    x = x[...,tf.newaxis] if len(x.shape)==2 else x
    x = x[...,:3]
    return x

def process_image(image_path):
    basename      = os.path.basename(image_path)
    output_folder = os.path.dirname(image_path)
    image         = load_image(image_path)
    with GLOBALS.processing_lock:
        segmentation_result = GLOBALS.model.process_image(image, progress_callback=progress_callback_for_image(basename))
        if GLOBALS.exmask_enabled:
            exmask_result = GLOBALS.exmask_model.process_image(image, progress_callback=progress_callback_for_image(basename))
            segmentation_result = paste_exmask(segmentation_result, exmask_result)
    
    skelresult   = postprocessing.skeletonize(segmentation_result)
    mask         = search_mask(image_path)

    stats        = postprocessing.compute_statistics(segmentation_result, skelresult, mask)

    result       = result_to_rgb(segmentation_result)
    skelresult   = result_to_rgb(skelresult)

    if mask is not None:
        result       = add_mask(result, mask)
        skelresult   = add_mask(skelresult, mask)

    write_as_png(os.path.join(output_folder, f'segmented_{basename}.png'), result)
    write_as_png(os.path.join(output_folder, f'skeletonized_{basename}.png'), skelresult)

    return stats

def result_to_rgb(x):
    assert len(x.shape)==2
    x     = x[...,np.newaxis]
    WHITE = (1.,1.,1.)
    RED   = (1.,0.,0.)
    x     = (x==1) * WHITE   +  (x==2) * RED
    return x

def write_as_png(path,x):
    x = tf.cast(x, tf.float32)
    x = x[...,tf.newaxis] if len(x.shape)==2 else x
    x = x*255 if tf.reduce_max(x)<=1 else x
    tf.io.write_file(path, tf.image.encode_png(  tf.cast(x, tf.uint8)  ))


def write_as_jpeg(path,x):
    x = tf.cast(x, tf.float32)
    x = x[...,tf.newaxis] if len(x.shape)==2 else x
    x = x[...,:3]
    x = x*255 if tf.reduce_max(x)<=1 else x
    tf.io.write_file(path, tf.image.encode_jpeg(  tf.cast(x, tf.uint8)  ))


def progress_callback_for_image(imagename):
    GLOBALS.processing_progress[imagename]=0
    def callback(x):
        GLOBALS.processing_progress[imagename]=x
        print(GLOBALS.processing_progress)
    return callback

def processing_progress(imagename):
    return GLOBALS.processing_progress.get(imagename,0)


def load_settings():
    settings = json.load(open('settings.json'))
    set_settings(settings)

def get_settings():
    modelfiles = glob.glob('models/*.dill')
    modelnames = [os.path.splitext(os.path.basename(fname))[0] for fname in modelfiles]
    exmask_modelfiles = glob.glob('models/exclusionmask_models/*.dill')
    exmask_modelnames = [os.path.splitext(os.path.basename(fname))[0] for fname in exmask_modelfiles]
    s = dict(
        models         = modelnames,
        active_model   = GLOBALS.active_model,
        exmask_enabled        = GLOBALS.exmask_enabled,
        exmask_models         = exmask_modelnames,              #available exmask-models
        exmask_active_model   = GLOBALS.exmask_active_model,    #active exmask-model
    )
    return s

def set_settings(s):
    print('New settings:',s)
    newmodelname = s.get('active_model')
    if newmodelname != GLOBALS.active_model:
        load_model(newmodelname)
    GLOBALS.exmask_enabled      = s.get('exmask_enabled', GLOBALS.exmask_enabled)
    if s.get('exmask_model') != GLOBALS.exmask_active_model:
        load_exmask_model(s.get('exmask_model'))
    json.dump(dict(
        active_model   = GLOBALS.active_model,
        exmask_enabled = GLOBALS.exmask_enabled,
        exmask_model   = GLOBALS.exmask_active_model,
    ), open('settings.json','w'))


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
        m = skio.imread(masks[0])[...,:3]
        m = skimgutil.img_as_float32(m)
        return m

def add_mask(image_rgb, mask):
    masked_image  = np.where( np.any(mask, axis=-1, keepdims=True)>0, mask, image_rgb )
    return masked_image

