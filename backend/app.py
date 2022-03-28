from base.backend.app import App as BaseApp

import os
import flask

import backend
from . import root_detection



class App(BaseApp):
    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        if self.is_reloader:
            return
        
        backend.init(self.root_path)
        self.settings = backend.GLOBALS.settings


    #override
    def process_image(self, imagename):
        print('Processing image:', imagename)
        #FIXME: code duplication with upstream
        full_path = os.path.join(self.cache_path, imagename)
        if not os.path.exists(full_path):
            flask.abort(404)
        
        result = root_detection.process_image(full_path)
        result['segmentation'] = os.path.basename(result['segmentation'])
        result['skeleton']     = os.path.basename(result['skeleton'])
        return flask.jsonify(result)
    


