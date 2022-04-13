import os
import torch, torchvision
import numpy as np
import scipy.ndimage
import cloudpickle
import PIL.Image


import backend
from backend import GLOBALS



def process(filename0, filename1, previous_data:dict=None):
    print(f'Performing root tracking on files {filename0} and {filename1}')
    #modelfile  = os.path.join('models/root_tracking_models', GLOBALS.settings.tracking_active_model+'.cpkl')
    #cloudpickle.load(open(modelfile, 'rb'))
    matchmodel = backend.load_tracking_model(GLOBALS.settings.tracking_active_model)

    seg0f = f'{filename0}.segmentation.png'
    seg1f = f'{filename1}.segmentation.png'

    if not os.path.exists(seg0f) or not os.path.exists(seg1f):
        img0    = torchvision.transforms.ToTensor()(PIL.Image.open(filename0))
        img1    = torchvision.transforms.ToTensor()(PIL.Image.open(filename1))
        with GLOBALS.processing_lock:
            seg0    = run_segmentation(filename0)
            seg1    = run_segmentation(filename1)
        PIL.Image.fromarray( (seg0*255).astype('uint8') ).save( seg0f )
        PIL.Image.fromarray( (seg1*255).astype('uint8') ).save( seg1f )
    else:
        seg0   = PIL.Image.open(seg0f) / np.float32(255)
        seg1   = PIL.Image.open(seg1f) / np.float32(255)
    
    if previous_data is None:  #FIXME: better condition?
        img0    = torchvision.transforms.ToTensor()(PIL.Image.open(filename0))
        img1    = torchvision.transforms.ToTensor()(PIL.Image.open(filename1))
        with GLOBALS.processing_lock:
            output  = matchmodel.bruteforce_match(img0, img1, seg0, seg1, matchmodel, n=5000, cyclic_threshold=4, dev='cpu') #TODO: larger n
            print()
            print(len(output['points0']))
            print('Matched percentage:', output['matched_percentage'])
            print()
            output['success'] = success = (len(output['points0'])>=16)
            output['n_matched_points'] = len(output['points0'])
            output['tracking_model']     = GLOBALS.settings.tracking_active_model
            output['segmentation_model'] = GLOBALS.settings.active_model
    else:
        output      = {
            'points0'            : np.asarray(previous_data['points0']).reshape(-1,2),
            'points1'            : np.asarray(previous_data['points1']).reshape(-1,2),
            'n_matched_points'   : previous_data['n_matched_points'],
            'tracking_model'     : previous_data['tracking_model'],
            'segmentation_model' : previous_data['segmentation_model'],
        }
        corrections = np.array(previous_data['corrections']).reshape(-1,4)
        if len(corrections)>0:
            imap   = np.load(f'{filename0}.{os.path.basename(filename1)}.imap.npy').astype('float32')
            corrections_p0 = corrections[:,:2][:,::-1] #xy to yx
            corrections_p1 = corrections[:,2:][:,::-1]
            corrections_p0 = np.stack([
                scipy.ndimage.map_coordinates(imap[...,0], corrections_p0.T, order=1),
                scipy.ndimage.map_coordinates(imap[...,1], corrections_p0.T, order=1),
            ], axis=-1)
            output['points0'] = np.concatenate([output['points0'], corrections_p0])
            output['points1'] = np.concatenate([output['points1'], corrections_p1])
        success = output['success'] = (len(output['points1'])>=1)
    
    if success:
        imap    = matchmodel.interpolation_map(output['points1'], output['points0'], seg0.shape)
    else:
        #dummy interpolation map
        imap    = matchmodel.interpolation_map(np.zeros([1,2]), np.zeros([1,2]), seg0.shape)
    
    np.save(f'{filename0}.{os.path.basename(filename1)}.imap.npy', imap.astype('float16'))  #f16 to save space & time

    warped_seg0 = matchmodel.warp(seg0, imap)
    gmap        = matchmodel.create_growth_map_rgba( warped_seg0>0.5, seg1>0.5, )
    output_file = f'{filename0}.{os.path.basename(filename1)}.growthmap.png'
    PIL.Image.fromarray(gmap).convert('RGB').save( output_file )
    output['growthmap'] = output_file

    output_file = f'{filename0}.{os.path.basename(filename1)}.growthmap_rgba.png'
    PIL.Image.fromarray(gmap).save( output_file )
    output['growthmap_rgba'] = output_file
    output['segmentation0']  = seg0f
    output['segmentation1']  = seg1f

    output['statistics']     = compute_statistics(gmap)

    return output


def run_segmentation(imgfile):
    return backend.call_with_optional_kwargs(GLOBALS.model.process_image, imgfile, threshold=None)


#FIXME: this kind of doesnt belong here
def skeletonized_growthmap(gmap):
    import skimage.morphology
    seg0w = (gmap==1) | (gmap==2)  #warped segmentation 0 = same+decay
    seg1  = (gmap==1) | (gmap==3)  #segmentation 1        = same+growth
    sk0   = skimage.morphology.skeletonize(seg0w)
    sk1   = skimage.morphology.skeletonize(seg1)
    return np.stack([
        np.zeros_like(sk0),
        (sk1 == 1) & (gmap == 1),
        (sk0 == 1) & (gmap == 2),
        (sk1 == 1) & (gmap == 3),
    ]).argmax(0)


def compute_statistics(turnovermap_rgba):
    #convert rgb to labels  #FIXME: should pass a labeled map as argument
    turnovermap = np.stack([
        (turnovermap_rgba == ( 39, 54, 59,  0)).all(-1),
        (turnovermap_rgba == (255,255,255,255)).all(-1),
        (turnovermap_rgba == (226,106,116,255)).all(-1),
        (turnovermap_rgba == ( 96,209,130,255)).all(-1),
    ]).argmax(0)

    turnovermap_sk = skeletonized_growthmap(turnovermap)

    return {
        'sum_same' :        int( (turnovermap==1).sum() ),
        'sum_decay' :       int( (turnovermap==2).sum() ),
        'sum_growth':       int( (turnovermap==3).sum() ),
        'sum_negative':     int( (turnovermap==0).sum() ),
        'sum_same_sk' :     int( (turnovermap_sk==1).sum() ),
        'sum_decay_sk' :    int( (turnovermap_sk==2).sum() ),
        'sum_growth_sk':    int( (turnovermap_sk==3).sum() ),
        'sum_negative_sk':  int( (turnovermap_sk==0).sum() ),
    }
