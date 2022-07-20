#!/bin/python
import os, shutil, sys, subprocess
import datetime
import argparse, zipfile, glob

os.environ['DO_NOT_RELOAD'] = 'true'
from backend.app import App
App().recompile_static(force=True)        #make sure the static/ folder is up to date

build_name = '%s_DigIT_RootDetector'%(datetime.datetime.now().strftime('%Y-%m-%d_%Hh%Mm%Ss') )
build_dir  = 'builds/%s'%build_name

rc = subprocess.call(f'''pyinstaller --noupx                            \
              --hidden-import=sklearn.utils._cython_blas     \
              --hidden-import=skimage.io._plugins.tifffile_plugin   \
              --hidden-import=onnxruntime                           \
              --hidden-import=torchvision                           \
              --hidden-import=cloudpickle                           \
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
    open(build_dir+'/main.bat', 'w').write(r'SET ROOT_PATH=%~dp0'+'\nmain\main.exe'+'\npause')
shutil.rmtree('./build')
#shutil.copyfile('settings.json', build_dir+'/settings.json')
os.remove('./main.spec')



#zip full + zip as update + TODO: upload

parser = argparse.ArgumentParser()
parser.add_argument('--zip', action='store_true')
args = parser.parse_args()

if args.zip:
    shutil.rmtree(build_dir+'/cache', ignore_errors=True)

    print('Zipping update package...')
    files_to_zip  = []
    files_to_zip += [os.path.join(build_dir, 'main', 'main.exe')]
    files_to_zip += glob.glob(os.path.join(build_dir, 'static/**'), recursive=True)
    with zipfile.ZipFile(build_dir+'.update.zip', 'w') as archive:
        for f in files_to_zip:
            archive.write(f, f.replace(build_dir, ''))

    print('Zipping full package...')
    shutil.make_archive(build_dir, "zip", build_dir)


print('Done')
