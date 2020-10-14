import webbrowser, os, tempfile, io, sys, time
import flask
from flask import Flask, escape, request

import processing

#need to import all the packages here in the main file because of dill-ed ipython model
import tensorflow as tf
import tensorflow.keras as keras

import numpy as np
arange = np.arange
import skimage.io              as skio
import skimage.draw            as skdraw
import skimage.transform       as sktransform
import skimage.measure         as skmeasure
import skimage.morphology      as skmorph
import skimage.util            as skimgutil
import sklearn.svm             as sksvm
import sklearn.model_selection as skms
import sklearn.utils           as skutils

import PIL
PIL.Image.MAX_IMAGE_PIXELS = None #Needed to open large images

#import util





app        = Flask('DigIT! Root Detector', static_folder=os.path.abspath('./HTML'))
TEMPFOLDER = tempfile.TemporaryDirectory(prefix='root_detector_')
print('Temporary Directory: %s'%TEMPFOLDER.name)





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
    print('Download: %s'%os.path.join(TEMPFOLDER.name, imgname))
    return flask.send_from_directory(TEMPFOLDER.name, imgname)

@app.route('/process_image/<imgname>')
def process_image(imgname):
    fullpath     = os.path.join(TEMPFOLDER.name, imgname)
    image        = processing.load_image(fullpath)
    result       = processing.process_image(image, processing.progress_callback_for_image(imgname))
    skelresult   = processing.skeletonize(result)
    result       = processing.maybe_add_mask(result, fullpath)
    skelresult   = processing.maybe_add_mask(skelresult, fullpath)
    processing.write_as_png(os.path.join(TEMPFOLDER.name, 'segmented_'+imgname+'.png'), result)
    processing.write_as_png(os.path.join(TEMPFOLDER.name, 'skeletonized_'+imgname+'.png'), skelresult)
    return flask.jsonify({'labels':[]})

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

@app.route('/custom_patch/<imgname>')
def custom_patch(imgname):
    y,x      = float(request.args.get('y')), float(request.args.get('x'))
    index    = int(request.args.get('index'))
    print('CUSTOM PATCH: %s @yx=%.3f,%.3f'%(imgname, y,x))
    fullpath = os.path.join(TEMPFOLDER.name, imgname)
    image    = processing.load_image(fullpath)
    patch    = processing.extract_patch(image, (y,x))
    processing.write_as_jpeg(os.path.join(TEMPFOLDER.name, 'patch_%i_%s'%(index,imgname)), patch)
    return 'OK'

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method=='POST':
        processing.set_settings(request.args)
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
    jsonfiles   = [tgtf  for tgtf      in targetfiles                  if os.path.exists(tgtf)]
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


is_debug = sys.argv[0].endswith('.py')
if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not is_debug:  #to avoid flask starting twice
    with app.app_context():
        processing.init()
        if not is_debug:
        	print('Flask started')
        	webbrowser.open('http://localhost:5000', new=2)

app.run(host='127.0.0.1',port=5000, debug=is_debug)
