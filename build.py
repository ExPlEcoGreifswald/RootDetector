#!/bin/python
import os, shutil, sys, subprocess
import datetime

os.environ['DO_NOT_RELOAD'] = 'true'
from backend.app import App
App().recompile_static(force=True)        #make sure the static/ folder is up to date

build_name = '%s_DigIT_RootDetector'%(datetime.datetime.now().strftime('%Y-%m-%d_%Hh%Mm%Ss') )
build_dir  = 'builds/%s'%build_name

rc = subprocess.call(f'''pyinstaller --noupx                            \
              --hidden-import=sklearn.utils._cython_blas     \
              --hidden-import=skimage.io._plugins.tifffile_plugin   \
              --hidden-import=onnxruntime                           \
              --hidden-import=pytorch_lightning                     \
              --hidden-import=torchvision                           \
              --additional-hooks-dir=./hooks                        \
              --distpath {build_dir} main.py''')
if rc!=0:
    print(f'PyInstaller exited with code {rc}')
    sys.exit(rc)

shutil.copytree('static', build_dir+'/static')
shutil.copytree('models', build_dir+'/models')
if 'linux' in sys.platform:
    os.symlink('/main/main', build_dir+'/main.run')
else:
    open(build_dir+'/main.bat', 'w').write(r'main\main.exe'+'\npause')
shutil.rmtree('./build')
#shutil.copyfile('settings.json', build_dir+'/settings.json')
os.remove('./main.spec')
