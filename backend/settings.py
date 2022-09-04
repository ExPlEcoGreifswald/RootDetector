from base.backend.settings import Settings as BaseSettings

import torch

class Settings(BaseSettings):
    @classmethod
    def get_defaults(cls):
         defaults = super().get_defaults()
         defaults['exmask_enabled'] = False
         defaults['use_gpu']        = False
         return defaults

    def get_settings_as_dict(self):
        s = super().get_settings_as_dict()
        s['available_gpu'] = torch.cuda.get_device_name() if torch.cuda.is_available() else None
        return s
