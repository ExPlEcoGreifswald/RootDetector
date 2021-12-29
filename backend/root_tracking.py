import os
import torch, torchvision
import numpy as np
import scipy.ndimage
import cloudpickle
import PIL.Image







def process(filename0, filename1, corrections=None):
    print(f'Performing root tracking on files {filename0} and {filename1}')
    segmodel   = cloudpickle.load(open('models/root_tracking_models/019c_segmodel.full.cpkl', 'rb'))
    matchmodel = cloudpickle.load(open('models/root_tracking_models/019c_contrastive_model.full.cpkl', 'rb'))

    img0    = torchvision.transforms.ToTensor()(PIL.Image.open(filename0))
    img1    = torchvision.transforms.ToTensor()(PIL.Image.open(filename1))

    seg0    = run_segmentation(segmodel, img0, dev='cpu')
    seg1    = run_segmentation(segmodel, img1, dev='cpu')

    if corrections is None:
        output  = bruteforce_match(img0, img1, seg0, seg1, matchmodel, n=5000, cyclic_threshold=4, dev='cpu')
        imap    = interpolation_map(output['points0'], output['points1'], img0.shape[-2:])
    else:
        with np.load(f'{filename0}.{os.path.basename(filename1)}.imap.npz', allow_pickle=True) as npz_file:
            imap    = npz_file['imap']
        output = cloudpickle.load( open(f'{filename0}.{os.path.basename(filename1)}.bfm.pkl','rb') )
        corrections    = np.array(corrections)
        corrections_p1 = corrections[:,:2][:,::-1]
        corrections_p0 = corrections[:,2:][:,::-1]
        corrections_p1 = np.stack([
            scipy.ndimage.map_coordinates(imap[...,0], corrections_p1.T, order=1),
            scipy.ndimage.map_coordinates(imap[...,1], corrections_p1.T, order=1),
        ], axis=-1)
        output['points0'] = np.concatenate([output['points0'], corrections_p0])
        output['points1'] = np.concatenate([output['points1'], corrections_p1])
        imap    = interpolation_map(output['points0'], output['points1'], img0.shape[-2:])
    np.savez_compressed(f'{filename0}.{os.path.basename(filename1)}.imap.npz', imap=imap)
    open(f'{filename0}.{os.path.basename(filename1)}.bfm.pkl','wb').write(cloudpickle.dumps(output))

    gmap    = create_growth_map( seg0>0.5,  warp(seg1, imap)>0.5 )
    output_file = f'{filename0}.{os.path.basename(filename1)}.growthmap.png'
    PIL.Image.fromarray(gmap).save( output_file )
    output['growthmap'] = output_file

    gmap        = create_growth_map_rgba( seg0>0.5,  warp(seg1, imap)>0.5 )
    output_file = f'{filename0}.{os.path.basename(filename1)}.growthmap_rgba.png'
    PIL.Image.fromarray(gmap).save( output_file )
    output['growthmap_rgba'] = output_file

    print()
    print(len(output['points0']))
    print('Matched percentage:', output['matched_percentage'])
    print()
    return output


def run_segmentation(segmodel, img, dev='cpu'):
    seg = segmodel.to(dev)( img[None].to(dev) )[0,0].cpu().numpy()
    segmodel.cpu(); torch.cuda.empty_cache() if dev=='cuda' else None;
    return seg


#TODO: package
import skimage.morphology as skmorph
def bruteforce_match(img0, img1, seg0, seg1, contrastive_model, n=100, ratio_threshold=1.1, cyclic_threshold=4, dev='cpu'):
    ft0  = contrastive_model.to(dev)( img0[None].to(dev), return_features=True )[0].cpu()
    ft1  = contrastive_model.to(dev)( img1[None].to(dev), return_features=True )[0].cpu()
    contrastive_model.cpu(); torch.cuda.empty_cache() if dev=='cuda' else None;
    
    skl0       = skmorph.skeletonize(seg0>0.5)
    skl1       = skmorph.skeletonize(seg1>0.5)
    skl_p0     = np.argwhere(skl0)
    skl_p1     = np.argwhere(skl1)
    
    c = 16
    dtype      = torch.float16 if dev=='cuda' else torch.float32
    bx_ft0     = extract_descriptors(ft0[None], [torch.as_tensor(skl_p0)], bx_size=64, dsc_size=c).to(dtype).to(dev)
    bx_ft1     = extract_descriptors(ft1[None], [torch.as_tensor(skl_p1)], bx_size=64, dsc_size=c).to(dtype).to(dev)
    
    result     = {
        'points0':np.array([], 'int16').reshape(-1,2),
        'points1':np.array([], 'int16').reshape(-1,2),
        'scores' :np.array([], 'float32'),
        'ratios' :np.array([], 'float32'),
        'matched_percentage':0,
    }
    if len(skl_p1)==0 or len(skl_p0)==0:
        return result
    
    ixs        = np.random.permutation(len(skl_p0))
    step       = 512
    for i in range(0,n,step):
        if i >= len(ixs)-1:
            break
        i       = ixs[:n][i:][:step]
        p       = skl_p0[i]
        dists_i = torch.einsum('nchw,mchw->nm', bx_ft0[i], bx_ft1).cpu().float() / c**2
        dists_i = dists_i/2+0.5  #range 0..1
        ix1     = dists_i.argmax(-1)
        yx1     = skl_p1[ix1]
        score   = dists_i.max(-1)[0]
        #set dists within 64px of yx1 to zero to find second largest peak
        dists_i_ = dists_i.clone().numpy()
        dists_i_[np.abs(skl_p1[None] - yx1[:,None]).min(-1)<64] = 0
        score_k2 = dists_i_.max(-1)
        ratio    = score/score_k2
        
        ratio_ok = (ratio > ratio_threshold)
            
        if cyclic_threshold >= 0:
            dists_cyc = torch.einsum('mchw,nchw->mn', bx_ft1[ix1], bx_ft0 ).cpu() / c**2
            dists_cyc = dists_cyc/2+0.5
            yx_cyc    = skl_p0[dists_cyc.argmax(-1)]
            cyclic_ok = (np.sum((yx_cyc - p)**2, axis=-1)**0.5 < cyclic_threshold)
        else:
            cyclic_ok = np.ones_like(ratio_ok)
        
        all_ok = np.array(ratio_ok & cyclic_ok).astype(bool)
        result['points0'] = np.concatenate([result['points0'], p[all_ok]]).astype('int16')
        result['points1'] = np.concatenate([result['points1'], yx1[all_ok]]).astype('int16')
        result['scores']  = np.concatenate([result['scores'],  score[all_ok]])
        result['ratios']  = np.concatenate([result['ratios'],  ratio[all_ok]])
    result['matched_percentage'] = len(result['points0']) / np.int32(len(skl_p0))
    return result

def extract_descriptors(x, pts_yx:list, bx_size=64, dsc_size=16):
    pts_xy = [torch.flip(yx, dims=[1]) for yx in pts_yx]
    boxes  = [torch.cat([xy-bx_size//2, xy+bx_size//2,], -1).float() for xy in pts_xy]
    dsc    = torchvision.ops.roi_align(x, boxes, dsc_size, sampling_ratio=1)
    return dsc


def filter_points(p0, p1, threshold=50):
    delta  = (p1-p0)
    median = np.median(delta, axis=0)
    dev    = ((delta - median)**2).sum(-1)**0.5
    return p0[dev<threshold], p1[dev<threshold]

def interpolation_map(p0,p1, shape):
    p0,p1 = filter_points(p0,p1)
    if len(p0)<10:
        return None
    delta = (p1 - p0).astype('float32')
    Y,X   = np.meshgrid(np.arange(shape[0]), np.arange(shape[1]), indexing='ij')
    delta_nearest = np.stack([
        scipy.interpolate.griddata( p0, delta[:,0], (Y,X), method='nearest' ),  
        scipy.interpolate.griddata( p0, delta[:,1], (Y,X), method='nearest' ),
    ], axis=-1)
    delta_linear = np.stack([
        scipy.interpolate.griddata( p0, delta[:,0], (Y,X), method='linear' ),  
        scipy.interpolate.griddata( p0, delta[:,1], (Y,X), method='linear' ),
    ], axis=-1)
    delta = np.where( np.isfinite(delta_linear), delta_linear, delta_nearest )
    return delta + np.stack([Y,X], axis=-1)

def create_growth_map(seg0, seg1):
    gmap = np.zeros( seg0.shape[:2]+(3,), 'uint8' )
    isec = seg0 * seg1
    gmap[:]            = ( 39, 54, 59)
    gmap[isec]         = (255,255,255)
    gmap[seg0 * ~isec] = (226,106,116)
    gmap[seg1 * ~isec] = ( 96,209,130)
    return gmap

def create_growth_map_rgba(seg0, seg1):
    gmap = np.zeros( seg0.shape[:2]+(4,), 'uint8' )
    isec = seg0 * seg1
    gmap[:]            = (  0,  0,  0,  0)
    gmap[isec]         = (255,255,255,255)
    gmap[seg0 * ~isec] = (226,106,116,255)
    gmap[seg1 * ~isec] = ( 96,209,130,255)
    return gmap


def warp(seg, imap):
    return scipy.ndimage.map_coordinates(seg, imap.transpose(2,0,1))
