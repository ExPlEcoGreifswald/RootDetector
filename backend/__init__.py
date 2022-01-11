import threading, queue, json, os, glob, pickle
import PIL.Image
import numpy as np

class GLOBALS:
    active_model           = ''                #modelname
    model                  = None              #TF model
    exmask_enabled         = False
    exmask_active_model    = ''                #modelname
    exmask_model           = None              #TF model
    tracking_active_model  = ''

    processing_lock        = threading.RLock()


def init():
    load_settings()

def load_settings():
    settings = json.load(open('settings.json'))
    set_settings(settings)

def get_settings():
    modelfiles = glob.glob('models/root_detection_models/*.pkl')
    modelnames = [os.path.splitext(os.path.basename(fname))[0] for fname in modelfiles]
    exmask_modelfiles   = glob.glob('models/exclusionmask_models/*.pkl')
    exmask_modelnames   = [os.path.splitext(os.path.basename(fname))[0] for fname in exmask_modelfiles]
    tracking_modelfiles = glob.glob('models/root_tracking_models/*.cpkl')
    tracking_modelnames = [os.path.splitext(os.path.basename(fname))[0] for fname in tracking_modelfiles]
    s = dict(
        models         = modelnames,
        active_model   = GLOBALS.active_model,
        exmask_enabled        = GLOBALS.exmask_enabled,
        exmask_models         = exmask_modelnames,              #available exmask-models
        exmask_active_model   = GLOBALS.exmask_active_model,    #active exmask-model
        tracking_models       = tracking_modelnames,            #available root tracking models
        tracking_active_model = GLOBALS.tracking_active_model,  #active root tracking models
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
    GLOBALS.tracking_active_model = s.get('tracking_model')
    json.dump(dict(
        active_model   = GLOBALS.active_model,
        exmask_enabled = GLOBALS.exmask_enabled,
        exmask_model   = GLOBALS.exmask_active_model,
        tracking_model = GLOBALS.tracking_active_model,
    ), open('settings.json','w'))

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


def call_with_optional_kwargs(func, *args, **kwargs):
    import inspect
    funcargs = inspect.getfullargspec(func).args
    kwargs   = dict([(k,v) for k,v in kwargs.items() if k in funcargs])
    return func(*args,**kwargs)
