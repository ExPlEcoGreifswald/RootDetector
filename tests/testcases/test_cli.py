import backend.cli

import zipfile, tempfile, os, pathlib
import PIL.Image
import numpy as np
import types


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

def test_associate_inputs_to_annotations():
    inputs = [
        'AAA.tiff',
        'AAA.tiff.png',
        'some_folder/BBB.tif',
        'DDD.tiff',
        'EEE.jpg',
    ]
    annotations = [
        'some_other_folder/BBB.tif.png',
        'AAA.png',
        'CCC.png',
        'EEE.segmentation.png'
    ]

    pairs = backend.cli.associate_inputs_to_annotations(inputs, annotations)
    print(pairs)
    assert pairs == [
        (inputs[0], annotations[1]),
        (inputs[2], annotations[0]),
        (inputs[4], annotations[3]),
    ]


def test_write_processing_results():
    tmpdir = tempfile.TemporaryDirectory()
    mockresults = [{
        'filename' : 'path/to/AAA.tiff',
        'result': {
            'segmentation': f'{tmpdir.name}/AAA.tiff.segmentation.png',
            'skeleton':     f'{tmpdir.name}/AAA.tiff.skeleton.png',
            'statistics': {
                'sum':           262183,
                'sum_mask':      736114,
                'sum_negative':  4797853,
                'sum_skeleton':  56863,
                'kimura_length': 62536,
                'widths':        [43034, 11858, 1971],
            }
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
        assert 'statistics.csv'                     in contents




def test_reformat_outputfilename():
    tmpdir = tempfile.TemporaryDirectory()

    x = backend.cli.reformat_outputfilename(tmpdir.name+'/file')
    assert x == tmpdir.name+'/file.zip'

    x = backend.cli.reformat_outputfilename(x)
    assert x == tmpdir.name+'/file.zip'

    open(x, 'w').write('banana')

    x = backend.cli.reformat_outputfilename(x)
    assert x == tmpdir.name+'/file(2).zip'


def test_cli_run_propagates_command_exit_code(monkeypatch):
    args = types.SimpleNamespace(evaluate=False, process=True, training=False)
    parser = types.SimpleNamespace(parse_args=lambda: args)
    monkeypatch.setattr(backend.cli.CLI, 'create_parser', lambda: parser)
    monkeypatch.setattr(backend.cli.CLI, 'process_cli_args', lambda _args: 2)
    assert backend.cli.CLI.run() == 2


def test_cli_run_returns_none_when_no_command_was_requested(monkeypatch):
    args = types.SimpleNamespace(evaluate=False, process=False, training=False)
    parser = types.SimpleNamespace(parse_args=lambda: args)
    monkeypatch.setattr(backend.cli.CLI, 'create_parser', lambda: parser)
    assert backend.cli.CLI.run() is None


def test_cli_processing_keyboard_interrupt_returns_130(tmp_path, monkeypatch):
    image = tmp_path / 'input.png'
    image.write_bytes(b'fixture')

    class Settings:
        models = {}
        exmask_enabled = False

    args = types.SimpleNamespace(
        input=pathlib.Path(str(image)),
        output=pathlib.Path(str(tmp_path / 'output.zip')),
        model=None,
        exclusionmask_model=None,
        no_exclusionmask=True,
    )
    monkeypatch.setattr(backend.cli.backend.settings, 'Settings', Settings)
    monkeypatch.setattr(backend.cli, 'setup_cache', lambda *_args: None)
    monkeypatch.setattr(
        backend.cli.backend.root_detection,
        'process_image',
        lambda *_args: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    assert backend.cli.CLI.process(args) == 130

