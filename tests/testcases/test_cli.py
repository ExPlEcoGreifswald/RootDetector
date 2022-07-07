import backend.cli

import zipfile, tempfile, os
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







