import backend.root_detection

import tempfile, os
import numpy as np
import PIL.Image



def test_postprocessing_with_exmask():
    ypred = np.zeros([100,100,3], 'uint8')
    ypred[:50]   = 255
    #exclusion mask
    ypred[:25]   = (255, 0, 0)

    tmpdir    = tempfile.TemporaryDirectory()
    ypred_png = os.path.join(tmpdir.name, 'AAA.tiff.segmentation.png')
    PIL.Image.fromarray(ypred).save(ypred_png)

    out = backend.root_detection.postprocess(ypred_png)
    assert out['statistics']['sum']      == (ypred[25:50,:,0].size)
    assert out['statistics']['sum_mask'] == (ypred[  :25,:,0].size)

