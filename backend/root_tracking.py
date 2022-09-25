import os, typing as tp
import torch, torchvision
import numpy as np
import scipy.ndimage
import PIL.Image


import backend
from backend import GLOBALS



def process(filename0, filename1, settings, previous_data:dict=None):
    print(f'Performing root tracking on files {filename0} and {filename1}')
    matchmodel = settings.models['tracking']

    seg0f, seg0 = ensure_segmentation(filename0, settings)
    seg1f, seg1 = ensure_segmentation(filename1, settings)
    exmask0     = ensure_exclusionmask(filename0, settings)
    #exmask1     = ensure_exclusionmask(filename1, settings)  #not required
    
    if previous_data is None:  #FIXME: better condition?
        img0    = torchvision.transforms.ToTensor()(PIL.Image.open(filename0))
        img1    = torchvision.transforms.ToTensor()(PIL.Image.open(filename1))
        with GLOBALS.processing_lock:
            device  = 'cuda' if settings.use_gpu and torch.cuda.is_available() else 'cpu'
            output  = matchmodel.bruteforce_match(img0, img1, seg0, seg1, matchmodel, n=5000, cyclic_threshold=4, dev=device) #TODO: larger n
            print()
            print(len(output['points0']))
            print('Matched percentage:', output['matched_percentage'])
            print()
            output['success'] = success = (len(output['points0'])>=16)
            output['n_matched_points'] = len(output['points0'])
            output['tracking_model']     = settings.active_models['tracking']
            output['segmentation_model'] = settings.active_models['detection']
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

    warped_seg0    = matchmodel.warp(seg0, imap)
    warped_exmask0 = None
    if exmask0 is not None:
        warped_exmask0 = matchmodel.warp(exmask0, imap)
    gmap           = matchmodel.create_growth_map_rgba( warped_seg0>0.5, seg1>0.5, )
    gmap           = paste_exclusionmask(gmap, warped_exmask0)

    output_file_rgb  = f'{filename0}.{os.path.basename(filename1)}.growthmap.png'
    output_file_rgba = f'{filename0}.{os.path.basename(filename1)}.growthmap_rgba.png'
    PIL.Image.fromarray(gmap).convert('RGB').save( output_file_rgb )
    PIL.Image.fromarray(gmap).save( output_file_rgba )

    output['growthmap']      = output_file_rgb
    output['growthmap_rgba'] = output_file_rgba
    output['segmentation0']  = seg0f
    output['segmentation1']  = seg1f

    output['statistics']     = compute_statistics(gmap)

    return output


def ensure_segmentation(input_image_path:str, settings:'backend.Settings') -> (str, np.ndarray):
    '''Run root detection (without a threshold) or load a cached result'''
    segf = f'{input_image_path}.segmentation.cache.png'
    if not os.path.exists(segf):
        seg = backend.root_detection.run_model(input_image_path, settings, 'detection', threshold=None)
        backend.write_as_png(segf, seg)
    else:
        seg = PIL.Image.open(segf).convert('L') / np.float32(255)
    return segf, seg


def ensure_exclusionmask(input_image_path:str, settings:'backend.Settings') -> np.ndarray:
    '''Run exclusion mask detection (if enabled) or load a custom mask or retrieve a cached result'''
    exmaskf = f'{input_image_path}.exclusionmask.cache.png'
    if not os.path.exists(exmaskf):
        exmask = backend.root_detection.maybe_compute_exclusionmask(input_image_path, settings)
        if exmask is not None:
            backend.write_as_png(exmaskf, exmask)
    else:
        exmask = PIL.Image.open(exmaskf).convert('L') / np.float32(255)
    return exmask


class COLORS:
    NEGATIVE = ( 39, 54, 59,  0)
    SAME     = (255,255,255,255)
    DECAY    = (226,106,116,255)
    GROWTH   = ( 96,209,130,255)
    EXMASK   = (255,  0,  0,255)

def paste_exclusionmask(turnovermap_rgba:np.ndarray, exmask:tp.Union[np.ndarray, None]) -> np.ndarray:
    if exmask is None:
        return turnovermap_rgba
    return np.where(exmask[...,None]>0, COLORS.EXMASK, turnovermap_rgba).astype('uint8')


def skeletonized_turnovermap(gmap):
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

def turnovermap_from_rgba(rgba:np.ndarray) -> np.ndarray:
    '''Convert a RGBA encoded turnover map into a labeled array
       with classes 0(negative),1(same),2(decay),3(growth),4(exclude)'''
    
    return np.stack([
        (rgba == COLORS.NEGATIVE).all(-1),
        (rgba == COLORS.SAME).all(-1),
        (rgba == COLORS.DECAY).all(-1),
        (rgba == COLORS.GROWTH).all(-1),
        (rgba == COLORS.EXMASK).all(-1),
    ]).argmax(0)


def compute_statistics(turnovermap_rgba):
    turnovermap    = turnovermap_from_rgba(turnovermap_rgba)
    turnovermap_sk = skeletonized_turnovermap(turnovermap)

    kimura_same   = backend.postprocessing.kimura_length(turnovermap_sk==1)
    kimura_decay  = backend.postprocessing.kimura_length(turnovermap_sk==2)
    kimura_growth = backend.postprocessing.kimura_length(turnovermap_sk==3)

    return {
        'sum_same' :        int( (turnovermap==1).sum() ),
        'sum_decay' :       int( (turnovermap==2).sum() ),
        'sum_growth':       int( (turnovermap==3).sum() ),
        'sum_negative':     int( (turnovermap==0).sum() ),
        'sum_exmask':       int( (turnovermap==4).sum() ),

        'sum_same_sk' :     int( (turnovermap_sk==1).sum() ),
        'sum_decay_sk' :    int( (turnovermap_sk==2).sum() ),
        'sum_growth_sk':    int( (turnovermap_sk==3).sum() ),
        'sum_negative_sk':  int( (turnovermap_sk==0).sum() ),

        'kimura_same':      int( kimura_same ),
        'kimura_decay':     int( kimura_decay ),
        'kimura_growth':    int( kimura_growth ),
    }
