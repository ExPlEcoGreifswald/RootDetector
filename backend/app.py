from base.backend.app import App as BaseApp
from base.backend.app import parser as base_parser
from base.backend.paths import get_models_path

import hmac
import os
import secrets
import shutil
import signal
import tempfile
import urllib.parse
import flask
from werkzeug.exceptions import HTTPException

import backend
import backend.jobs
import backend.training
import backend.training_jobs
import backend.pipeline
import backend.security
import backend.settings
import backend.diagnostics
from . import root_detection
from . import root_tracking



class App(BaseApp):
    def __init__(self, *args, **kw):
        self.session_token = secrets.token_urlsafe(32)
        self.max_upload_bytes = backend.security.configured_max_upload_bytes()
        backend.diagnostics.configure_logging()
        # Packaged Windows releases contain the manifest but fetch the large
        # verified model files on first launch. Source/Docker users can prefetch
        # them explicitly to make startup deterministic.
        backend.settings.ensure_pretrained_models()
        
        super().__init__(*args, **kw)
        if self.is_reloader:
            return

        self.config.update(
            MAX_CONTENT_LENGTH=self.max_upload_bytes + backend.security.UPLOAD_FORM_OVERHEAD_BYTES,
            MAX_FORM_MEMORY_SIZE=1024 * 1024,
            MAX_FORM_PARTS=backend.security.MAX_UPLOAD_FILES,
        )
        self.pipeline_manager = backend.pipeline.PipelineManager(
            self.settings,
            cache_path=self.cache_path,
        )
        self.training_results = {}
        self.training_manager = backend.training_jobs.TrainingManager(
            self.settings,
            result_sink=self.training_results,
        )

        self.view_functions['file_upload'] = self.file_upload
        self.view_functions['images'] = self.images
        self.view_functions['get_set_settings'] = self.get_set_settings
        self.route('/api/session', methods=['GET'])(self.get_session)
        self.route('/api/diagnostics', methods=['GET'])(self.download_diagnostics)
        self.route('/api/diagnostics/client', methods=['POST'])(self.record_client_diagnostic)
        self.route('/process_root_tracking', methods=['POST'])(self.process_root_tracking)
        self.route('/postprocess_detection/<filename>', methods=['POST'])(self.postprocess_detection)
        self.route('/compile_tracking_results', methods=['POST'])(self.compile_tracking_results)
        self.route('/api/pipeline/runs', methods=['POST'])(self.create_pipeline_run)
        self.route('/api/pipeline/runs/<run_id>', methods=['GET'])(self.get_pipeline_run)
        self.route('/api/pipeline/runs/<run_id>/cancel', methods=['POST'])(self.cancel_pipeline_run)
        self.route('/api/pipeline/runs/<run_id>/retry', methods=['POST'])(self.retry_pipeline_run)
        self.route('/api/training/runs', methods=['POST'])(self.create_training_run)
        self.route('/api/training/runs/<run_id>', methods=['GET'])(self.get_training_run)
        self.route('/api/training/runs/<run_id>/cancel', methods=['POST'])(self.cancel_training_run)
        self.add_url_rule('/delete_image/<path:path>', 'secure_delete_image', self.delete_image, methods=['DELETE'])
        self.add_url_rule('/shutdown', 'secure_shutdown', self.shutdown, methods=['POST'])
        self.add_url_rule('/clear_cache', 'secure_clear_cache', self.clear_cache, methods=['POST'])
        self.add_url_rule('/process_image/<imagename>', 'secure_process_image', self.process_image, methods=['POST'])
        self.add_url_rule('/save_model', 'secure_save_model', self.save_model, methods=['POST'])
        self.add_url_rule('/stop_training', 'secure_stop_training', self.stop_training, methods=['POST'])
        self.before_request(self.protect_local_request)
        self.after_request(self.add_security_headers)
        self.register_error_handler(backend.security.ValidationError, self.handle_validation_error)
        self.register_error_handler(413, self.handle_request_too_large)
        self.register_error_handler(Exception, self.handle_unexpected_error)

    @staticmethod
    def json_error(code, message, status, retryable=False, stage='api'):
        return flask.jsonify(backend.jobs.error_payload(
            code,
            message,
            stage,
            retryable=retryable,
        )), status

    @staticmethod
    def _origin_identity(url):
        parsed = urllib.parse.urlsplit(url)
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or '').lower()
        port = parsed.port
        if port is None:
            port = 443 if scheme == 'https' else 80
        return scheme, hostname, port

    def protect_local_request(self):
        request_host = urllib.parse.urlsplit(flask.request.host_url).hostname
        if request_host not in {'localhost', '127.0.0.1', '::1'}:
            return self.json_error('invalid_host', 'RootDetector only accepts loopback requests.', 403)

        origin = flask.request.headers.get('Origin')
        if origin and self._origin_identity(origin) != self._origin_identity(flask.request.host_url):
            return self.json_error('invalid_origin', 'Cross-origin requests are not allowed.', 403)

        legacy_get_endpoints = {
            'clear_cache',
            'delete_image',
            'process_image',
            'save_model',
            'shutdown',
            'stop_training',
        }
        if flask.request.method == 'GET' and flask.request.endpoint in legacy_get_endpoints:
            return self.json_error(
                'method_not_allowed',
                'This operation requires an explicit state-changing request.',
                405,
            )

        if flask.request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            supplied_token = flask.request.headers.get('X-RootDetector-Token', '')
            if not hmac.compare_digest(supplied_token, self.session_token):
                return self.json_error(
                    'invalid_session_token',
                    'The local session token is missing or invalid. Reload RootDetector and try again.',
                    403,
                )
        return None

    def add_security_headers(self, response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self' data: blob:; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
        return response

    def handle_validation_error(self, error):
        return self.json_error(error.code, str(error), error.status)

    def handle_request_too_large(self, _error):
        return self.json_error(
            'upload_too_large',
            'The request exceeds RootDetector\'s {} file limit plus multipart overhead.'.format(
                backend.security.upload_limit_label(self.max_upload_bytes)
            ),
            413,
        )

    def handle_unexpected_error(self, error):
        if isinstance(error, HTTPException):
            return error
        payload = backend.jobs.error_payload(
            'internal_error',
            'RootDetector encountered an unexpected error. Download diagnostics and retry.',
            'api',
            item_id=flask.request.path,
            retryable=True,
            error_type=error.__class__.__name__,
        )
        backend.diagnostics.log_exception(
            payload['diagnostic_id'],
            'api',
            flask.request.path,
            error,
            self.settings,
        )
        return flask.jsonify(payload), 500

    def get_session(self):
        return flask.jsonify({
            'token': self.session_token,
            'asset_schema': backend.security.ASSET_SCHEMA_VERSION,
            'limits': {
                'max_upload_bytes': self.max_upload_bytes,
                'max_upload_files': backend.security.MAX_UPLOAD_FILES,
                'max_image_pixels': backend.security.MAX_IMAGE_PIXELS,
            },
        })

    def download_diagnostics(self):
        archive = backend.diagnostics.build_diagnostics_archive(self.settings)
        return flask.send_file(
            archive,
            mimetype='application/zip',
            as_attachment=True,
            download_name='RootDetector-diagnostics.zip',
        )

    def record_client_diagnostic(self):
        data = flask.request.get_json(silent=True)
        if not isinstance(data, dict):
            raise backend.security.ValidationError(
                'Client diagnostics must be a JSON object.',
                'invalid_client_diagnostic',
            )

        def clean_field(name, limit, required=False):
            value = data.get(name, '')
            if not isinstance(value, str) or (required and not value.strip()):
                raise backend.security.ValidationError(
                    '{} must be text.'.format(name),
                    'invalid_client_diagnostic',
                )
            return ' '.join(value.split())[:limit]

        stage = clean_field('stage', 64, required=True)
        item_id = clean_field('item_id', 300)
        message = clean_field('message', 2000, required=True)
        error_type = clean_field('error_type', 100)
        status = data.get('status')
        if status is not None and (
            isinstance(status, bool) or not isinstance(status, (int, float))
        ):
            raise backend.security.ValidationError(
                'status must be numeric.',
                'invalid_client_diagnostic',
            )

        diagnostic_id = backend.jobs.new_diagnostic_id()
        backend.diagnostics.logger().warning(
            '[%s] Browser %s failed for %s: %s type=%s status=%s.',
            diagnostic_id,
            stage,
            item_id or '-',
            message,
            error_type or '-',
            status if status is not None else '-',
        )
        return flask.jsonify({'diagnostic_id': diagnostic_id}), 202

    def file_upload(self):
        files = flask.request.files.getlist('files')
        if not files:
            raise backend.security.ValidationError('No files were provided.', 'missing_upload')
        if len(files) > backend.security.MAX_UPLOAD_FILES:
            raise backend.security.ValidationError(
                'Upload at most {} files per request.'.format(backend.security.MAX_UPLOAD_FILES),
                'too_many_uploads',
                413,
            )

        pending = []
        temporary_paths = []
        names = set()
        try:
            for storage in files:
                name = backend.security.validate_filename(
                    storage.filename,
                    backend.security.SUPPORTED_IMAGE_EXTENSIONS,
                )
                if name in names:
                    raise backend.security.ValidationError(
                        'Duplicate filename in upload request: {}'.format(name),
                        'duplicate_filename',
                        409,
                    )
                names.add(name)
                destination = backend.security.safe_resolve(
                    self.cache_path,
                    name,
                    backend.security.SUPPORTED_IMAGE_EXTENSIONS,
                )
                handle, temporary = tempfile.mkstemp(prefix='.upload-', dir=self.cache_path)
                os.close(handle)
                temporary_paths.append(temporary)
                storage.save(temporary)
                metadata = backend.security.validate_image_file(
                    temporary,
                    max_upload_bytes=self.max_upload_bytes,
                )
                if os.path.exists(destination) and not backend.security.files_are_identical(temporary, destination):
                    raise backend.security.ValidationError(
                        'A different file named {} is already loaded. Clear the current project or rename the file.'.format(name),
                        'filename_conflict',
                        409,
                    )
                pending.append((name, temporary, destination, metadata))

            uploaded = []
            for name, temporary, destination, metadata in pending:
                reused = os.path.exists(destination)
                if reused:
                    os.remove(temporary)
                else:
                    os.replace(temporary, destination)
                uploaded.append(dict(metadata, name=name, reused=reused))
                backend.diagnostics.logger().info(
                    'Upload accepted: name=%s size=%s reused=%s.',
                    name,
                    metadata.get('bytes'),
                    reused,
                )
            return flask.jsonify({'files': uploaded})
        finally:
            for _name, temporary, _destination, _metadata in pending:
                if os.path.exists(temporary):
                    os.remove(temporary)
            for temporary in temporary_paths:
                if os.path.isfile(temporary):
                    os.remove(temporary)

    def images(self, path):
        full_path = backend.security.safe_resolve(
            self.cache_path,
            path,
            must_exist=True,
        )
        return flask.send_file(full_path)

    def get_set_settings(self):
        if flask.request.method == 'GET':
            return flask.jsonify(self.settings.get_settings_as_dict())

        request_data = flask.request.get_json(force=True) or {}
        if not isinstance(request_data, dict):
            raise backend.security.ValidationError('Settings must be a JSON object.', 'invalid_settings')
        allowed_settings = {
            'active_models',
            'exmask_enabled',
            'use_gpu',
            'too_many_roots',
        }
        unknown_settings = set(request_data) - allowed_settings
        if unknown_settings:
            raise backend.security.ValidationError(
                'Unknown setting(s): {}.'.format(', '.join(sorted(unknown_settings))),
                'invalid_settings',
            )
        active_models = request_data.get('active_models', {})
        if not isinstance(active_models, dict):
            raise backend.security.ValidationError(
                'The active_models setting must be an object.',
                'invalid_settings',
            )
        settings_data = self.settings.get_settings_as_dict()
        current_settings = settings_data.get('settings', {})
        defaults = self.settings.get_defaults() if hasattr(self.settings, 'get_defaults') else {}
        default_models = defaults.get('active_models', {})
        available_models = settings_data.get('available_models', {})
        known_model_types = set(default_models) | set(available_models)
        if not known_model_types:
            # Keep lightweight/test settings implementations usable too.
            known_model_types = set(getattr(self.settings, 'active_models', {}))
        for modeltype, modelname in active_models.items():
            if modeltype not in known_model_types:
                raise backend.security.ValidationError('Invalid model type.', 'invalid_model_type')
            backend.security.validate_filename(modeltype)
            if modelname != '':
                backend.security.validate_filename(modelname)

        for boolean_name in ['exmask_enabled', 'use_gpu']:
            if boolean_name in request_data and not isinstance(request_data[boolean_name], bool):
                raise backend.security.ValidationError(
                    '{} must be true or false.'.format(boolean_name),
                    'invalid_settings',
                )
        if 'too_many_roots' in request_data:
            threshold = request_data['too_many_roots']
            if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 1:
                raise backend.security.ValidationError(
                    'too_many_roots must be a positive whole number.',
                    'invalid_settings',
                )

        # BaseSettings persists the supplied dictionary as the entire settings
        # file. A partial request must therefore be expanded before saving;
        # otherwise one model selection silently discards the other types.
        updated_settings = dict(defaults)
        updated_settings.update(current_settings)
        merged_models = dict(default_models)
        merged_models.update(current_settings.get('active_models', {}))
        merged_models.update(active_models)
        updated_settings.update(request_data)
        updated_settings['active_models'] = merged_models
        self.settings.set_settings(updated_settings)
        return flask.jsonify({'saved': True})

    def delete_image(self, path):
        full_path = backend.security.safe_resolve(self.cache_path, path)
        if os.path.isfile(full_path):
            os.remove(full_path)
        return flask.jsonify({'deleted': os.path.basename(full_path)})

    def clear_cache(self):
        if any(
            run.state not in backend.pipeline.TERMINAL_RUN_STATES
            for run in self.pipeline_manager.runs.values()
        ):
            return self.json_error(
                'pipeline_busy',
                'The cache cannot be cleared while analysis is running.',
                409,
            )
        if self.training_manager.active_run() is not None:
            return self.json_error(
                'training_busy',
                'The cache cannot be cleared while training is running.',
                409,
                retryable=True,
            )
        shutil.rmtree(self.cache_path, ignore_errors=True)
        os.makedirs(self.cache_path)
        return flask.jsonify({'cleared': True})

    def shutdown(self):
        os.kill(os.getpid(), signal.SIGINT)
        return flask.jsonify({'shutdown': True})

    def process_image(self, imagename):
        full_path = backend.security.safe_resolve(
            self.cache_path,
            imagename,
            backend.security.SUPPORTED_IMAGE_EXTENSIONS,
            must_exist=True,
        )
        result = root_detection.process_image(full_path, self.settings)
        return flask.jsonify(result)

    def postprocess_detection(self, filename):
        #FIXME: code duplication
        full_path = backend.security.safe_resolve(
            self.cache_path,
            filename,
            {'.png'},
            must_exist=True,
        )
        
        result = root_detection.postprocess_segmentation_file(full_path)
        result['segmentation'] = os.path.basename(result['segmentation'])
        result['skeleton']     = os.path.basename(result['skeleton'])
        return flask.jsonify(result)
    

    def process_root_tracking(self):
        data = flask.request.get_json(force=True) or {}
        fname0 = backend.security.safe_resolve(
            self.cache_path,
            data.get('filename0'),
            backend.security.SUPPORTED_IMAGE_EXTENSIONS,
            must_exist=True,
        )
        fname1 = backend.security.safe_resolve(
            self.cache_path,
            data.get('filename1'),
            backend.security.SUPPORTED_IMAGE_EXTENSIONS,
            must_exist=True,
        )
        previous_data = data if 'points0' in data else None
        result = root_tracking.process(fname0, fname1, self.settings, previous_data)
        
        if isinstance(result, root_tracking.TooManyRootsError):
            return flask.jsonify({
                'success': 'TOO_MANY_ROOTS',
                'state': 'skipped',
                'code': 'too_many_roots',
                'message': 'Tracking was skipped because the configured root threshold was exceeded.',
            })
        
        return flask.jsonify({
            'points0':         result['points0'].tolist(),
            'points1':         result['points1'].tolist(),
            'growthmap'     :  os.path.basename(result['growthmap']),
            'growthmap_rgba':  os.path.basename(result['growthmap_rgba']),
            'segmentation0' :  os.path.basename(result['segmentation0']),
            'segmentation1' :  os.path.basename(result['segmentation1']),
            'success'       :  result['success'],
            'n_matched_points'   : result['n_matched_points'],
            'tracking_model'     : result['tracking_model'],
            'segmentation_model' : result['segmentation_model'],
            'tracking_matcher'     : result['tracking_matcher'],
            'exclusion_mask_policy': result['exclusion_mask_policy'],
            'exclusion_masks'      : result['exclusion_masks'],
            'statistics'         : result['statistics'],
        })
    
    def compile_tracking_results(self):
        file_pairs = flask.request.get_json(force=True)['file_pairs']
        for pair in file_pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise backend.security.ValidationError('Invalid tracking pair.', 'invalid_tracking_pair')
            for filename in pair:
                backend.security.safe_resolve(
                    self.cache_path,
                    filename,
                    backend.security.SUPPORTED_IMAGE_EXTENSIONS,
                    must_exist=True,
                )
        return root_tracking.compile_results_into_zip(file_pairs)

    def create_pipeline_run(self):
        request_data = flask.request.get_json(force=True) or {}
        if self.training_manager.active_run() is not None:
            return self.json_error(
                'training_busy',
                'Analysis cannot start while training is running.',
                409,
                retryable=True,
            )
        try:
            run = self.pipeline_manager.create(
                request_data.get('filenames', []),
                request_data.get('file_pairs', []),
            )
        except ValueError as exc:
            return self.json_error('invalid_pipeline_request', str(exc), 400)
        except RuntimeError as exc:
            return self.json_error('pipeline_busy', str(exc), 409, retryable=True)
        return flask.jsonify(run.snapshot()), 202

    def get_pipeline_run(self, run_id):
        try:
            return flask.jsonify(self.pipeline_manager.get(run_id).snapshot())
        except KeyError as exc:
            return self.json_error('pipeline_not_found', str(exc), 404)

    def cancel_pipeline_run(self, run_id):
        try:
            run = self.pipeline_manager.get(run_id)
        except KeyError as exc:
            return self.json_error('pipeline_not_found', str(exc), 404)
        run.request_cancel()
        return flask.jsonify(run.snapshot()), 202

    def retry_pipeline_run(self, run_id):
        try:
            run = self.pipeline_manager.get(run_id)
            run.retry_failed()
        except KeyError as exc:
            return self.json_error('pipeline_not_found', str(exc), 404)
        except RuntimeError as exc:
            return self.json_error('pipeline_not_retryable', str(exc), 409)
        return flask.jsonify(run.snapshot()), 202

    def _prepare_training_request(self):
        requestform = flask.request.get_json(force=True) or {}
        if not isinstance(requestform, dict):
            raise backend.security.ValidationError(
                'Training request must be an object.',
                'invalid_training_request',
            )
        try:
            options = backend.training.parse_training_options(requestform.get('options'))
        except backend.training.TrainingValidationError as exc:
            raise backend.security.ValidationError(str(exc), 'invalid_training_options')

        filenames = requestform.get('filenames')
        if not isinstance(filenames, list) or not filenames:
            raise backend.security.ValidationError(
                'Select at least one image with a matching annotation.',
                'invalid_training_files',
            )

        label_review = requestform.get('label_review')
        if not isinstance(label_review, dict) or (
            label_review.get('source') != 'user_reviewed'
            or label_review.get('confirmed') is not True
        ):
            raise backend.security.ValidationError(
                'Training requires explicit confirmation that every label was independently reviewed; generated detection results are not ground truth.',
                'unreviewed_training_labels',
            )

        imagefiles = [
            backend.security.safe_resolve(
                self.cache_path,
                filename,
                backend.security.SUPPORTED_IMAGE_EXTENSIONS,
                must_exist=True,
            )
            for filename in filenames
        ]
        label_filenames = requestform.get('label_filenames')
        if label_filenames is None:
            # Older clients use a conventional annotation filename. They must
            # still explicitly confirm review before training can start.
            targetfiles = backend.training.find_targetfiles(imagefiles)
        elif isinstance(label_filenames, list) and len(label_filenames) == len(imagefiles):
            targetfiles = [
                backend.security.safe_resolve(
                    self.cache_path,
                    label_name,
                    {'.png'},
                    must_exist=True,
                )
                for label_name in label_filenames
            ]
        else:
            raise backend.security.ValidationError(
                'Provide one training label filename for each image.',
                'invalid_training_labels',
            )
        if not all(targetfiles):
            raise backend.security.ValidationError(
                'Every training image must have a matching segmentation annotation.',
                'missing_training_annotations',
            )
        validated_targets = [target for target in targetfiles if target is not None]
        return imagefiles, validated_targets, options

    def _start_training_run(self):
        if any(
            run.state not in backend.pipeline.TERMINAL_RUN_STATES
            for run in self.pipeline_manager.runs.values()
        ):
            raise RuntimeError('Training cannot start while analysis is running.')
        imagefiles, targetfiles, options = self._prepare_training_request()
        return self.training_manager.create(imagefiles, targetfiles, options)

    def create_training_run(self):
        try:
            run = self._start_training_run()
        except RuntimeError as exc:
            return self.json_error('training_busy', str(exc), 409, retryable=True)
        return flask.jsonify(run.snapshot()), 202

    def get_training_run(self, run_id):
        try:
            run = self.training_manager.get(run_id)
        except KeyError as exc:
            return self.json_error('training_not_found', str(exc), 404)
        return flask.jsonify(run.snapshot())

    def cancel_training_run(self, run_id):
        try:
            run = self.training_manager.get(run_id)
        except KeyError as exc:
            return self.json_error('training_not_found', str(exc), 404)
        run.request_cancel()
        return flask.jsonify(run.snapshot()), 202

    # Legacy blocking endpoint retained for existing packaged clients. It uses
    # the same job manager and includes the run ID in its response.
    def training(self):
        try:
            run = self._start_training_run()
        except RuntimeError as exc:
            return self.json_error('training_busy', str(exc), 409, retryable=True)
        run.wait()
        snapshot = run.snapshot()
        # Preserve the compact response fields expected by released packaged
        # clients while exposing the asynchronous run metadata as well.
        training_result = snapshot.get('result') or {}
        snapshot['training_result'] = training_result
        snapshot['result'] = 'OK' if snapshot['state'] == 'completed' else snapshot['state'].upper()
        snapshot['message'] = training_result.get('message', '')
        snapshot['effective_options'] = dict(run.options)
        return flask.jsonify(snapshot), 500 if snapshot['state'] == 'failed' else 200

    def save_model(self):
        request_data = flask.request.get_json(force=True) or {}
        newname = backend.security.validate_filename(request_data.get('newname'))
        options = request_data.get('options') or {}
        modeltype = options.get('training_type', 'detection')
        if modeltype not in {'detection', 'exclusion_mask'} or modeltype not in self.settings.models:
            raise backend.security.ValidationError('Invalid model type.', 'invalid_model_type')
        result = self.training_results.get(modeltype)
        if result is None or not result.completed:
            return self.json_error(
                'training_not_completed',
                'Only a successfully completed training run can be saved.',
                409,
            )
        model_folder = os.path.join(get_models_path(), modeltype)
        os.makedirs(model_folder, exist_ok=True)
        path = backend.security.safe_resolve(model_folder, newname)
        self.settings.models[modeltype].save(path)
        self.settings.active_models[modeltype] = newname
        return flask.jsonify({'saved': newname, 'model_type': modeltype})

    def stop_training(self):
        run = self.training_manager.active_run()
        if run is None:
            backend.training.request_stop(self.settings)
            return flask.jsonify({'stop_requested': False, 'state': 'idle'})
        run.request_cancel()
        return flask.jsonify(run.snapshot()), 202

    def run(self, parse_args=True, **args):
        if parse_args:
            parsed = base_parser.parse_args()
            args = dict(host=parsed.host, port=parsed.port, debug=parsed.debug)
        host = args.get('host', 'localhost')
        container_bind_allowed = os.environ.get('ROOTDETECTOR_ALLOW_CONTAINER_BIND') == '1'
        if host not in {'localhost', '127.0.0.1', '::1'} and not (
            container_bind_allowed and host in {'0.0.0.0', '::'}
        ):
            raise RuntimeError('RootDetector must bind to a loopback address.')
        return super().run(parse_args=False, **args)
    
