from backend.startup import ensure_torch
#needs to be called before the first 'import torch'
ensure_torch()


from backend.app import App
from backend.cli import CLI

if __name__ == '__main__':
    ok = CLI.run()

    if not ok:
        #start UI
        print('Starting UI')
        App().run()

