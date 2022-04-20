from base.backend.settings import Settings as BaseSettings

class Settings(BaseSettings):
    @classmethod
    def get_defaults(cls):
         defaults = super().get_defaults()
         defaults['exmask_enabled'] = False
         return defaults
