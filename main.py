import webbrowser, os, tempfile, io, sys, time
import glob, shutil
import warnings
warnings.simplefilter('ignore')

import flask
from flask import Flask, escape, request

import processing

#need to import all the packages here in the main file because of dill-ed ipython model
import tensorflow as tf
import tensorflow.keras as keras

import numpy as np
arange = np.arange
import skimage.io              as skio
import skimage.morphology      as skmorph
import skimage.util            as skimgutil

import PIL
PIL.Image.MAX_IMAGE_PIXELS = None #Needed to open large images





app        = Flask('DigIT! Root Detector', static_folder=os.path.abspath('./HTML'))

if os.environ.get('WERKZEUG_RUN_MAIN')=='true':
    TEMPPREFIX = 'root_detector_'
    TEMPFOLDER = tempfile.TemporaryDirectory(prefix=TEMPPREFIX)
    print('Temporary Directory: %s'%TEMPFOLDER.name)
    #delete all previous temporary folders if not cleaned up properly
    for tmpdir in glob.glob( os.path.join(os.path.dirname(TEMPFOLDER.name), TEMPPREFIX+'*') ):
        if tmpdir != TEMPFOLDER.name:
            print('Removing ',tmpdir)
            shutil.rmtree(tmpdir)




@app.route('/')
def root():
    return app.send_static_file('index.html')

@app.route('/static/<path:path>')
def staticfiles(path):
    return app.send_static_file(path)

@app.route('/file_upload', methods=['POST'])
def file_upload():
    files = request.files.getlist("files")
    for f in files:
        filename = request.form.get('filename', f.filename)
        print('Upload: %s'%filename)
        fullpath = os.path.join(TEMPFOLDER.name, os.path.basename(filename) )
        f.save(fullpath)
        #save the file additionally as jpg to make sure format is compatible with browser (tiff)
        processing.write_as_jpeg(fullpath+'.jpg', processing.load_image(fullpath) )
    return 'OK'

@app.route('/images/<imgname>')
def images(imgname):
    return flask.send_from_directory(TEMPFOLDER.name, imgname)

@app.route('/process_image/<imgname>')
def process_image(imgname):
    fullpath  = os.path.join(TEMPFOLDER.name, imgname)
    stats     = processing.process_image( fullpath )
    return flask.jsonify({'statistics':stats})

@app.route('/processing_progress/<imgname>')
def processing_progress(imgname):
    return str(processing.processing_progress(imgname))


@app.route('/delete_image/<imgname>')
def delete_image(imgname):
    fullpath = os.path.join(TEMPFOLDER.name, imgname)
    print('DELETE: %s'%fullpath)
    if os.path.exists(fullpath):
        os.remove(fullpath)
    return 'OK'


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method=='POST':
        processing.set_settings(request.get_json(force=True))
        return 'OK'
    elif request.method=='GET':
        return flask.jsonify(processing.get_settings())


@app.route('/start_training', methods=['POST'])
def start_training():
    imagefiles  = dict(request.form.lists())['filenames[]']
    imagefiles  = [os.path.join(TEMPFOLDER.name, fname) for fname in imagefiles]
    imagefiles  = [fname for fname in imagefiles if os.path.exists(fname)]
    targetfiles = [os.path.splitext(fname)[0]+'.png'   for fname in imagefiles]
    imagefiles  = [imgf  for imgf,tgtf in zip(imagefiles, targetfiles) if os.path.exists(tgtf)]
    if len(imagefiles)>0:
        processing.retrain(imagefiles, targetfiles)
        return 'OK'
    else:
        print(f'Could not find any of the input files')
        flask.abort(404)

@app.route('/retraining_progress')
def retraining_progress():
    def streaming_generator():
        while processing.get_training_progress() < 1:
            yield f'({processing.get_training_progress():.3f})'
            time.sleep(0.5)
    return flask.Response(streaming_generator(), mimetype='text/csv')

@app.route('/stop_training')
def stop_training():
    processing.stop_training()
    return 'OK'

@app.route('/save_model')
def save_model():
    processing.save_model(request.args['newname'])
    return 'OK'


is_debug = sys.argv[0].endswith('.py')
if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not is_debug:  #to avoid flask starting twice
    with app.app_context():
        processing.init()
        if not is_debug:
        	print('Flask started')
        	webbrowser.open('http://localhost:5000', new=2)

app.run(host='127.0.0.1',port=5000, debug=is_debug)
