import backend.evaluation

import zipfile, tempfile, os
import PIL.Image
import numpy as np


def test_evaluate_single():
    ytrue = np.zeros([100,100], 'uint8')
    ytrue[:,:50] = 255
    ypred = np.zeros([100,100], 'uint8')
    ypred[:50]   = 255

    tmpdir    = tempfile.TemporaryDirectory()
    ytrue_png = os.path.join(tmpdir.name, 'AAA.png')
    ypred_png = os.path.join(tmpdir.name, 'AAA.tiff.segmentation.png')
    PIL.Image.fromarray(ytrue).save(ytrue_png)
    PIL.Image.fromarray(ypred).save(ypred_png)

    evresult = backend.evaluation.evaluate_single_file(ypred_png, ytrue_png)
    assert np.allclose(evresult['IoU'], 1/3)

    outputfile = os.path.join(tmpdir.name, 'evaluation.zip')
    backend.evaluation.save_evaluation_results([evresult], outputfile)
    assert os.path.exists(outputfile)
    with zipfile.ZipFile(outputfile) as archive:
        contents = archive.namelist()
        assert 'statistics.csv'    in contents
        csv_stats = archive.read('statistics.csv').decode('utf8').strip().split('\n')
        assert len(csv_stats) == 2
        assert csv_stats[0].startswith('#')
        assert csv_stats[1].split(',')[0].strip() == 'AAA.tiff'
        assert csv_stats[1].split(',')[1].strip() == '0.33'
        
        assert 'AAA.tiff/error_map.png' in contents


#TODO
#def test_evaluate_with_exclusionmask



def test_IoU():
    a = np.zeros([100,100])
    b = np.zeros([100,100])
    b[:50] = 1
    assert backend.evaluation.IoU(a,b) == 0

    c = np.zeros([100,100])
    c[:,:50] = 1
    assert np.allclose(backend.evaluation.IoU(c,b) , 1/3)


def test_error_map():
    ytrue = np.zeros([100,100])
    ytrue[:,:50] = 1
    ypred = np.zeros([100,100])
    ypred[:50] = 1

    errormap = backend.evaluation.create_error_map(ytrue, ypred)
    assert np.all(errormap[:50,:50] == (0,1,0)) #green true positive
    assert np.all(errormap[:50,50:] == (1,0,0)) #red   false positive
    assert np.all(errormap[50:,:50] == (0,0,1)) #blue  false negative
    assert np.all(errormap[50:,50:] == (0,0,0)) #black true negative
