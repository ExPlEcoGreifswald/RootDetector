#!/bin/python
import os, shutil
import datetime


build_name = '%s_DigIT_RootDetector'%(datetime.datetime.now().strftime('%Y%m%d_%Hh%Mm%Ss') )
build_dir  = 'builds/%s'%build_name

os.system(f'''pyinstaller --noupx                            \
              --hidden-import=sklearn.utils._cython_blas     \
              --hidden-import=skimage.io._plugins.tifffile_plugin   \
              --additional-hooks-dir=./hooks                        \
              --distpath {build_dir} -F main.py''')


shutil.copytree('HTML',   build_dir+'/HTML')
shutil.copytree('models', build_dir+'/models')
shutil.rmtree('./build')
shutil.copyfile('settings.json', build_dir+'/')
os.remove('./main.spec')

