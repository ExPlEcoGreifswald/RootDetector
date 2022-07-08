import base.backend.cli as base_cli

import os, argparse, glob, pathlib, zipfile, sys
import backend.settings
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

        group = parser.add_mutually_exclusive_group(required=False)
        group.add_argument('--exclusionmask', action='store_true')
        group.add_argument('--no-exclusionmask', action='store_false')

        group = parser.add_argument_group('evaluation arguments')
        group.add_argument('--annotations', default=None, type=pathlib.Path,
                            help=f'Path to annotation files (e.g. --annotations=path/to/*.png)')
        group.add_argument('--predictions', default=None, type=pathlib.Path,
                            help=f'Path to result files (e.g. --predictions=path/to/results.zip)')
        return parser

    #override
    @classmethod
    def process_cli_args(cls, args):
        if args.evaluate:
            return cls.evaluate(args)
        elif args.process:
            return cls.process(args)
        else:
            raise NotImplementedError()
        return True

    @staticmethod
    def evaluate(args):
        if args.annotations is None or args.predictions is None:
            print('[ERROR] Please specify --annotations and --predictions')
            return 1
        
        annotationfiles = sorted(glob.glob(args.annotations.as_posix(), recursive=True))
        predictionfiles = sorted(glob.glob(args.predictions.as_posix(), recursive=True))
        file_pairs = associate_predictions_to_annotations(predictionfiles, annotationfiles)
        
        print(f'Found {len(file_pairs)} result files and annotations.')
        evresults = [evaluation.evaluate_single_file(*pair) for pair in file_pairs]
        output    = reformat_outputfilename(args.output.as_posix())
        evaluation.save_evaluation_results(evresults, output)
        print(f'Output written to {output}')

    @classmethod
    def process(cls, args):
        if args.input is None:
            print('[ERROR] Please specify --input')
            return 1
        
        #FIXME: code duplication with upstream
        inputfiles = sorted(glob.glob(args.input.as_posix(), recursive=True))
        if len(inputfiles) == 0:
            print('Could not find any files')
            return

        if args.model:
            raise NotImplementedError('TODO')
        if args.exclusionmask or args.no_exclusionmask==False:
            raise NotImplementedError('TODO')

        print(f'Processing {len(inputfiles)} files')
        results = []
        import backend.root_detection
        settings = backend.settings.Settings()
        backend.init(settings)
        for i,f in enumerate(inputfiles):
            print(f'[{i:4d} / {len(inputfiles)}] {f}')
            try:
                result       = backend.root_detection.process_image(f)
            except Exception as e:
                print(f'[ERROR] {e}', file=sys.stderr)
                continue
            results += [{'filename':f, 'result':result}]
        
        if len(results)==0:
            print(f'[ERROR] Unable to process any file', file=sys.stderr)
            return
        
        cls.write_results(results, args)

    @staticmethod
    def write_results(results, args):
        outputfile  = reformat_outputfilename(args.output.as_posix())
        with zipfile.ZipFile(outputfile, 'w') as archive:
            for r in results:
                filename = os.path.basename(r['filename'])
                r        = r['result']
                archive.open(f'{filename}/{filename}.segmentation.png', 'w').write(open(r['segmentation'], 'rb').read())
                archive.open(f'{filename}/{filename}.skeleton.png', 'w').write(open(r['skeleton'], 'rb').read())
        print(f'Results written to {outputfile}.')

    #override
    @classmethod
    def run(cls):
        args = cls.create_parser().parse_args()
        if args.evaluate or args.process:
            cls.process_cli_args(args)
            return True
        else:
            return False


def reformat_outputfilename(filename:str) -> str:
    filename += ('.zip' if not filename.endswith('.zip') else '')
    if os.path.exists(filename):
        split    = os.path.splitext(filename)
        filename = f'{split[0]}(2){split[1]}'
    return filename


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

