import glob, tempfile, os
import PIL.Image
import numpy as np
import torch, torchvision


WHITE  = (255,255,255)
GREEN  = (  0,255,  0)
RED    = (255,  0,  0)
BLUE   = (  0,  0,255)
BLACK  = (  0,  0,  0)


class Dataset:
    def __init__(self, inputfiles, targetfiles, patchsize=512, augment=False, colors=[WHITE, GREEN]):
        self.augment      = augment
        self.patchsize    = patchsize
        self.colors       = colors
        self.inputfiles   = inputfiles
        self.targetfiles  = targetfiles
        self.cachedir     = tempfile.TemporaryDirectory(prefix='delete_me_cache_', dir='.')
        print(self.cachedir.name)
        self.n_patches     = self._load_and_cache_all(inputfiles, targetfiles)

        self.transform    = torchvision.transforms.Compose([torchvision.transforms.ToTensor()])
        if self.augment:
            self.transform.transforms += [
                torchvision.transforms.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.2, hue=0.02)
            ]
    
    def _load_and_cache_all(self, imagefiles, targetfiles):
        i = 0
        for image_f, target_f in zip(imagefiles, targetfiles):
            image  = PIL.Image.open(image_f).convert('RGB') * np.uint8(1)
            target = self.load_target_image(target_f)
            assert image.shape[:2] == target.shape[:2]
            image_patches  = slice_into_patches_with_overlap(image, self.patchsize)
            target_patches = slice_into_patches_with_overlap(target[...,np.newaxis], self.patchsize)
            for image_p, target_p in zip(image_patches, target_patches):
                PIL.Image.fromarray(image_p).save(self.cachedir.name+f'/{i}.jpg', quality=100)
                PIL.Image.fromarray(target_p.squeeze()).save(self.cachedir.name+f'/{i}.png')
                i += 1
        return i
    
    def __len__(self):
        return self.n_patches
    def __getitem__(self, i):
        image         = PIL.Image.open(self.cachedir.name+f'/{i}.jpg') / np.float32(255)
        target        = PIL.Image.open(self.cachedir.name+f'/{i}.png') > np.float32(0.5)
        target        = target[...,np.newaxis].astype(np.float32)
        #augmentation: flips and rotations
        image, target = (image[:,::-1], target[:,::-1]) if self.augment and np.random.random()<0.5 else (image,target)
        image, target = (image[::-1],   target[::-1])   if self.augment and np.random.random()<0.5 else (image,target)
        k             = np.random.randint(4) if self.augment else 0
        image, target = np.rot90(image, k), np.rot90(target, k)
        
        return self.transform(image.copy()), torchvision.transforms.ToTensor()(target.copy())
    
    def load_target_image(self, filename):
        img    = PIL.Image.open(filename).convert('RGB') * np.int8(1)
        result = [np.abs(img - c).sum(-1) < 64 for c in self.colors]
        return np.any(result, axis=0)
    
    def create_dataloader(self, batch_size, shuffle=False, num_workers='auto'):
        if num_workers == 'auto':
            num_workers = os.cpu_count()
        return torch.utils.data.DataLoader(self, batch_size, shuffle,
                                           collate_fn=getattr(self, 'collate_fn', None),
                                           num_workers=num_workers, pin_memory=True,
                                           worker_init_fn=lambda x: np.random.seed(torch.randint(0,1000,(1,))[0].item()+x) )



def grid_for_patches(imageshape, patchsize, slack):
    H,W       = imageshape[:2]
    stepsize  = patchsize - slack
    grid      = np.stack( np.meshgrid( np.minimum( np.arange(patchsize, H+stepsize, stepsize), H ), 
                                      np.minimum( np.arange(patchsize, W+stepsize, stepsize), W ), indexing='ij' ), axis=-1 )
    grid      = np.concatenate([grid-patchsize, grid], axis=-1)
    grid      = np.maximum(0, grid)
    return grid

def slice_into_patches_with_overlap(image, patchsize=1024, slack=32):
    grid      = grid_for_patches(image.shape, patchsize, slack)
    patches   = [image[i0:i1, j0:j1] for i0,j0,i1,j1 in grid.reshape(-1, 4)]
    return patches

def stitch_overlapping_patches(patches, imageshape, slack=32, out=None):
    patchsize = patches[0].shape[0]
    grid      = grid_for_patches(imageshape, patchsize, slack)
    halfslack = slack//2
    i0,i1     = (grid[grid.shape[0]-2,grid.shape[1]-2,(2,3)] - grid[-1,-1,(0,1)])//2
    d0 = np.stack( np.meshgrid( [0]+[ halfslack]*(grid.shape[0]-2)+[           i0]*(grid.shape[0]>1),
                                [0]+[ halfslack]*(grid.shape[1]-2)+[           i1]*(grid.shape[1]>1), indexing='ij' ), axis=-1 )
    d1 = np.stack( np.meshgrid(     [-halfslack]*(grid.shape[0]-1)+[imageshape[0]],      
                                    [-halfslack]*(grid.shape[1]-1)+[imageshape[1]], indexing='ij' ), axis=-1 )
    d  = np.concatenate([d0,d1], axis=-1)
    if out is None:
        out = np.zeros(imageshape[:2]+patches[0].shape[2:])
    for patch,gi,di in zip(patches, d.reshape(-1,4), (grid+d).reshape(-1,4)):
        out[di[0]:di[2], di[1]:di[3]] = patch[gi[0]:gi[2], gi[1]:gi[3]]
    return out

