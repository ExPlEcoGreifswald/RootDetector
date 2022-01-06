import os
import torch, torchvision
import numpy as np
import scipy.ndimage
import cloudpickle
import PIL.Image







def process(filename0, filename1, corrections=None, points0=None, points1=None):
    #TODO: wrap in threading.Lock
    print(f'Performing root tracking on files {filename0} and {filename1}')
    segmodel   = cloudpickle.load(open('models/root_tracking_models/019c_segmodel.full.cpkl', 'rb'))
    matchmodel = cloudpickle.load(open('models/root_tracking_models/019c_contrastive_model.full.cpkl', 'rb'))

    if corrections is None:
        img0    = torchvision.transforms.ToTensor()(PIL.Image.open(filename0))
        img1    = torchvision.transforms.ToTensor()(PIL.Image.open(filename1))
        seg0    = run_segmentation(segmodel, img0, dev='cpu')
        seg1    = run_segmentation(segmodel, img1, dev='cpu')
        output  = bruteforce_match(img0, img1, seg0, seg1, matchmodel, n=5000, cyclic_threshold=4, dev='cpu')  #TODO: larger n
        imap    = interpolation_map(output['points0'], output['points1'], img0.shape[-2:])
    else:
        imap   = np.load(f'{filename0}.{os.path.basename(filename1)}.imap.npy').astype('float32')
        output = cloudpickle.load( open(f'{filename0}.{os.path.basename(filename1)}.bfm.pkl','rb') )
        seg0   = PIL.Image.open(f'{filename0}.segmentation.png') / np.float32(255)
        seg1   = PIL.Image.open(f'{filename1}.segmentation.png') / np.float32(255)

        corrections    = np.array(corrections).reshape(-1,4)
        corrections_p1 = corrections[:,:2][:,::-1]
        corrections_p0 = corrections[:,2:][:,::-1]
        corrections_p1 = np.stack([
            scipy.ndimage.map_coordinates(imap[...,0], corrections_p1.T, order=1), #TODO: use scipy.interpolate.LinearNDInterpolator
            scipy.ndimage.map_coordinates(imap[...,1], corrections_p1.T, order=1),
        ], axis=-1)
        output['points0'] = np.concatenate([points0, corrections_p0])
        output['points1'] = np.concatenate([points1, corrections_p1])
        imap    = interpolation_map(output['points0'], output['points1'], seg0.shape)
    
    np.save(f'{filename0}.{os.path.basename(filename1)}.imap.npy', imap.astype('float16'))  #f16 to save space & time
    open(f'{filename0}.{os.path.basename(filename1)}.bfm.pkl','wb').write(cloudpickle.dumps(output))
    PIL.Image.fromarray( (seg0*255).astype('uint8') ).save( f'{filename0}.segmentation.png' )
    PIL.Image.fromarray( (seg1*255).astype('uint8') ).save( f'{filename1}.segmentation.png' )

    warped_seg1 = warp(seg1, imap)
    gmap        = create_growth_map_rgba( seg0>0.5,  warped_seg1>0.5 )
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
        dists_i_[np.abs(skl_p1[None] - yx1[:,None]).min(-1)<64] = 0   #TODO: max instead of min
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
    _p0,_p1 = filter_points(result['points0'], result['points1'])
    result['points0'] = _p0
    result['points1'] = _p1
    return result

def extract_descriptors(x, pts_yx:list, bx_size=64, dsc_size=16):
    pts_xy = [torch.flip(yx, dims=[1]) for yx in pts_yx]
    boxes  = [torch.cat([xy-bx_size//2, xy+bx_size//2,], -1).float() for xy in pts_xy]
    dsc    = torchvision.ops.roi_align(x, boxes, dsc_size, sampling_ratio=1)
    return dsc


def filter_points(p0, p1, threshold=50):
    delta  = (p1-p0)
    median = np.median(delta, axis=0)  #TODO: median not optimal
    dev    = ((delta - median)**2).sum(-1)**0.5
    return p0[dev<threshold], p1[dev<threshold]

def interpolation_map(p0,p1, shape):
    '''Creates a map with coordinates from image1 to image0 according to matched points p0 and p1'''
    #if len(p0)<10:  #TODO
    #    return None
    #direction vectors from each point1 to corresponding point0
    delta = (p1 - p0).astype('float32')
    
    #additional corner points, for extraploation
    cpts  = np.array([(0,0), (0,shape[1]), (shape[0],0), shape])
    #get their values via nearest neighbor
    delta_corners = scipy.interpolate.NearestNDInterpolator(p0, delta)(*cpts.T)
    #add them to the pool of known points
    p0    = np.concatenate([p0, cpts])
    delta = np.concatenate([delta, delta_corners])
    
    #densify the set of sparse points
    Y,X   = np.meshgrid(np.arange(shape[0]), np.arange(shape[1]), indexing='ij')
    delta_linear = scipy.interpolate.LinearNDInterpolator(p0, delta)(Y,X)
    
    #convert from direction vectors to coordinates again
    return delta_linear + np.stack([Y,X], axis=-1)

def create_growth_map_rgba(seg0, seg1):
    gmap = np.zeros( seg0.shape[:2]+(4,), 'uint8' )
    isec = seg0 * seg1
    gmap[:]            = ( 39, 54, 59,  0)
    gmap[isec]         = (255,255,255,255)
    gmap[seg0 * ~isec] = (226,106,116,255)
    gmap[seg1 * ~isec] = ( 96,209,130,255)
    return gmap


def warp(seg, imap):
    return scipy.ndimage.map_coordinates(seg, imap.transpose(2,0,1), order=1)
