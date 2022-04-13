from base.backend.app import App as BaseApp

import os
import flask

import backend
import backend.training
from . import root_detection
from . import root_tracking



class App(BaseApp):
    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        if self.is_reloader:
            return
        
        backend.init(self.root_path)
        self.settings = backend.GLOBALS.settings

        self.route('/process_root_tracking', methods=['GET', 'POST'])(self.process_root_tracking)
    

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
    

    def process_root_tracking(self):
        if flask.request.method=='GET':
            fname0 = os.path.join(self.cache_path, flask.request.args['filename0'])
            fname1 = os.path.join(self.cache_path, flask.request.args['filename1'])
            result = root_tracking.process(fname0, fname1)
        elif flask.request.method=='POST':
            data   = flask.request.get_json(force=True)
            fname0 = os.path.join(self.cache_path, data['filename0'])
            fname1 = os.path.join(self.cache_path, data['filename1'])
            result = root_tracking.process(fname0, fname1, data)
        
        return flask.jsonify({
            'points0':         result['points0'].tolist(),
            'points1':         result['points1'].tolist(),
            'growthmap'     :  os.path.basename(result['growthmap']),
            'growthmap_rgba':  os.path.basename(result['growthmap_rgba']),
            'segmentation0' :  os.path.basename(result['segmentation0']),
            'segmentation1' :  os.path.basename(result['segmentation1']),
            'success'       :  result['success'],
            'n_matched_points'   : result['n_matched_points'],
            'tracking_model'     : result['tracking_model'],
            'segmentation_model' : result['segmentation_model'],
            'statistics'         : result['statistics'],
        })

    #override
    def training(self):
        imagefiles = dict(flask.request.form.lists())['filenames[]']
        imagefiles = [os.path.join(self.cache_path, fname) for fname in imagefiles]
        if not all([os.path.exists(fname) for fname in imagefiles]):
            flask.abort(404)
        
        targetfiles = [ f'{imgf}.segmented.png' for imgf in imagefiles ]
        if not all([os.path.exists(fname) for fname in targetfiles]):
            flask.abort(404)
        
        backend.training.start_training(imagefiles, targetfiles)
        return 'OK'
    
    #override
    def save_model(self):
        newname = flask.request.args['newname']
        backend.training.save_model(newname)
        print('New model training model saved as:',newname)
        return 'OK'

