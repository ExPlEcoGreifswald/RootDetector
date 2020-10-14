import os
#restrict gpu usage
os.environ["CUDA_VISIBLE_DEVICES"]=""

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

import skimage.measure    as skmeasure
import skimage.morphology as skmorph
import skimage.io         as skio


class GLOBALS:
    active_model           = ''                #modelname
    model                  = None
    processing_progress    = dict()            #filename:percentage
    processing_lock        = threading.Lock()
    current_training_epoch = 0

class CONSTANTS:
    N_EPOCHS = 5                                           #XXX: 5 epochs for testing only




def init():
    load_settings()

def load_model(name):
    filepath             = os.path.join('models', name+'.dill')
    print('Loading model', filepath)
    GLOBALS.model        = dill.load(open(filepath, 'rb'))
    GLOBALS.active_model = name
    print('Finished loading', filepath)

def load_image(path):
    x = GLOBALS.model.load_image(path)
    x = x[...,tf.newaxis] if len(x.shape)==2 else x
    x = x[...,:3]
    return x


def process_image(image, progress_callback=None):
    with GLOBALS.processing_lock:
        print('Processing file with model', GLOBALS.active_model)
        return GLOBALS.model.process_image(image, progress_callback=progress_callback)


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
    s = dict( models       = modelnames,
              active_model = GLOBALS.active_model )
    return s

def set_settings(s):
    print('New settings:',s)
    newmodelname = s.get('active_model')
    if newmodelname != GLOBALS.active_model:
        load_model(newmodelname)
    json.dump(dict(active_model=GLOBALS.active_model), open('settings.json','w'))


def maybe_add_mask(image, input_image_path):
    '''Looks for a file with prefix "mask_" in the same directory as input_image_path,
       if it exists, blends it with image'''

    basename = os.path.splitext(os.path.basename(input_image_path))[0]
    pattern  = os.path.join( os.path.dirname(input_image_path), 'mask_'+basename+'*.png' )
    masks    = glob.glob(pattern)
    if len(masks)==1:
        mask          = skio.imread(masks[0])[...,:3]
        image_rgb     = np.stack([image]*3, axis=-1)*np.uint8(255)
        masked_image  = np.where( np.any(mask, axis=-1, keepdims=True)>0, mask, image_rgb )
        return masked_image
    #else
    return image

def skeletonize(image):
    return skmorph.skeletonize(image>0.5)

def on_train_epoch(e):
    GLOBALS.current_training_epoch = e

def get_training_progress():
    return (GLOBALS.current_training_epoch+1)/CONSTANTS.N_EPOCHS

def retrain(imagefiles, targetfiles):
    with GLOBALS.processing_lock:
        GLOBALS.current_training_epoch = -1
        GLOBALS.model.retrain(imagefiles, targetfiles, 
                              epochs=CONSTANTS.N_EPOCHS,
                              callback=on_train_epoch)
        GLOBALS.current_training_epoch = CONSTANTS.N_EPOCHS
        #GLOBALS.active_model = ''

def stop_training():
    GLOBALS.model.stop_training()