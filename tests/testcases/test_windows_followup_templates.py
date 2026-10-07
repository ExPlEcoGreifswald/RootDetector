from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding='utf-8')


def test_file_import_controls_are_fomantic_menu_links_with_disabled_guards():
    template = read('templates/roots/top_menu.html')
    pipeline = read('frontend/roots/pipeline.js')
    app = read('frontend/roots/app.js')
    styles = read('frontend/roots/styles.css')

    for control_id in [
        'load-input-images-button',
        'load-input-folder-button',
        'load-annotations-button',
        'load-exclude-masks-button',
    ]:
        assert 'id="{}"'.format(control_id) in template
    assert template.count('<a href="#" class="ui') >= 6
    assert "if(this.classList.contains('disabled')) return false" in template
    assert 'aria-disabled="true"' in template
    assert "attr('tabindex', run_disabled ? '-1' : '0')" in pipeline
    assert "keydown.rootdetector-menu" in app
    assert 'event.target !== event.currentTarget' in app
    assert 'id="file-import-menu"' in template
    assert 'aria-expanded="false"' in template
    assert "$('#file-import-menu').dropdown({action: 'hide'})" in app
    assert "addClass('keyboard-open')" in app
    assert "focusout.rootdetector-files-menu" in app
    assert "keydown.rootdetector-files-menu" in app
    assert "mouseenter.rootdetector-files-menu mouseleave.rootdetector-files-menu" in app
    assert "find('.menu a.item:not(.disabled)').first().trigger('focus')" in app
    assert '#file-import-menu.keyboard-open > .menu' in styles


def test_narrow_top_menu_keeps_run_analysis_visible():
    styles = read('frontend/roots/styles.css')
    template = read('templates/roots/top_menu.html')

    assert 'class="ui container menu page-wide"' in template
    assert 'id="pipeline-run-button"' in template
    assert '@media (max-width: 480px)' in styles
    assert '.ui.menu.page-wide {' in styles
    assert 'flex-wrap: wrap;' in styles
    assert '.ui.menu.page-wide > #pipeline-run-button {' in styles
    assert 'flex: 1 0 100%;' in styles


def test_settings_actions_are_keyboard_focusable():
    template = read('templates/roots/modals.html')
    styles = read('frontend/roots/styles.css')

    assert 'aria-label="Close settings"' in template
    assert '<button type="button" class="ui negative button"' in template
    assert '<button type="button" class="ui positive right labeled icon button"' in template
    assert '</div>\n    <div class="actions">' in template
    assert '#settings-dialog > .content' in styles
    assert 'max-height: calc(100vh - 11rem)' in styles
    assert 'overflow-y: auto' in styles


def test_training_can_be_closed_or_retried_after_interruption():
    template = read('templates/roots/modals.html')
    training = read('frontend/roots/training.js')
    training_tab = read('templates/roots/training_tab.html')

    assert 'id="retry-training-button"' in template
    assert 'id="close-training-button"' in template
    assert 'Training interrupted. You can retry' in training
    assert "run.state" in training
    assert "Math.min(Number(run.progress) * 100, 99)" in training
    assert "$('#training-new-modelname-field').hide()" in training
    assert '[INTERRUPTED - NOT SAVABLE]' in training
    assert '<button type="button" class="ui violet basic fluid button"' in training_tab
    assert 'for="training-learning-rate"' in training_tab
    assert 'for="training-number-of-epochs"' in training_tab


def test_pipeline_cancel_waits_for_backend_acknowledgement():
    template = read('templates/roots/modals.html')
    pipeline = read('frontend/roots/pipeline.js')

    assert 'class="ui red button" id="pipeline-cancel-button"' in template
    assert 'Cancelling analysis. Waiting for the active operation to stop safely' in pipeline
    assert "run.state == 'cancelling'" in pipeline


def test_large_batch_upload_is_resumable_and_errors_are_readable():
    template = read('templates/roots/modals.html')
    pipeline = read('frontend/roots/pipeline.js')
    file_input = read('frontend/roots/file_input.js')
    security = read('frontend/roots/security.js')
    styles = read('frontend/roots/styles.css')
    scripts = read('templates/roots/scripts.html')

    assert 'id="pipeline-diagnostics-button"' in template
    assert 'RootsFileInput.ensure_uploaded' in pipeline
    assert 'Already uploaded in this session.' in pipeline
    assert 'max_attempts: 3' in pipeline
    assert "status == 0" in file_input
    assert '[object Object]' not in pipeline
    assert 'responseJSON?.message' in security
    assert 'The connection to the local RootDetector process was interrupted.' in security
    assert 'report_client_error' in security
    assert 'overflow-wrap: anywhere' in styles
    assert 'max-width: calc(100vw - 1.75rem)' in styles
    assert 'href="roots/styles.css"' in scripts


def test_root_page_has_mixed_release_recovery_bootstrap():
    template = read('templates/index.html')
    security = read('frontend/roots/security.js')

    assert 'RootDetectorBoot.start()' in template
    assert 'RootDetector could not load its browser files.' in template
    assert 'RootDetector is not reachable.' in template
    assert 'This tab belongs to a different RootDetector version.' in template
    assert 'StartRootDetector.bat' in template
    assert "error?.code == 'asset_schema_mismatch'" in template
    assert "error?.status == 0" in template
    assert 'rootdetector-web-rc2-1' in security


def test_tracking_tab_explains_detection_only_runs():
    template = read('templates/roots/tracking_tab.html')
    pipeline = read('frontend/roots/pipeline.js')
    tracking = read('frontend/roots/tracking.js')

    assert 'No tracking pairs were found' in template
    assert 'same prefix before the date' in template
    assert 'Some observations were not paired' in template
    assert 'Same-day duplicates' in template
    assert 'plan_tracking_pairs(files)' in tracking
    assert "issue.code == 'duplicate_date'" in tracking
    assert 'Starting detection only; no valid tracking pairs were found.' in pipeline


def test_packaged_startup_failures_remain_actionable():
    startup = read('main.py')

    assert 'packaged_startup_error' in startup
    assert 'logs\\\\rootdetector.log' in startup
    assert 'raise SystemExit(exit_code)' in startup
    assert 'StartRootDetector.bat' in startup


def test_windows_workflow_uploads_only_the_full_portable_zip():
    workflow = read('.github/workflows/build.yml')

    assert 'actions/checkout@v5' in workflow
    assert 'actions/setup-python@v6' in workflow
    assert 'actions/upload-artifact@v6' in workflow
    assert 'node tests/testcases_js/test_tracking_utils.js' in workflow
    assert 'path: builds/*_DigIT_RootDetector.zip' in workflow
    assert 'path: builds/*.zip' not in workflow


def test_portable_build_contains_exact_provenance():
    build_script = read('build.py')

    assert "os.environ.get('GITHUB_SHA'" in build_script
    assert "os.environ.get('GITHUB_RUN_ID'" in build_script
    assert "build_dir+'/BUILD-INFO.txt'" in build_script


def test_portable_build_has_one_clearly_named_launcher():
    build_script = read('build.py')
    recovery_template = read('templates/index.html')

    assert "open(build_dir+'/StartRootDetector.bat'" in build_script
    assert "open(build_dir+'/main.bat'" not in build_script
    assert "launchers != {'StartRootDetector.bat'}" in build_script
    assert 'StartRootDetector.bat' in recovery_template


def test_training_help_is_user_facing_and_cli_alias_stays_technical():
    template = read('templates/roots/training_tab.html')
    technical_guide = read('TECHNICAL-GUIDE.md')

    assert '--lr' not in template
    assert '--lr' in technical_guide
