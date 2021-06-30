import numpy as np
import tensorflow as tf
import tensorflow.keras as keras

import skimage.io   as skio
import skimage.util as skimgutil
import tempfile, os


PATCHSIZE = 512


class RootDetector(keras.Model):
    def __init__(self, basemodel=None):
        keras.Model.__init__(self)
        if basemodel is None:
            basemodel = self.build_model()
        self.basemodel = basemodel
        
    def call(self, *x):
        return self.basemodel(*x)
    
    @staticmethod
    def build_model():
        x = in0      = keras.Input((PATCHSIZE,PATCHSIZE,3))
        x            = tf.image.per_image_standardization(x)
        mobilenet    = keras.applications.MobileNet(include_top=False, weights='imagenet')
        #skiplayers   = ['conv_dw_1_relu', 'conv_dw_2_relu', 'conv_dw_4_relu', 'conv_dw_8_relu', 'conv_dw_10_relu']
        skiplayers   = ['conv_dw_1_relu', 'conv_dw_2_relu', 'conv_dw_4_relu', 'conv_dw_8_relu']
        backbone     = keras.Model(mobilenet.input, [l.output for l in mobilenet.layers if l.name in skiplayers])
        X            = backbone(x)[::-1]

        x            = X[0]
        for skip_x in X[1:]:
            x            = keras.layers.BatchNormalization()(x)
            x            = keras.layers.Conv2D(skip_x.shape[-1]//2, (3,3), padding='same', activation='relu')(x)
            x            = tf.image.resize(x, skip_x.shape[1:3], method='bilinear')
            x            = keras.layers.Concatenate()([skip_x, x])

        x            = keras.layers.BatchNormalization()(x)
        x            = keras.layers.Conv2D(32, (3,3), padding='same', activation='relu')(x)
        x = x0       = tf.image.resize(x, in0.shape[1:3], method='bilinear')

        x            = keras.layers.BatchNormalization()(x)
        x            = keras.layers.Conv2D(1,  (3,3), padding='same', activation='sigmoid', name='exclusionmask')(x)

        m            = keras.Model(in0, {'exclusionmask':x})
        return m

    
    def predict_patches(self, patches, callback=None):
        #tta: flip_lr
        tta_patches   = list(patches)+list(patches[:,:,::-1])
        batchsize     = 4
        n_batches     = np.ceil(len(tta_patches) / batchsize)
        def _callback(batch, logs=None):
            if callback is not None:
                callback( batch/n_batches )
        callbacks     = [keras.callbacks.LambdaCallback(on_predict_batch_end=_callback)]
        resultpatches = self.basemodel.predict(np.array(tta_patches), batch_size=batchsize, callbacks=callbacks)
        resultpatches = resultpatches['exclusionmask']
        #un-tta
        resultpatches = (resultpatches[:len(patches)]  + resultpatches[len(patches):,:,::-1])/2
        resultpatches = (resultpatches > 0.5)*1
        return resultpatches
    
    def retrain(self, imagefiles, targetfiles, epochs, callback=lambda e:None):
        ds, _cache0 = build_dataset(imagefiles, targetfiles, trainmode=True, ensure_caching=False)
        return train_model(self, ds, epochs=epochs, progress_callback=callback)
    
    def stop_training(self):
        self.stop_training = True
    
    @staticmethod
    def load_image(imgpath):
        return skio.imread(imgpath)
    
    def process_image(self, image, progress_callback=None):
        #slack,patchsize = 64, 1000
        slack,patchsize = 64, PATCHSIZE
        H,W           = image.shape[:2]
        padded        = np.pad(image, [(0,max(0,patchsize-H)), (0,max(0,patchsize-W)), (0,0)], mode='constant')
        patches       = slice_into_patches_with_overlap(padded, patchsize=patchsize, slack=slack)
        resultpatches = self.predict_patches(patches, callback=progress_callback)
        finalresult   = stitch_overlapping_patches(resultpatches, image.shape, slack=slack )
        finalresult   = finalresult[:H,:W]
        return finalresult
    
    def __getstate__(self):
        tmpdir = tempfile.TemporaryDirectory()
        tmpf   = os.path.join(tmpdir.name, 'basemodel')+'.h5'
        keras.models.save_model(self.basemodel, tmpf, include_optimizer=False)
        return {'basemodel_serialized':open(tmpf, 'rb').read()}
    
    def __setstate__(self, state):
        tmpf = tempfile.NamedTemporaryFile(suffix='.h5', delete=False)
        try:
            tmpf.write(state['basemodel_serialized'])
            basemodel = keras.models.load_model(tmpf.name, compile=False)
            self.__init__(basemodel)
        finally:
            tmpf.close()
            os.unlink(tmpf.name)



def train_model(model, ds_train, ds_valid=None, epochs=5, batch_size=8, progress_callback=lambda e:None):
    ds_train        = ds_train.batch(batch_size)
    ds_valid        = ds_valid.batch(batch_size) if ds_valid is not None else None
    
    callbacks = [
        keras.callbacks.LearningRateScheduler(lambda epoch,lr: lr*0.2 if epoch in [3,4] else lr),
        keras.callbacks.LambdaCallback(on_epoch_end=lambda epoch,logs: progress_callback(epoch))
    ]
    metrics   = [keras.metrics.Precision(), keras.metrics.Recall(), dice_score]
    model.compile(
        keras.optimizers.Adam(learning_rate=0.0005), 
        loss    = {'exclusionmask':weighted_loss(dice_entropy_loss)}, 
        metrics = {'exclusionmask':['accuracy']},
    )
    h = model.fit(ds_train,
                  validation_data=ds_valid,
                  epochs=epochs,
                  callbacks=callbacks)
    return h



#######DATASET##########


CLASS_COLORS = np.array([
    (-1., -1., -1.), #ignore:     none
    (0.0, 0.0, 0.0), #background: black
    (0.2, 1.0, 1.0), #roots:      white,green
    (1.0, 0.0, 0.5), #exclude:    red,pink
])


def load_tristate_labelmask(labelfile):
    labelmask      = skimgutil.img_as_float32(skio.imread(labelfile, as_gray=False))#[...,:3]
    if len(labelmask.shape)==2:
        labelmask = labelmask[...,None]
    labelmask      = labelmask[...,:3]
    labelmask      = np.abs(labelmask - CLASS_COLORS[:,None,None]).sum(-1).argmin(0) -1
    return labelmask

def load_and_slice(args):
    imagefile,labelfile = args
    image         = skio.imread(imagefile.decode('utf8'))[...,:3]
    label         = load_tristate_labelmask(labelfile.decode('utf8'))
    label         = (label==2)  # exclusion mask
    image_patches = slice_into_patches_with_overlap(image, PATCHSIZE)
    label_patches = slice_into_patches_with_overlap(label[...,np.newaxis], PATCHSIZE)
    return skimgutil.img_as_float32(image_patches), label_patches.astype('float32')
ds_load_and_slice = lambda *x: tf.numpy_function(load_and_slice, x, (tf.float32, tf.float32))

@tf.function
def augment(*X):
    X   = list(X)
    X   = [tf.image.flip_up_down(x) for x in X] if tf.random.uniform((1,))[0]<0.5 else X
    X   = [tf.image.flip_up_down(x) for x in X] if tf.random.uniform((1,))[0]<0.5 else X
    k   = tf.random.uniform([1], 0,4, 'int32')[0]
    X   = [tf.image.rot90(x,k) for x in X]
    return X

def reorder(x,y):
    return x, {'exclusionmask':y}

def build_dataset(imagefiles, targetfiles, trainmode=False, ensure_caching=False):
    cachedir = tempfile.TemporaryDirectory(prefix='delete_me_')
    ds       = tf.data.Dataset.from_tensor_slices( list(zip(imagefiles, targetfiles)) )
    ds       = ds.map(ds_load_and_slice, -1).unbatch().cache(cachedir.name+'/cache0')

    if ensure_caching:
        len([1 for _ in ds])
    if trainmode:
        ds = ds.map(augment, -1).shuffle(128)
    ds = ds.map(reorder)
    return ds, cachedir






#######UTILS#########

def n_slices(length, patchsize, slack):
        return int(1 + np.ceil((length-patchsize) / (patchsize-slack)))

def slice_into_patches_with_overlap(image, patchsize=512, slack=32):
    H,W      = image.shape[:2]
    stepsize = patchsize - slack
    n0,n1    = n_slices(H,patchsize,slack), n_slices(W,patchsize,slack)
    slices   = np.array(  [image[max(0,i-patchsize):i]      for i in np.minimum(np.arange(patchsize, H+stepsize, stepsize), H) ]  )
    patches  = np.array(  [slices[:,:,max(0,i-patchsize):i] for i in np.minimum(np.arange(patchsize, W+stepsize, stepsize), W) ]  )
    return patches.transpose(1,0,2,3,4).reshape(n0*n1, min(H,patchsize), min(W,patchsize), -1)

def stitch_overlapping_patches(patches, imageshape, slack=32):
    H,W           = imageshape[:2]
    patchsize     = patches.shape[1]
    h,w           = n_slices(H,patchsize,slack), n_slices(W,patchsize,slack)
    patches       = patches.reshape(h,w,patchsize,patchsize,-1)
    halfslack     = slack//2
    i0            = H - ((patchsize-halfslack)+(patchsize-slack)*(h-2))
    i1            = W - ((patchsize-halfslack)+(patchsize-slack)*(w-2))
    slices        = np.concatenate( [patches[0, :, :-halfslack]] + list(patches[1:-1, :, halfslack:-halfslack]) + ([patches[-1, :, -i0:]] if len(patches)>1 else []), axis=1 )
    image         = np.concatenate( [slices [0, :, :-halfslack]] + list(slices [1:-1, :, halfslack:-halfslack]) + ([slices [-1, :, -i1:]] if len(slices)>1  else []), axis=1 )
    return image





def dice_score(ytrue, ypred):
    d = tf.reduce_sum(ytrue) + tf.reduce_sum(ypred) + 1
    n = 2* tf.reduce_sum(ytrue * ypred ) +1
    return n/d

def dice_score(ytrue, ypred):
    d = tf.reduce_sum(ytrue, axis=[1,2]) + tf.reduce_sum(ypred, axis=[1,2]) + 1
    n = 2* tf.reduce_sum(ytrue * ypred, axis=[1,2] ) +1
    return tf.reduce_mean(n/d, axis=-1)

#masked dice score, negative pixels in the ytrue are ignored
def dice_score(ytrue, ypred):
    mask  = tf.cast(ytrue>=0, tf.float32)
    ytrue = ytrue*mask
    ypred = ypred*mask
    d = tf.reduce_sum(ytrue, axis=[1,2]) + tf.reduce_sum(ypred, axis=[1,2]) + 1
    n = 2* tf.reduce_sum(ytrue * ypred, axis=[1,2] ) +1
    return tf.reduce_mean(n/d, axis=-1)

def dice_loss(ytrue, ypred):
    return 1-dice_score(ytrue,ypred)

def dice_entropy_loss(ytrue, ypred):
    return dice_loss(ytrue, ypred)[:,tf.newaxis, tf.newaxis]*0.01 + tf.losses.binary_crossentropy(ytrue, ypred)*0.99

def weightfunc(x, alpha=2, beta=0.5):
    x = tf.nn.avg_pool2d(x, (5,5), strides=(1,1), padding='SAME')
    return 1-tf.math.tanh( (x-beta)*alpha )**2

def weighted_loss(baseloss):
    def lossfunction(ytrue, ypred):
        return baseloss(ytrue, ypred)[...,tf.newaxis] * weightfunc(ytrue)
    lossfunction.__name__=baseloss.__name__
    return lossfunction