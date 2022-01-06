import os, glob, threading, json, pickle
import numpy as np


#import tensorflow as tf
#import tensorflow.keras as keras
#K = keras.backend
#print('TensorFlow version: %s'%tf.__version__)
#print('Keras version: %s'%keras.__version__)

import PIL.Image
#import skimage.io         as skio
#import skimage.util       as skimgutil

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
    filepath             = os.path.join('models/root_detection_models', name+'.pkl')
    print('Loading model', filepath)
    GLOBALS.model        = pickle.load(open(filepath, 'rb'))
    GLOBALS.active_model = name
    print('Finished loading', filepath)

def load_exmask_model(name):
    '''Loads the exclusion mask model'''
    filepath                    = os.path.join('models/exclusionmask_models', name+'.pkl')
    print('Loading model', filepath)
    GLOBALS.exmask_model        = pickle.load(open(filepath, 'rb'))
    GLOBALS.exmask_active_model = name
    print('Finished loading', filepath)


def load_image(path):
    x = PIL.Image.open(path) / np.float32(255)
    x = x[...,np.newaxis] if len(x.shape)==2 else x
    x = x[...,:3]
    return x

def process_image(image_path):
    basename      = os.path.basename(image_path)
    output_folder = os.path.dirname(image_path)
    image         = load_image(image_path)
    with GLOBALS.processing_lock:
        progress_callback=lambda x: PubSub.publish({'progress':x, 'image':os.path.basename(image_path), 'stage':'roots'})
        segmentation_result = GLOBALS.model.process_image(image, progress_callback=progress_callback)
        if GLOBALS.exmask_enabled:
            progress_callback=lambda x: PubSub.publish({'progress':x, 'image':os.path.basename(image_path), 'stage':'mask'})
            exmask_result = GLOBALS.exmask_model.process_image(image, progress_callback=progress_callback)
            segmentation_result = paste_exmask(segmentation_result, exmask_result)
    
    skelresult   = postprocessing.skeletonize(segmentation_result)
    mask         = search_mask(image_path)

    stats        = postprocessing.compute_statistics(segmentation_result, skelresult, mask)

    result_rgb     = result_to_rgb(segmentation_result)
    skelresult_rgb = result_to_rgb(skelresult)

    if mask is not None:
        result_rgb       = add_mask(result_rgb, mask)
        skelresult_rgb   = add_mask(skelresult_rgb, mask)


    segmentation_fname = f'segmented_{basename}.png'
    skeleton_fname     = f'skeletonized_{basename}.png'
    write_as_png(os.path.join(output_folder, segmentation_fname), result_rgb)
    write_as_png(os.path.join(output_folder, skeleton_fname), skelresult_rgb)

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

def write_as_png(path,x):
    x = np.asarray(x).astype('float32')
    x = x[...,np.newaxis] if len(x.shape)==2 else x
    x = x*255 if np.max(x)<=1 else x
    x = x.astype('uint8')
    PIL.Image.fromarray(x).save(path)


def write_as_jpeg(path,x):
    x = x.astype('float32')
    x = x[...,np.newaxis] if len(x.shape)==2 else x
    x = x[...,:3]
    x = x*255 if np.max(x)<=1 else x
    PIL.Image.fromarray(x.astype('uint8')).save(path)


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
    modelfiles = glob.glob('models/root_detection_models/*.pkl')
    modelnames = [os.path.splitext(os.path.basename(fname))[0] for fname in modelfiles]
    exmask_modelfiles = glob.glob('models/exclusionmask_models/*.pkl')
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
        return PIL.Image.open(masks[0]).convert('RGB') / np.float32(255)

def add_mask(image_rgb, mask):
    masked_image  = np.where( np.any(mask, axis=-1, keepdims=True)>0, mask, image_rgb )
    return masked_image



import queue

class PubSub:
    subscribers = []

    @classmethod
    def subscribe(cls):
        q = queue.Queue(maxsize=5)
        cls.subscribers.append(q)
        return q

    @classmethod
    def publish(cls, msg, event='message'):
        for i in reversed(range(len(cls.subscribers))):
            try:
                cls.subscribers[i].put_nowait((event, msg))
            except queue.Full:
                del cls.subscribers[i]

