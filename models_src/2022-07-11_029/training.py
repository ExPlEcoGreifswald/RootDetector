import numpy as np
import torch, torchvision




class TrainingTask(torch.nn.Module):
    def __init__(self, basemodule, epochs=10, lr=0.001, optim='AdamW', callback=None):
        super().__init__()
        self.basemodule        = basemodule
        self.epochs            = epochs
        self.lr                = lr
        self.progress_callback = callback
        assert optim in ['SGD', 'Adam', 'AdamW']
        self.optim             = optim
    
    def training_step(self, batch):
        raise NotImplementedError()
    def validation_step(self, batch):
        raise NotImplementedError()
    def validation_epoch_end(self, logs):
        raise NotImplementedError()
    
    def configure_optimizers(self):
        if self.optim=='SGD':
            optim = torch.optim.SGD(self.parameters(), self.lr, momentum=0.9, weight_decay=1e-4)
        elif self.optim=='Adam':
            optim = torch.optim.Adam(self.parameters(), self.lr, weight_decay=1e-4)
        elif self.optim=='AdamW':
            optim = torch.optim.AdamW(self.parameters(), self.lr, weight_decay=0.01)
        #steps = [int(self.epochs*i) for i in [0.6,0.8,0.92]]
        #print('Learning rate milestones:', steps)
        #sched = torch.optim.lr_scheduler.MultiStepLR(optim, steps, gamma=0.2)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(optim, self.epochs, eta_min=self.lr*0.01)
        return optim, sched
    
    @property
    def device(self):
        return next(self.parameters()).device
    
    def train_one_epoch(self, loader, optimizer, scheduler=None):
        for i,batch in enumerate(loader):
            if self.__class__.stop_requested:
                break
            loss,logs  = self.training_step(batch)
            
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            logs['lr'] = optimizer.param_groups[0]['lr']
            self.callback.on_batch_end(logs, i, len(loader))
        if scheduler:
            scheduler.step()
    
    def eval_one_epoch(self, loader):
        all_outputs = []
        for i,batch in enumerate(loader):
            outputs, logs  = self.validation_step(batch)
            self.callback.on_batch_end(logs, i, len(loader))
            all_outputs   += [outputs]
        logs = self.validation_epoch_end(all_outputs)
        self.callback.on_batch_end(logs, i, len(loader))
    
    def fit(self, loader_train, loader_valid=None, epochs='auto', device='cuda'):
        self.epochs = epochs
        if epochs == 'auto':
            self.epochs = max(15, 50 // len(loader_train))
            
        if self.progress_callback is not None:
            self.callback = TrainingProgressCallback(self.progress_callback, self.epochs)
        else:
            self.callback = PrintMetricsCallback()
        
        self.train().requires_grad_(True)
        optim, sched  = self.configure_optimizers()
        device = device if torch.cuda.is_available() else 'cpu'
        torch.cuda.empty_cache()
        try:
            self.to(device)
            self.__class__.stop_requested = False
            for e in range(self.epochs):
                if self.__class__.stop_requested:
                    break
                self.train().requires_grad_(True)
                self.train_one_epoch(loader_train, optim, sched)
                
                self.eval().requires_grad_(False)
                if loader_valid:
                    self.eval_one_epoch(loader_valid)
                
                self.callback.on_epoch_end(e)
        except KeyboardInterrupt:
            print('\nInterrupted')
        except Exception as e:
            #prevent the exception getting to ipython (memory leak)
            import traceback
            traceback.print_exc()
            return e
        finally:
            self.zero_grad(set_to_none=True)
            self.eval().cpu().requires_grad_(False)
            torch.cuda.empty_cache()
     
    #XXX: class method to avoid boiler code
    @classmethod
    def request_stop(cls):
        cls.stop_requested = True


class SegmentationTask(TrainingTask):
    def __init__(self, *args, loss='wfocal', loss_kw={}, **kw):
        super().__init__(*args, **kw)
        assert loss  in ['BCE', 'wBCE', 'wBCE+Dice', 'focal', 'wfocal']
        self.loss      = loss
        if 'focal' in loss and loss_kw=={}:
            loss_kw    = {'alpha':0.7, 'gamma':2.0}  #higher alpha to put focus on the positive class
        self.loss_kw   = loss_kw

    def training_step(self, batch):
        x,y     = batch
        x,y     = x.to(self.device), y.to(self.device)
        sigmoid = self.loss not in ['focal', 'wfocal']
        y_seg   = self.basemodule(x, sigmoid=sigmoid)
        if self.loss=='BCE':
            loss0   = torch.nn.functional.binary_cross_entropy(y_seg, y).mean()
        elif self.loss=='wBCE':
            loss0   = weighted_bce_loss(y_seg, y).mean()
        elif self.loss=='wBCE+Dice':
            loss0   = weighted_dice_entropy_loss(y_seg, y).mean()
        elif self.loss=='focal':
            loss0   = torchvision.ops.sigmoid_focal_loss( y_seg, y,  **self.loss_kw).mean()
        elif self.loss=='wfocal':
            loss0   = weighted_focal_loss(y_seg, y,  **self.loss_kw).mean()
        return loss0, {'loss': loss0.item()}
    
    def validation_step(self, batch):
        x,y     = batch
        x,y     = x.to(self.device), y.to(self.device)
        ypred   = self.basemodule(x)
        dice    = dice_score(ypred, y).mean()
        ypred   = (ypred>0.5).float()
        TP      = (ypred *     y).sum([1,2,3]).cpu().numpy()
        FP      = (ypred * (1-y)).sum([1,2,3]).cpu().numpy()
        FN      = ((1-ypred) * y).sum([1,2,3]).cpu().numpy()
        return {
            'precision' : TP/(TP+FP),
            'recall'    : TP/(TP+FN),
            'IoU'       : IoU(y, ypred).cpu().numpy(),
             }, None
    
    def validation_epoch_end(self, outs):
        precision = np.concatenate([o['precision'] for o in outs])
        recall    = np.concatenate([o['recall']    for o in outs])
        iou       = np.concatenate([o['IoU']       for o in outs])
        return {'precision': np.nanmean(precision), 'recall':np.nanmean(recall), 'IoU':np.nanmean(iou)}


def dice_score(ypred, ytrue, eps=1):
    '''Per-image dice score'''
    d = torch.sum(ytrue, dim=[2,3]) + torch.sum(ypred, dim=[2,3]) + eps
    n = 2* torch.sum(ytrue * ypred, dim=[2,3] ) +eps
    return torch.mean(n/d, dim=1)

def dice_loss(ypred, ytrue):
    return 1-dice_score(ypred,ytrue)

def dice_entropy_loss(ypred, ytrue, alpha=0.01, with_logits=False):
    bce_func = torch.nn.functional.binary_cross_entropy_with_logits if with_logits else torch.nn.functional.binary_cross_entropy
    return (  dice_loss(ypred, ytrue)[:,np.newaxis, np.newaxis]*alpha 
            + bce_func(ypred, ytrue, reduction='none')*(1-alpha) ).mean()

def weightfunc(x, alpha=2, beta=0.5):
    x = torch.nn.functional.avg_pool2d(x, kernel_size=(5,5), stride=1, padding=2)
    return 1 + 10 * torch.exp( -(  x - 0.5  )**2 / 0.05 )

def weightfunc(x, alpha=2, beta=0.5):
    x = torch.nn.functional.avg_pool2d(x, kernel_size=(5,5), stride=1, padding=2)
    return 1 - torch.tanh( (x-beta)*alpha )**2

def weighted_loss(baseloss):
    def lossfunction(ypred, ytrue, *args, **kwargs):
        return (baseloss(ypred, ytrue, *args, **kwargs) * weightfunc(ytrue)).mean()
    lossfunction.__name__=baseloss.__name__
    return lossfunction

weighted_dice_entropy_loss    = weighted_loss(dice_entropy_loss)
weighted_bce_loss             = weighted_loss(lambda *x: torch.nn.functional.binary_cross_entropy(*x, reduction='none'))
weighted_bce_loss_with_logits = weighted_loss(lambda *x: torch.nn.functional.binary_cross_entropy_with_logits(*x, reduction='none'))
weighted_focal_loss           = weighted_loss(torchvision.ops.sigmoid_focal_loss)


def IoU(a,b):
    a,b = torch.as_tensor(a).bool(), torch.as_tensor(b).bool()
    #single channel inputs required
    assert a.ndim==2 or a.shape[-3]==1
    intersection = a & b
    union        = a | b
    return (intersection.sum(dim=[-1,-2]) / union.sum(dim=[-1,-2]))




class PrintMetricsCallback:
    '''Prints metrics after each training epoch in a compact table'''
    def __init__(self):
        self.epoch = 0
        self.logs  = {}
        
    def on_epoch_end(self, epoch):
        self.epoch = epoch + 1
        self.logs  = {}
        print() #newline
    
    def on_batch_end(self, logs, batch_i, n_batches):
        if logs is not None:
            self.accumulate_logs(logs)
        percent     = ((batch_i+1) / n_batches)
        metrics_str = ' | '.join([f'{k}:{float(np.mean(v)):>9.5f}' for k,v in self.logs.items()])
        print(f'[{self.epoch:04d}|{percent:.2f}] {metrics_str}', end='\r')
    
    def accumulate_logs(self, newlogs):
        for k,v in newlogs.items():
            self.logs[k] = self.logs.get(k, []) + [v]

class TrainingProgressCallback:
    '''Passes training progress as percentage to a custom callback function'''
    def __init__(self, callback_fn, epochs):
        self.n_epochs    = epochs
        self.epoch       = 0
        self.callback_fn = callback_fn
    
    def on_batch_end(self, logs, batch_i, n_batches):
        percent     = ((batch_i+1) / (n_batches*self.n_epochs))
        percent    += self.epoch / self.n_epochs
        self.callback_fn(percent)
    
    def on_epoch_end(self, epoch):
        self.epoch = epoch + 1
