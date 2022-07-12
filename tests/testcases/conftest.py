import os
os.environ['TESTS_TO_SKIP'] = (
    '''test_download_all'''              #needs non-static
    '''test_load_results'''              #needs non-static, replaced with test_load_root_results.py:test_basic_load_results
    '''test_add_boxes'''                 #no boxes
    '''test_overlay_side_by_side_switch'''   #side-by-side removed
)



import sys, importlib
modellib = importlib.import_module('models_src.2022-07-11_029.models')
from base.backend.app import get_models_path

models_path = os.path.join(get_models_path(), 'detection')
os.makedirs(models_path, exist_ok=True)
for i in range(3):
    modellib.UNet(pretrained=False).save( os.path.join(models_path, f'model_{i}') )


#FIXME: copy tracking model src and instantiate instead of this
import glob, shutil
models_path = os.path.join(get_models_path(), 'tracking')
shutil.rmtree(models_path, ignore_errors=True)
os.makedirs(models_path, exist_ok=True)
for i,m in enumerate(glob.glob('./**/tracking/*.pkl', recursive=True)):
    shutil.copy(m, os.path.join(models_path, f'model_{i}.pkl') )
