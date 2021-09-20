#!/bin/python
import os, shutil, sys, subprocess
import datetime


build_name = '%s_DigIT_RootDetector'%(datetime.datetime.now().strftime('%Y%m%d_%Hh%Mm%Ss') )
build_dir  = 'builds/%s'%build_name

rc = subprocess.call(f'''pyinstaller --noupx                            \
              --hidden-import=014a_tools     \
              --hidden-import=sklearn.utils._cython_blas     \
              --hidden-import=skimage.io._plugins.tifffile_plugin   \
              --additional-hooks-dir=./hooks                        \
              --distpath {build_dir} main.py''')
if rc!=0:
    print(f'PyInstaller exited with code {rc}')
    sys.exit(rc)


shutil.copytree('HTML',   build_dir+'/HTML')
shutil.copytree('models', build_dir+'/models')
shutil.copytree('exclusionmask_models', build_dir+'/exclusionmask_models')
if 'linux' in sys.platform:
    os.symlink('/main/main', build_dir+'/main.run')
else:
    open(build_dir+'/main.bat', 'w').write(r'main\main.exe'+'\npause')
    #takes up 400MB and is already in main/
    os.remove(build_dir+'/main/tensorflow/python/_pywrap_tensorflow_internal.pyd')
shutil.rmtree('./build')
shutil.copyfile('settings.json', build_dir+'/settings.json')
os.remove('./main.spec')
