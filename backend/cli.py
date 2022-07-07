import base.backend.cli as base_cli

import os, argparse, glob, pathlib, zipfile
from . import settings
from . import evaluation
from base.backend.app import get_cache_path


class CLI(base_cli.CLI):

    #override
    @classmethod
    def create_parser(cls):
        parser = super().create_parser(
            description    = 'DigIT! RootDetector',
            default_output = 'results.zip',
        )
        group = parser.add_mutually_exclusive_group(required=False)
        group.add_argument('--evaluate', action='store_true')
        group.add_argument('--process',  action='store_true')

        group = parser.add_argument_group('evaluation arguments')
        group.add_argument('--annotations', default=None, type=pathlib.Path)
        group.add_argument('--predictions', default=None, type=pathlib.Path)
        return parser

    #override
    @classmethod
    def process_cli_args(cls, args):
        if args.evaluate:
            return cls.process_evaluate(args)
        elif args.process:
            print('processing', args)
            raise NotImplementedError()
        else:
            raise NotImplementedError()
        return True

    @staticmethod
    def process_evaluate(args):
        if args.annotations is None or args.predictions is None:
            print('[ERROR] Please specify --annotations and --predictions')
            return 1
        
        annotationfiles = sorted(glob.glob(args.annotations.as_posix(), recursive=True))
        predictionfiles = sorted(glob.glob(args.predictions.as_posix(), recursive=True))
        file_pairs = associate_predictions_to_annotations(predictionfiles, annotationfiles)
        
        print(f'Found {len(file_pairs)} result files and annotations.')
        evresults = [evaluation.evaluate_single_file(*pair) for pair in file_pairs]
        output    = args.output.as_posix()
        output   += ('.zip' if not output.endswith('.zip') else '')
        evaluation.save_evaluation_results(evresults, output)
        print(f'Output written to {output}')


    #override
    @classmethod
    def run(cls):
        args = cls.create_parser().parse_args()
        if args.evaluate or args.process:
            cls.process_cli_args(args)
            return True
        else:
            return False





def associate_predictions_to_annotations(predictionfiles:list, annotationfiles:list) -> tuple:
    annotation_pngs = [a for a in annotationfiles if a.endswith('.png')]
    prediction_pngs = [p for p in predictionfiles if p.endswith('.png')]
    prediction_zips = [p for p in predictionfiles if p.endswith('.zip')]
    for zipf in prediction_zips:
        with zipfile.ZipFile(zipf) as archive:
            for name in archive.namelist():
                prediction_pngs.append(name)

    conflicts = []
    pairs     = []
    for p in prediction_pngs:
        p_basename = no_ext_file_basename(p)
        candidates = [a for a in annotation_pngs if no_ext_file_basename(a) == p_basename]
        if len(candidates) == 1:
            pairs.append( (p, candidates[0]) )
        elif len(candidates) > 1:
            conflicts.append(p)

    if len(conflicts):
        print('[ERROR] Found multiple annotation files for:')
        print('\n'.join(conflicts))
    
    #extract zipped & matched predictions
    for zipf in prediction_zips:
        with zipfile.ZipFile(zipf) as archive:
            archive_namelist = archive.namelist()
            for i, (pred,ann) in enumerate(pairs):
                if pred in archive_namelist:
                    destination = os.path.join(get_cache_path(), os.path.basename(pred))
                    open(destination, 'wb').write( archive.open(pred).read() )
                    pairs[i] = (destination, ann)
    
    return pairs

def no_ext_file_basename(filename:str) -> str:
    filename = os.path.basename(filename)
    for ending in ['.segmentation.png', '.png', '.tiff', '.tif']:
        filename = (filename+'\n').replace(ending+'\n', '').replace('\n','')
    return filename

