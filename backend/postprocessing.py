import numpy as np
import skimage.morphology as skmorph
import scipy.ndimage







def compute_statistics(result, skeletonized_result, mask=None):
    if mask is None:
        mask = np.zeros(result.shape[:2], dtype='bool')
    elif len(mask.shape)>2:
        mask = np.any(mask, axis=-1)
    mask                = (mask > 0) | (result==2)
    result              = np.where(mask, 2, result)
    skeletonized_result = np.where(mask, 2, skeletonized_result)

    N_neg               = (result == 0).sum()
    N_mask              = (result == 2).sum()
    result              = (result              == 1)
    skeletonized_result = (skeletonized_result == 1)*1

    N_o    = compute_orthogonal_connections(skeletonized_result)
    N_d    = compute_diagonal_connections(skeletonized_result)
    kimura = kimura_length(N_o, N_d)
    widths = width_histogram(result, skeletonized_result)
    return {
        'sum' :             int(result.sum()),
        'sum_skeleton' :    int(skeletonized_result.sum()),
        'sum_mask':         int(N_mask),
        'sum_negative':     int(N_neg),
        'connections_orth': int(N_o),
        'connections_diag': int(N_d),
        'kimura_length':    int(kimura),
        'widths':           widths.tolist(),
    }

def skeletonize(image):
    if len(image.shape)>2:
        image = image[...,0]
    skel = skmorph.skeletonize(image==1)
    skel = np.where(image>1, image, skel)
    return skel

def compute_diagonal_connections(x):
    k0 = np.array( [ [0,1],[1,0] ] )
    k1 = np.array( [ [1,0],[0,1] ] )
    r0 = scipy.ndimage.convolve(x, k0, mode='constant')
    r1 = scipy.ndimage.convolve(x, k1, mode='constant')
    return ((r0==2) | (r1==2)).sum()

def compute_orthogonal_connections(x):
    k0 = np.array( [ [1,],[1] ] )
    k1 = np.array( [ [1,   1] ] )
    r0 = scipy.ndimage.convolve(x, k0, mode='constant')
    r1 = scipy.ndimage.convolve(x, k1, mode='constant')
    return ((r0==2) | (r1==2)).sum()

def kimura_length(N_o, N_d):
    '''Kimura, K., Kikuchi, S., & Yamasaki, S. I. (1999). Accurate root length measurement by image analysis. Plant and Soil, 216(1), 117-127.'''
    return ( N_d**2 + (N_d + N_o/2)**2 )**0.5   + N_o/2


def width_histogram(x, x_skel, bin_thresholds=[3,7]):
    d = scipy.ndimage.distance_transform_edt(x)
    w = d[x_skel>0]
    return np.histogram( w, bins=[0.1]+bin_thresholds+[np.inf] )[0]
