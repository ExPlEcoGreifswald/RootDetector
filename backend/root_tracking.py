import os
import torch, torchvision
import numpy as np
import scipy.ndimage
import cloudpickle
import PIL.Image


import backend
from backend import GLOBALS



def process(filename0, filename1, corrections=None, points0=None, points1=None):
    #TODO: wrap in threading.Lock
    print(f'Performing root tracking on files {filename0} and {filename1}')
    segmodel   = cloudpickle.load(open('models/root_tracking_models/019c_segmodel.full.cpkl', 'rb'))

    modelfile  = os.path.join('models/root_tracking_models', GLOBALS.tracking_active_model+'.cpkl')
    matchmodel = cloudpickle.load(open(modelfile, 'rb'))

    if corrections is None:
        img0    = torchvision.transforms.ToTensor()(PIL.Image.open(filename0))
        img1    = torchvision.transforms.ToTensor()(PIL.Image.open(filename1))
        with GLOBALS.processing_lock:
            seg0    = run_segmentation(filename0)
            seg1    = run_segmentation(filename1)
            output  = matchmodel.bruteforce_match(img0, img1, seg0, seg1, matchmodel, n=5000, cyclic_threshold=4, dev='cpu') #TODO: larger n
            imap    = matchmodel.interpolation_map(output['points0'], output['points1'], img0.shape[-2:])
    else:
        imap   = np.load(f'{filename0}.{os.path.basename(filename1)}.imap.npy').astype('float32')
        output = cloudpickle.load( open(f'{filename0}.{os.path.basename(filename1)}.bfm.pkl','rb') )
        seg0   = PIL.Image.open(f'{filename0}.segmentation.png') / np.float32(255)
        seg1   = PIL.Image.open(f'{filename1}.segmentation.png') / np.float32(255)

        corrections    = np.array(corrections).reshape(-1,4)
        corrections_p1 = corrections[:,:2][:,::-1]
        corrections_p0 = corrections[:,2:][:,::-1]
        corrections_p1 = np.stack([
            scipy.ndimage.map_coordinates(imap[...,0], corrections_p1.T, order=1),
            scipy.ndimage.map_coordinates(imap[...,1], corrections_p1.T, order=1),
        ], axis=-1)
        output['points0'] = np.concatenate([points0, corrections_p0])
        output['points1'] = np.concatenate([points1, corrections_p1])
        imap    = matchmodel.interpolation_map(output['points0'], output['points1'], seg0.shape)
    
    np.save(f'{filename0}.{os.path.basename(filename1)}.imap.npy', imap.astype('float16'))  #f16 to save space & time
    open(f'{filename0}.{os.path.basename(filename1)}.bfm.pkl','wb').write(cloudpickle.dumps(output))
    PIL.Image.fromarray( (seg0*255).astype('uint8') ).save( f'{filename0}.segmentation.png' )
    PIL.Image.fromarray( (seg1*255).astype('uint8') ).save( f'{filename1}.segmentation.png' )

    warped_seg1 = matchmodel.warp(seg1, imap)
    gmap        = matchmodel.create_growth_map_rgba( seg0>0.5,  warped_seg1>0.5 )
    output_file = f'{filename0}.{os.path.basename(filename1)}.growthmap.png'
    PIL.Image.fromarray(gmap).convert('RGB').save( output_file )
    output['growthmap'] = output_file

    output_file = f'{filename0}.{os.path.basename(filename1)}.growthmap_rgba.png'
    PIL.Image.fromarray(gmap).save( output_file )
    output['growthmap_rgba'] = output_file

    print()
    print(len(output['points0']))
    print('Matched percentage:', output['matched_percentage'])
    print()
    return output


def run_segmentation(imgfile):
    return backend.call_with_optional_kwargs(GLOBALS.model.process_image, imgfile, threshold=None)

