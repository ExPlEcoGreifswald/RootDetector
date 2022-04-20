import backend
from base.backend import pubsub



def start_training(imagefiles, targetfiles):
    #TODO: lock.acquire(blocking=False)
    model = backend.GLOBALS.settings.models['detection']
    #indicate that the current model is unsaved
    backend.GLOBALS.settings.active_models['detection'] = ''
    ok = model.start_training(imagefiles, targetfiles, epochs=10, num_workers=0, callback=training_progress_callback)
    return 'OK' if ok else 'INTERRUPTED'

def training_progress_callback(x):
    pubsub.PubSub.publish({'progress':x,  'description':'Training...'}, event='training')

