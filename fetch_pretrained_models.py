import urllib.request, os

URLS = {
    'https://www.dropbox.com/s/p2mlxhaz0diyjvp/2022-04-19_028a_WM.pt.zip?dl=1'        : 'models/detection/2022-04-19_028a_WM.pt.zip',
    'https://www.dropbox.com/s/u6zg2q3t668xih3/2022-07-14_028c_WM_exmask.pt.zip?dl=1' : 'models/exclusion_mask/2022-07-14_028c_WM_exmask.pt.zip',
    'https://www.dropbox.com/s/fr7tptmig5u5yre/2022-01-10_022_roottracking.stage2.pkl?dl=1' : 'models/tracking/2022-01-10_022_roottracking.stage2.pkl',
}

for url, destination in URLS.items():
    print(f'Downloading {url} ...')
    with urllib.request.urlopen(url) as f:
        os.makedirs( os.path.dirname(destination), exist_ok=True )
        open(destination, 'wb').write(f.read())

