import webbrowser, os, tempfile, io, sys, time, json
import glob, shutil
import warnings
warnings.simplefilter('ignore')

import flask
from flask import Flask, escape, request

import backend
from backend import root_tracking, root_detection

import PIL.Image
PIL.Image.MAX_IMAGE_PIXELS = None #Needed to open large images





app        = Flask('DigIT! Root Detector', static_folder=os.path.abspath('./HTML'))

is_debug = sys.argv[0].endswith('.py')
if os.environ.get('WERKZEUG_RUN_MAIN')=='true' or not is_debug:
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
        #backend.write_as_jpeg(fullpath+'.jpg', backend.load_image(fullpath) )
    return 'OK'

@app.route('/images/<imgname>')
def images(imgname):
    return flask.send_from_directory(TEMPFOLDER.name, imgname)

@app.route('/process_image/<imgname>')
def process_image(imgname):
    fullpath  = os.path.join(TEMPFOLDER.name, imgname)
    result    = root_detection.process_image( fullpath )
    result['segmentation'] = os.path.basename(result['segmentation'])
    result['skeleton']     = os.path.basename(result['skeleton'])
    return flask.jsonify(result)


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
        backend.set_settings(request.get_json(force=True))
        return 'OK'
    elif request.method=='GET':
        return flask.jsonify(backend.get_settings())

@app.route('/process_root_tracking', methods=['GET', 'POST'])
def process_root_tracking():
    if request.method=='GET':
        fname0 = os.path.join(TEMPFOLDER.name, request.args['filename0'])
        fname1 = os.path.join(TEMPFOLDER.name, request.args['filename1'])
        result = root_tracking.process(fname0, fname1)
    elif request.method=='POST':
        data   = request.get_json(force=True)
        fname0 = os.path.join(TEMPFOLDER.name, data['filename0'])
        fname1 = os.path.join(TEMPFOLDER.name, data['filename1'])
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
    })
    return 'OK'


@app.route('/stream')
def stream():
    def generator():
        message_queue = backend.PubSub.subscribe()
        while 1:
            event, message = message_queue.get()
            #TODO: make sure message does not contain \n
            yield f'event:{event}\ndata: {json.dumps(message)}\n\n'
    return flask.Response(generator(), mimetype="text/event-stream")


if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not is_debug:  #to avoid flask starting twice
    with app.app_context():
        backend.init()
        if not is_debug:
        	print('Flask started')
        	webbrowser.open('http://localhost:5000', new=2)

#ugly ugly
host = ([x[x.index('=')+1:] for x in sys.argv if x.startswith('--host=')] + ['127.0.0.1'])[0]
print(f'Host: {host}')
app.run(host=host,port=5000, debug=is_debug)
