import sys, time, os, io, warnings, importlib
import typing as tp
import numpy as np
import torch, torchvision
from torchvision.models._utils import IntermediateLayerGetter
import PIL.Image

warnings.simplefilter('ignore') #pytorch is too noisy


if "__torch_package__" in dir():
    #inside a torch package
    import torch_package_importer
    import_func = torch_package_importer.import_module 
else:
    #normal
    import importlib
    import_func = lambda m, p: importlib.reload(importlib.import_module(m, p))

#internal modules
MODULES = ['datasets', 'training']
[datasets, traininglib] = [import_func(('.' if __package__ else '')+m, __package__) for m in MODULES]




class UNet(torch.nn.Module):
    class UpBlock(torch.nn.Module):
        def __init__(self, in_c, out_c, inter_c=None):
            #super().__init__()
            torch.nn.Module.__init__(self)
            inter_c        = inter_c or out_c
            self.conv1x1   = torch.nn.Conv2d(in_c, inter_c, 1)
            self.convblock = torch.nn.Sequential(
                torch.nn.Conv2d(inter_c, out_c, 3, padding=1, bias=0),
                torch.nn.BatchNorm2d(out_c),
                #torch.nn.ReLU(),
            )
        def forward(self, x, skip_x, relu=True):
            x = torch.nn.functional.interpolate(x, skip_x.shape[2:])
            x = torch.cat([x, skip_x], dim=1)
            x = self.conv1x1(x)
            x = self.convblock(x)
            x = torch.relu(x) if relu else x
            return x
    
    def __init__(self, backbone='mobilenet3l', colors=['WHITE'], pretrained:bool=True):
        torch.nn.Module.__init__(self)
        factory_func = globals().get(f'{backbone}_backbone', None)
        if factory_func is None:
            raise NotImplementedError(backbone)
        self.backbone, C = factory_func(pretrained)
        
        self.up0 = self.UpBlock(C[-1]    + C[-2],  C[-2])
        self.up1 = self.UpBlock(C[-2]    + C[-3],  C[-3])
        self.up2 = self.UpBlock(C[-3]    + C[-4],  C[-4])
        self.up3 = self.UpBlock(C[-4]    + C[-5],  C[-5])
        self.up4 = self.UpBlock(C[-5]    + 3,      32)
        self.cls = torch.nn.Conv2d(32, 1, 3, padding=1)

        self.colors = [getattr(datasets, c) for c in colors]
    
    def forward(self, x, return_features=False, sigmoid=True):
        device = list(self.parameters())[0].device
        x      = x.to(device)
        
        X = self.backbone(x)
        X = ([x] + [X[f'out{i}'] for i in range(5)])[::-1]
        x = X.pop(0)
        x = self.up0(x, X[0])
        x = self.up1(x, X[1])
        x = self.up2(x, X[2])
        x = self.up3(x, X[3])
        x = self.up4(x, X[4], relu=not return_features)
        if return_features:
            return normalize(x)
        x = self.cls(x)
        if sigmoid:
            x = torch.sigmoid(x)
        return x
    
    def load_image(self, path):
        return PIL.Image.open(path).convert('RGB') / np.float32(255)
    
    def process_image(self, image, progress_callback=lambda *x:None, threshold=0.5):
        #TODO? slice into patches
        if isinstance(image, str):
            image = self.load_image(image)
        
        imageshape = image.shape
        patches = datasets.slice_into_patches_with_overlap(image, patchsize=1280, slack=128)
        with torch.no_grad():
            outputpatches = []
            for patch in patches:
                x = torchvision.transforms.ToTensor()(patch)
                y = self.eval()(x[None]).cpu()[0,0]
                outputpatches += [y.numpy()]
        output = datasets.stitch_overlapping_patches(outputpatches, imageshape, slack=128)
        if threshold is not None:
            output = (output > threshold)*1
        return output

    def start_training(self, 
                       imagefiles_train,      targetfiles_train, 
                       imagefiles_valid=None, targetfiles_valid=None, 
                       epochs=100,            lr=1e-3, 
                       callback=None,         num_workers='auto',
                       ds_kwargs={},          task_kwargs={},
                       fit_kwargs={},
                       ):
        task     = traininglib.SegmentationTask(self, epochs=epochs, lr=lr, callback=callback, **task_kwargs)
        ds_train = datasets.Dataset(imagefiles_train, targetfiles_train, augment=True, colors=self.colors, **ds_kwargs)
        ld_train = ds_train.create_dataloader(batch_size=8, shuffle=True, num_workers=num_workers)
        ld_valid = None
        if imagefiles_valid is not None and targetfiles_valid is not None:
            ds_valid = datasets.Dataset(imagefiles_valid, targetfiles_valid, augment=False, colors=self.colors, patchsize=5000, **ds_kwargs)  #full sized images
            ld_valid = ds_valid.create_dataloader(batch_size=1, shuffle=False, num_workers=num_workers)
        self.requires_grad_(True)
        task.fit(ld_train, ld_valid, epochs, **fit_kwargs)
        self.eval().cpu().requires_grad_(False)

    def stop_training(self):
        traininglib.SegmentationTask.request_stop()

    def save(self, destination):
        if isinstance(destination, str):
            destination = time.strftime(destination)
            if not destination.endswith('.pt.zip'):
                destination += '.pt.zip'
        try:
            import torch_package_importer as imp
            #re-export
            importer = (imp, torch.package.sys_importer)
        except ImportError as e:
            #first export
            importer = (torch.package.sys_importer,)
        with torch.package.PackageExporter(destination, importer) as pe:
            interns = [__name__.split('.')[-1]]+MODULES
            pe.intern(interns)
            pe.extern('**', exclude=['torchvision.**'])
            externs = ['torchvision.ops.**', 'torchvision.datasets.**', 'torchvision.io.**', 'torchvision.models.*']
            pe.intern('torchvision.**', exclude=externs)
            pe.extern(externs)
            
            #force inclusion of internal modules + re-save if importlib.reload'ed
            for inmod in interns:
                inmod_pkg = f'{__package__}.{inmod}' if __package__ else inmod
                if inmod_pkg in sys.modules:
                    pe.save_source_file(inmod, sys.modules[inmod_pkg].__file__, dependencies=True)
                else:
                    pe.save_source_string(inmod, importer[0].get_source(inmod))
            
            pe.save_pickle('model', 'model.pkl', self)
        return destination


def normalize(x, axis=-3):
    denom = (x**2).sum(axis, keepdims=True)**0.5
    return x / denom


def resnet18_backbone(pretrained:bool):
    base = torchvision.models.resnet18(pretrained=pretrained)
    return_layers = dict(relu='out0', layer1='out1', layer2='out2', layer3='out3', layer4='out4')
    backbone = IntermediateLayerGetter(base, return_layers)
    channels = [64, 64, 128, 256, 512]
    return backbone, channels

def mobilenet2_backbone(pretrained:bool):
    base = torchvision.models.mobilenet_v2(pretrained=pretrained).features
    return_layers = {'1':'out0', '3':'out1', '6':'out2', '13':'out3', '18':'out4'}
    backbone = IntermediateLayerGetter(base, return_layers)
    channels = [16, 24, 32, 96, 1280]
    return backbone, channels

def mobilenet3s_backbone(pretrained:bool):
    base = torchvision.models.mobilenet_v3_small(pretrained=pretrained).features
    return_layers = {'0':'out0', '1':'out1', '3':'out2', '8':'out3', '12':'out4'}
    backbone = IntermediateLayerGetter(base, return_layers)
    channels = [16, 16, 24, 48, 576]
    return backbone, channels

def mobilenet3s_mini_backbone(pretrained:bool):
    base = torchvision.models.mobilenet_v3_small(pretrained=pretrained).features
    return_layers = {'0':'out0', '1':'out1', '3':'out2', '8':'out3', '9':'out4'}
    backbone = IntermediateLayerGetter(base, return_layers)
    channels = [16, 16, 24, 48, 96]
    return backbone, channels

def mobilenet3l_backbone(pretrained:bool):
    base = torchvision.models.mobilenet_v3_large(pretrained=pretrained).features
    return_layers = {'1':'out0', '3':'out1', '6':'out2', '10':'out3', '16':'out4'}
    backbone = IntermediateLayerGetter(base, return_layers)
    channels = [16, 24, 40, 80, 960]
    return backbone, channels

