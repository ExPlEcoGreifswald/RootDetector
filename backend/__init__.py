import threading, queue, json, os, glob, pickle, time
import PIL.Image
import numpy as np

from base.backend.settings import Settings as BaseSettings


class GLOBALS:
    settings:'Settings'    = None  #see below
    root_path:str          = ''

    model:object           = None  #pre-loaded detection model
    exmask_model:object    = None  #pre-loaded exclusion mask model

    processing_lock        = threading.RLock()


def init(root_path):
    GLOBALS.root_path = os.path.normpath(root_path)
    GLOBALS.settings  = Settings()


class Settings(BaseSettings):
    DEFAULTS = {
        'active_model'          : None,
        'exmask_active_model'   : None,
        'exmask_enabled'        : False,
        'tracking_active_model' : None,
    }

    @classmethod
    def get_defaults(cls):
        available_models = cls.get_available_models()
        first_or_none    = lambda x: x[0] if len(x) else None 
        return {
            'active_model'          : first_or_none(available_models['models']),
            'exmask_enabled'        : False,
            'exmask_active_model'   : first_or_none(available_models['exmask_models']),
            'tracking_active_model' : first_or_none(available_models['tracking_models']),
        }

    @staticmethod
    def get_available_models():
        detection_modelfiles = glob.glob(f'{GLOBALS.root_path}/models/root_detection_models/*.pkl')
        detection_modelnames = [os.path.splitext(os.path.basename(fname))[0] for fname in detection_modelfiles]
        exmask_modelfiles    = glob.glob(f'{GLOBALS.root_path}/models/exclusionmask_models/*.pkl')
        exmask_modelnames    = [os.path.splitext(os.path.basename(fname))[0] for fname in exmask_modelfiles]
        tracking_modelfiles  = glob.glob(f'{GLOBALS.root_path}/models/root_tracking_models/*.cpkl')
        tracking_modelnames  = [os.path.splitext(os.path.basename(fname))[0] for fname in tracking_modelfiles]

        return {
            'models'          : detection_modelnames,
            'exmask_models'   : exmask_modelnames,
            'tracking_models' : tracking_modelnames,
        }

    def set_settings(self, s, *args, **kw):
        super().set_settings(s, *args, **kw)
        #TODO: remove this
        load_models_from_settings(self)


def load_models_from_settings(settings:'Settings'):
    print('load_models_from_settings', settings.get_defaults())
    load_model(settings.active_model)
    load_exmask_model(settings.exmask_active_model)

def load_model(name):
    '''Loads the root segmentation model'''
    filepath             = os.path.join(f'{GLOBALS.root_path}/models/root_detection_models/{name}.pkl')
    if not os.path.exists(filepath):
        print(f'[ERROR] cannot load model {name}')
        return
    print('Loading model', filepath)
    t0 = time.time()
    GLOBALS.model        = pickle.load(open(filepath, 'rb'))
    print(f'Finished loading in {time.time() - t0:.3f} seconds')

def load_exmask_model(name):
    '''Loads the exclusion mask model'''
    filepath                    = os.path.join(f'{GLOBALS.root_path}/models/exclusionmask_models/{name}.pkl')
    if not os.path.exists(filepath):
        print(f'[ERROR] cannot load exclusion mask model {name}')
        return
    print('Loading model', filepath)
    t0 = time.time()
    GLOBALS.exmask_model        = pickle.load(open(filepath, 'rb'))
    print(f'Finished loading in {time.time() - t0:.3f} seconds')

def load_tracking_model(name):
    '''Loads the exclusion mask model'''
    filepath                    = os.path.join(f'{GLOBALS.root_path}/models/root_tracking_models/{name}.cpkl')
    if not os.path.exists(filepath):
        print(f'[ERROR] cannot load tracking model {name}')
        return
    print('Loading model', filepath)
    t0 = time.time()
    model = pickle.load(open(filepath, 'rb'))
    print(f'Finished loading in {time.time() - t0:.3f} seconds')
    return model


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

#TODO: remove, already upstream
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
