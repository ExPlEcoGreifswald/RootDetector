import sys


def packaged_startup_error(exc):
    diagnostic_hint = ''
    try:
        from backend import diagnostics
        from backend import jobs
        diagnostic_id = jobs.new_diagnostic_id()
        diagnostics.log_exception(diagnostic_id, 'startup', 'application', exc)
        diagnostic_hint = ' Diagnostic ID: {}. See logs\\rootdetector.log.'.format(
            diagnostic_id
        )
    except Exception:
        pass
    print('[ERROR] RootDetector could not start: {}{}'.format(exc, diagnostic_hint))
    print(
        'The first launch requires internet access to download the PyTorch runtime '
        'and pretrained models. Check the connection, proxy, firewall, and available '
        'disk space, then run StartRootDetector.bat again.'
    )


try:
    from backend.app import App
    from backend.cli import CLI
except Exception as exc:
    if __name__ == '__main__' and getattr(sys, 'frozen', False):
        packaged_startup_error(exc)
        sys.exit(1)
    raise


if __name__ == '__main__':
    try:
        exit_code = CLI.run()
        if exit_code is None:
            # Start the desktop browser application when no CLI operation was requested.
            print('Starting UI')
            App().run()
    except Exception as exc:
        if getattr(sys, 'frozen', False):
            packaged_startup_error(exc)
            sys.exit(1)
        raise
    raise SystemExit(exit_code)
