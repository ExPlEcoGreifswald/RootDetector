#needed for upstream
from base.backend import *
from . import root_detection as processing


import PIL.Image
import numpy as np


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

def load_image(path):
    x = PIL.Image.open(path) / np.float32(255)
    x = x[...,np.newaxis] if len(x.shape)==2 else x
    x = x[...,:3]
    return x


def call_with_optional_kwargs(func, *args, **kwargs):
    import inspect
    funcargs = inspect.getfullargspec(func).args
    kwargs   = dict([(k,v) for k,v in kwargs.items() if k in funcargs])
    return func(*args,**kwargs)
