import os, glob, time, pickle
from base.backend.settings import Settings as BaseSettings
from base.backend.app      import get_models_folder
import backend

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
        detection_modelfiles = glob.glob(f'{get_models_folder()}/root_detection_models/*.pkl')
        detection_modelnames = [os.path.splitext(os.path.basename(fname))[0] for fname in detection_modelfiles]
        exmask_modelfiles    = glob.glob(f'{get_models_folder()}/exclusionmask_models/*.pkl')
        exmask_modelnames    = [os.path.splitext(os.path.basename(fname))[0] for fname in exmask_modelfiles]
        tracking_modelfiles  = glob.glob(f'{get_models_folder()}/root_tracking_models/*.cpkl')
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

    #override
    @staticmethod
    def load_model(name):
        return load_model(name)

def load_models_from_settings(settings:'Settings'):
    print('load_models_from_settings', settings.get_defaults())
    load_model(settings.active_model)
    load_exmask_model(settings.exmask_active_model)

def load_model(name):
    '''Loads the root segmentation model'''
    filepath             = os.path.join(f'{get_models_folder()}/root_detection_models/{name}.pkl')
    if not os.path.exists(filepath):
        print(f'[ERROR] cannot load model {name}')
        return
    print('Loading model', filepath)
    t0 = time.time()
    backend.GLOBALS.model        = pickle.load(open(filepath, 'rb'))
    print(f'Finished loading in {time.time() - t0:.3f} seconds')

def load_exmask_model(name):
    '''Loads the exclusion mask model'''
    filepath                    = os.path.join(f'{get_models_folder()}/exclusionmask_models/{name}.pkl')
    if not os.path.exists(filepath):
        print(f'[ERROR] cannot load exclusion mask model {name}')
        return
    print('Loading model', filepath)
    t0 = time.time()
    backend.GLOBALS.exmask_model        = pickle.load(open(filepath, 'rb'))
    print(f'Finished loading in {time.time() - t0:.3f} seconds')

def load_tracking_model(name):
    '''Loads the exclusion mask model'''
    filepath                    = os.path.join(f'{get_models_folder()}/root_tracking_models/{name}.cpkl')
    if not os.path.exists(filepath):
        print(f'[ERROR] cannot load tracking model {name}')
        return
    print('Loading model', filepath)
    t0 = time.time()
    model = pickle.load(open(filepath, 'rb'))
    print(f'Finished loading in {time.time() - t0:.3f} seconds')
    return model