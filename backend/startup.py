import sys, os, urllib.request, zipfile
#not importing because imports torch internally #FIXME
#from base.paths import path_to_main_module


WHEEL_URLS = {
    'torch==1.10.1+cpu'     : 'https://download.pytorch.org/whl/cpu/torch-1.10.1%2Bcpu-cp37-cp37m-win_amd64.whl',
    'torch==1.10.1+cu113'   : 'https://download.pytorch.org/whl/cu113/torch-1.10.1%2Bcu113-cp37-cp37m-win_amd64.whl',
}

def download_and_extract_pytorch_libs(destination:str) -> None:
    __TEST_TORCH_VERSION = 'torch==1.10.1+cpu'
    url                  = WHEEL_URLS[__TEST_TORCH_VERSION]
    whl_path             = './cache/torch.whl'

    print(f'Downloading PyTorch from {url} ...')
    with urllib.request.urlopen(url) as f:
        os.makedirs( os.path.dirname(whl_path), exist_ok=True )
        open(whl_path, 'wb').write(f.read())
    
    with zipfile.ZipFile(whl_path) as zipf:
        libs = [n for n in zipf.namelist() if n.startswith('torch/lib')]
        zipf.extractall(path=destination, members=libs)
    os.remove(whl_path)


def ensure_torch() -> None:
    '''Check if PyTorch binaries are present and download if they are not.
       Normally done once on the first start because binaries are not included
       in the zip package to save space.
    '''
    is_debug         = sys.argv[0].endswith('.py')
    if is_debug:
        #only relevant for packaged .exe
        return
    if not 'win32' in sys.platform:
        #only for windows
        return

    #root             = path_to_main_module()
    root             = './'
    path_to_torchlib = os.path.join(root, 'main', 'torch', 'lib')
    if os.path.exists(path_to_torchlib):
        #all ok
        return

    #not ok, first start, download torch
    download_and_extract_pytorch_libs( os.path.join(root, 'main') )
    



if __name__ == '__main__':
    download_and_extract_pytorch_libs('DELETE_ME_TORCH')

    print('Done')
