from base.backend import GLOBALS
from base.backend import pubsub
import os

import torch


def start_training(imagefiles, targetfiles, training_options:dict, settings):
    locked = GLOBALS.processing_lock.acquire(blocking=False)
    if not locked:
        raise RuntimeError('Cannot start training. Already processing.')

    print('Training options: ', training_options)
    training_type = training_options['training_type']
    assert training_type in ['detection', 'exclusion_mask']

    device = 'cuda' if settings.use_gpu and torch.cuda.is_available() else 'cpu'
    with GLOBALS.processing_lock:
        GLOBALS.processing_lock.release()  #decrement recursion level bc acquired twice
        model = settings.models[training_type].to(device)
        #indicate that the current model is unsaved
        settings.active_models[training_type] = ''
        ok = model.start_training(
            imagefiles, 
            targetfiles, 
            epochs      = int(training_options.get('epochs', 10)),
            lr          = float(training_options.get('lr', 1e-3)),
            num_workers = 0 if device=='cpu' else 'auto', 
            callback    = training_progress_callback,
            fit_kwargs  = {'device':device},
        )
        model.cpu()
        return 'OK' if ok else 'INTERRUPTED'

def training_progress_callback(x):
    pubsub.PubSub.publish({'progress':x,  'description':'Training...'}, event='training')

def find_targetfiles(inputfiles):
    def find_targetfile(imgf):
        no_ext_imgf = os.path.splitext(imgf)[0]
        for f in [
            f'{imgf}.segmentation.png', 
            f'{no_ext_imgf}.segmentation.png', 
            f'{no_ext_imgf}.png'
        ]:
            if os.path.exists(f):
                return f
    return list(map(find_targetfile, inputfiles))
