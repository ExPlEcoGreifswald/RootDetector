import backend.cli

import zipfile, tempfile, os, pathlib
import PIL.Image
import numpy as np


def test_no_ext_file_basename():
    target = 'AD_T046_L002_13.07.18_133359_007_SS'
    file_basename = backend.cli.no_ext_file_basename
    assert target == file_basename('AD_T046_L002_13.07.18_133359_007_SS.png')
    assert target == file_basename('AD_T046_L002_13.07.18_133359_007_SS.tif.segmentation.png')
    assert target == file_basename('AD_T046_L002_13.07.18_133359_007_SS.segmentation.png')
    assert target == file_basename('AD_T046_L002_13.07.18_133359_007_SS.tiff')

    assert target != file_basename('AD_T046_L002_13.07.18_133359_007_SS.tiff.skeleton.png')


def test_associate_predictions_to_annotations_basic():
    predictions = [
        'AAA.tiff.segmentation.png',
        'AAA.tiff.skeleton.png',
        'some_folder/BBB.tif.segmentation.png',
        'DDD.tiff.segmentation.png',
    ]
    annotations = [
        'some_other_folder/BBB.tif.png',
        'AAA.png',
        'CCC.png',
    ]

    pairs = backend.cli.associate_predictions_to_annotations(predictions, annotations)
    assert pairs == [
        (predictions[0], annotations[1]),
        (predictions[2], annotations[0]),
    ]

def test_associate_predictions_to_annotations_zipped():
    annotations = [
        'some_other_folder/BBB.tif.png',
        'AAA.png',
        'CCC.png',
    ]

    tmpdir = tempfile.TemporaryDirectory()
    tmppng = os.path.join(tmpdir.name, 'AAA.tiff.segmentation.png')
    PIL.Image.fromarray(np.ones([100,100,3], 'uint8')).save( tmppng )
    
    tmpzip = os.path.join(tmpdir.name, 'results.zip')
    with zipfile.ZipFile(tmpzip, 'w') as archive:
        archive.open('AAA.tiff.segmentation.png', 'w').write( open(tmppng, 'rb').read() )
    
    predictions = [tmpzip]
    pairs = backend.cli.associate_predictions_to_annotations(predictions, annotations)
    assert len(pairs) == 1
    assert os.path.exists(pairs[0][0]), 'failed to unzip'

def test_write_processing_results():
    tmpdir = tempfile.TemporaryDirectory()
    mockresults = [{
        'filename' : 'path/to/AAA.tiff',
        'result': {
            'segmentation': f'{tmpdir.name}/AAA.tiff.segmentation.png',
            'skeleton':     f'{tmpdir.name}/AAA.tiff.skeleton.png',
        }
    }]
    PIL.Image.fromarray(np.ones([100,100,3], 'uint8')).save( mockresults[0]['result']['segmentation'] )
    PIL.Image.fromarray(np.ones([100,100,3], 'uint8')).save( mockresults[0]['result']['skeleton'] )

    class mockargs:
        output = pathlib.Path(tmpdir.name+'/results')
    backend.cli.CLI.write_results(mockresults, mockargs)

    assert os.path.exists(tmpdir.name+'/results.zip')
    with zipfile.ZipFile(tmpdir.name+'/results.zip', 'r') as archive:
        contents = archive.namelist()
        assert 'AAA.tiff/AAA.tiff.segmentation.png' in contents
        assert 'AAA.tiff/AAA.tiff.skeleton.png'     in contents




def test_reformat_outputfilename():
    tmpdir = tempfile.TemporaryDirectory()

    x = backend.cli.reformat_outputfilename(tmpdir.name+'/file')
    assert x == tmpdir.name+'/file.zip'

    x = backend.cli.reformat_outputfilename(x)
    assert x == tmpdir.name+'/file.zip'

    open(x, 'w').write('banana')

    x = backend.cli.reformat_outputfilename(x)
    assert x == tmpdir.name+'/file(2).zip'



