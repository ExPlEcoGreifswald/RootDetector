import backend
from base.backend import pubsub



def start_training(imagefiles, targetfiles):
    #TODO: lock.acquire(blocking=False)
    model = backend.GLOBALS.model
    model.start_training(imagefiles, targetfiles, epochs=10, num_workers=0, callback=training_progress_callback)
    backend.GLOBALS.model                 = model
    backend.GLOBALS.settings.active_model = ''


def training_progress_callback(x):
    pubsub.PubSub.publish({'progress':x,  'description':'Training...'}, event='training')

def save_model(newname):
    path = f'{backend.GLOBALS.root_path}/models/root_detection_models/{newname}.pkl'
    backend.GLOBALS.model.save(path)
    backend.GLOBALS.settings.active_model = newname

