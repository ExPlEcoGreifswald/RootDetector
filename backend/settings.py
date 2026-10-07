from base.backend.settings import Settings as BaseSettings
import typing as tp
import torch

class Settings(BaseSettings):
    exmask_enabled: bool
    use_gpu: bool
    too_many_roots: int

    @classmethod
    def get_defaults(cls):
        defaults = tp.cast(tp.Dict[str, tp.Any], super().get_defaults())
        defaults['exmask_enabled'] = False
        defaults['use_gpu']        = False
        defaults['too_many_roots'] = 100000
        return defaults

    def load_settings_from_file(self):
        settings = super().load_settings_from_file()
        # Older partial saves may contain only one model type. Restore the
        # omitted selections from available defaults on the next launch.
        active_models = settings.get('active_models', {})
        if isinstance(active_models, dict):
            defaults = self.get_defaults()['active_models']
            settings['active_models'] = dict(defaults, **active_models)
        return settings

    def get_settings_as_dict(self):
        s = super().get_settings_as_dict()
        s['available_gpu'] = torch.cuda.get_device_name() if torch.cuda.is_available() else None
        return s



import hashlib
import urllib.request
import os
from base.backend.app import get_models_path, path_to_main_module

#TODO: replace path_to_main_module with models_path (need to fix tests)
DEFAULT_PRETRAINED_FILE = os.path.join(path_to_main_module(), 'models', 'pretrained_models.txt')

def parse_pretrained_models_file(path=DEFAULT_PRETRAINED_FILE) -> dict:
    models = {}
    with open(path, 'r') as source:
        for lineno, raw_line in enumerate(source, 1):
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            fields = [field.strip() for field in line.split(' : ')]
            if len(fields) not in [2, 3]:
                raise ValueError('Invalid pretrained model entry on line {}'.format(lineno))
            destination, url = fields[:2]
            models[destination] = {
                'url': url,
                'sha256': fields[2].lower() if len(fields) == 3 else None,
            }
    return models


def _sha256(path:str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate_pretrained_models() -> None:
    """Fail without network access when required model files are missing or corrupt."""
    models_path = get_models_path()
    problems = []
    for relative_path, model in parse_pretrained_models_file().items():
        destination = os.path.join(models_path, relative_path)
        if not os.path.isfile(destination):
            problems.append('missing {}'.format(relative_path))
            continue
        expected_hash = model['sha256']
        if expected_hash and _sha256(destination) != expected_hash:
            problems.append('checksum mismatch {}'.format(relative_path))
    if problems:
        raise RuntimeError(
            'Pretrained models are not ready ({}). Run `python fetch_pretrained_models.py` '
            'or `docker compose -f compose.core.yml run --rm model-fetch`.'.format('; '.join(problems))
        )

def ensure_pretrained_models() -> None:
    models_path = get_models_path()
    for destination, model in parse_pretrained_models_file().items():
        destination = os.path.join(models_path, destination)
        expected_hash = model['sha256']
        if os.path.exists(destination):
            if not expected_hash or _sha256(destination) == expected_hash:
                continue
            print('Checksum mismatch for {}. Downloading a verified replacement.'.format(destination))

        url = model['url']
        temporary = destination + '.download'
        print(f'Downloading {url} ...')
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        try:
            try:
                with urllib.request.urlopen(url, timeout=60) as response, open(temporary, 'wb') as output:
                    for block in iter(lambda: response.read(1024 * 1024), b''):
                        output.write(block)
            except Exception as exc:
                raise RuntimeError(
                    'Could not download model {}. Check the internet connection and try again.'.format(destination)
                ) from exc
            actual_hash = _sha256(temporary)
            if expected_hash and actual_hash != expected_hash:
                raise RuntimeError(
                    'Downloaded model checksum mismatch for {}: expected {}, got {}'.format(
                        destination, expected_hash, actual_hash
                    )
                )
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
