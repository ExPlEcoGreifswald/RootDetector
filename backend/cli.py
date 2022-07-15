import base.backend.cli as base_cli

import os, argparse, glob, pathlib, zipfile, sys
import backend.settings
import backend.training
import backend.evaluation
import backend.root_detection
from base.backend.app import get_cache_path, setup_cache


class CLI(base_cli.CLI):

    #override
    @classmethod
    def create_parser(cls):
        parser = super().create_parser(
            description    = 'DigIT! RootDetector',
            default_output = 'output.zip',
        )
        parser.add_argument('--exclusionmask_model', type=pathlib.Path,
                            help='Path to model file (default: last used)')

        group = parser.add_mutually_exclusive_group(required=False)
        group.add_argument('--process',  action='store_true',
                           help='Perform root detection on input files')
        group.add_argument('--evaluate', action='store_true',
                           help='Perform evaluation of processed results')
        group.add_argument('--training', action='store_true',
                           help='Retrain a root detection model')

        group = parser.add_mutually_exclusive_group(required=False)
        #group.add_argument('--exclusionmask', action='store_true')
        group.add_argument('--no-exclusionmask', action='store_true',
                           help='Process without exclusion mask. (With by default)')

        parser.add_argument('--annotations', default=None, type=pathlib.Path,
                            help=f'Path to annotation files (e.g. --annotations=path/to/*.png)')
        parser.add_argument('--predictions', default=None, type=pathlib.Path,
                            help=f'Path to result files (e.g. --predictions=path/to/results.zip)')
        #TODO?: --cuda
        #parser.add_argument('--cpu', action='store_true',
        #                    help='Process on the CPU. (Default : use GPU if available)')

        parser.add_argument('--lr', type=float, default=1e-4, 
                            help='Learning rate during training (Default: 1e-4)')
        parser.add_argument('--epochs', type=int, default=10, 
                            help='Number of epochs during training (Default: 10)')
        return parser

    #override
    @classmethod
    def process_cli_args(cls, args):
        if args.evaluate:
            return cls.evaluate(args)
        elif args.process:
            return cls.process(args)
        elif args.training:
            return cls.training(args)
        else:
            raise NotImplementedError()
        return True

    @staticmethod
    def evaluate(args):
        if args.annotations is None or args.predictions is None:
            print('[ERROR] Please specify --annotations and --predictions')
            return 1
        
        setup_cache(get_cache_path())
        annotationfiles = sorted(glob.glob(args.annotations.as_posix(), recursive=True))
        predictionfiles = sorted(glob.glob(args.predictions.as_posix(), recursive=True))
        file_pairs = associate_predictions_to_annotations(predictionfiles, annotationfiles)
        if len(file_pairs) == 0:
            print('Could not find any matching files')
            return
        
        print(f'Found {len(file_pairs)} result files and annotations.')
        evresults = [backend.evaluation.evaluate_single_file(*pair) for pair in file_pairs]
        output    = reformat_outputfilename(args.output.as_posix())
        backend.evaluation.save_evaluation_results(evresults, output)
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

        settings = backend.settings.Settings()
        setup_cache(get_cache_path())

        if args.model:
            #TODO: code duplication
            modelpath = args.model.as_posix()
            if not os.path.exists(modelpath):
                print(f'[ERROR] File "{modelpath}" does not exist')
                return 1
            model = settings.load_modelfile(modelpath)
            settings.models['detection'] = model
        if args.exclusionmask_model:
            #TODO: code duplication
            modelpath = args.exclusionmask_model.as_posix()
            if not os.path.exists(modelpath):
                print(f'[ERROR] File "{modelpath}" does not exist')
                return 1
            model = settings.load_modelfile(modelpath)
            settings.models['exclusion_mask'] = model

        settings.exmask_enabled = not args.no_exclusionmask

        print(f'Processing {len(inputfiles)} files')
        results = []
        for i,f in enumerate(inputfiles):
            print(f'[{i:4d} / {len(inputfiles)}] {f}')
            try:
                result       = backend.root_detection.process_image(f, settings)
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
        all_stats   = []
        csv_header = [
            'Filename', '# root pixels', '# background pixels', '# mask pixels', '# skeleton pixels', 
            '# skeleton pixels (<3px width)', '# skeleton pixels (3-7px width)', '# skeleton pixels (>7px width)',
            'Kimura length'
        ]

        with zipfile.ZipFile(outputfile, 'w') as archive:
            all_csv_data = []
            for r in results:
                filename = os.path.basename(r['filename'])
                r        = r['result']
                png_seg  = open(get_cache_path(r['segmentation']), 'rb').read()
                png_skel = open(get_cache_path(r['skeleton']), 'rb').read()
                archive.open(f'{filename}/{filename}.segmentation.png', 'w').write(png_seg)
                archive.open(f'{filename}/{filename}.skeleton.png', 'w').write(png_skel)
                all_stats.append(r['statistics'])

                keys = ['sum', 'sum_negative', 'sum_mask', 'sum_skeleton']
                csv_data = (
                      [filename] 
                    + [r['statistics'][k] for k in keys]
                    +  r['statistics']['widths'] 
                    + [r['statistics']['kimura_length']] 
                )
                assert len(csv_data) == len(csv_header), [len(csv_data) , len(csv_header)]
                all_csv_data += [[str(x) for x in csv_data]]
            csv_text = '\n'.join([', '.join(line) for line in [csv_header]+all_csv_data])
            archive.writestr('statistics.csv', csv_text)
        print(f'Results written to {outputfile}.')
    
    @staticmethod
    def training(args):
        if args.annotations is None or args.input is None:
            print('[ERROR] Please specify --annotations and --input')
            return 1
        
        setup_cache(get_cache_path())
        annotationfiles = sorted(glob.glob(args.annotations.as_posix(), recursive=True))
        inputfiles      = sorted(glob.glob(args.input.as_posix(), recursive=True))
        file_pairs      = associate_inputs_to_annotations(inputfiles, annotationfiles)
        inputfiles      = [f0 for f0,f1 in file_pairs]
        annotationfiles = [f1 for f0,f1 in file_pairs]
        if len(file_pairs) == 0:
            print('Could not find any matching files')
            return 1
        
        settings = backend.settings.Settings()
        setup_cache(get_cache_path())

        if args.model and args.exclusionmask_model:
            #both specified
            print('[ERROR] Please specify either --model or --exclusionmask_model')
            return 1
        elif args.model:
            modelpath = args.model.as_posix()
            modeltype = 'detection'
        elif args.exclusionmask_model:
            modelpath = args.exclusionmask_model.as_posix()
            modeltype = 'exclusion_mask'
        else:
            #none specified
            print('[ERROR] Please specify either --model or --exclusionmask_model')
            return 1
        
        if not os.path.exists(modelpath):
            print(f'[ERROR] File "{modelpath}" does not exist')
            return 1
        
        model = settings.load_modelfile(modelpath)
        settings.models[modeltype] = model

        print(f'Found {len(file_pairs)} input files and annotations.')
        options = {
            'training_type': modeltype,
            'epochs'       : args.epochs,
            'lr'           : args.lr,
        }
        cb = lambda x: print(f'Training progress: {x*100:.1f}%        ', end='\r')
        backend.training.start_training(inputfiles, annotationfiles, options, settings, callback=cb)

        output = args.output.as_posix()
        model.save(output)
        print(f'Output written to {output}')



    #override #TODO: unify
    @classmethod
    def run(cls):
        args = cls.create_parser().parse_args()
        if args.evaluate or args.process or args.training:
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


def associate_predictions_to_annotations(predictionfiles:list, annotationfiles:list) -> list:
    annotation_pngs = [a for a in annotationfiles if a.endswith('.png')]
    prediction_pngs = [p for p in predictionfiles if p.endswith('.png')]
    prediction_zips = [p for p in predictionfiles if p.endswith('.zip')]
    for zipf in prediction_zips:
        with zipfile.ZipFile(zipf) as archive:
            for name in archive.namelist():
                prediction_pngs.append(name)

    pairs = associate_files_to_annotations(prediction_pngs, annotationfiles)
    
    #extract zipped & matched predictions
    for zipf in prediction_zips:
        with zipfile.ZipFile(zipf) as archive:
            archive_namelist = archive.namelist()
            for i, (pred,ann) in enumerate(pairs):
                if pred in archive_namelist:
                    destination = get_cache_path(os.path.basename(pred))
                    open(destination, 'wb').write( archive.open(pred).read() )
                    pairs[i] = (destination, ann)
    
    return pairs

def associate_inputs_to_annotations(inputfiles:list, annotationfiles:list) -> list:
    annotationfiles = [a for a in annotationfiles if a.endswith('.png')]
    inputfiles      = [f for f in inputfiles      if os.path.splitext(f)[1].lower() in ['.tiff', '.tif', '.jpg', '.jpeg']]

    pairs = associate_files_to_annotations(inputfiles, annotationfiles)
    return pairs

def associate_files_to_annotations(files:list, annotationfiles:list) -> list:
    conflicts = []
    pairs     = []
    for f in files:
        f_basename = no_ext_file_basename(f)
        candidates = [a for a in annotationfiles if no_ext_file_basename(a) == f_basename]
        if len(candidates) == 1:
            pairs.append( (f, candidates[0]) )
        elif len(candidates) > 1:
            conflicts.append(f)
    
    if len(conflicts):
        print('[ERROR] Found multiple annotation files for:')
        print('\n'.join(conflicts))
    
    return pairs


def no_ext_file_basename(filename:str) -> str:
    filename = os.path.basename(filename)
    for ending in ['.segmentation.png', '.png', '.tiff', '.tif', '.jpg', '.jpeg']:
        filename = (filename+'\n').replace(ending+'\n', '').replace(ending.upper()+'\n', '').replace('\n','')
    return filename

