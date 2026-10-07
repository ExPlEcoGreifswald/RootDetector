"""Local-service path and upload validation primitives."""

import hashlib
import ntpath
import os
import typing as tp
import unicodedata
import warnings

import PIL.Image


SUPPORTED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tif', '.tiff'}
SUPPORTED_IMAGE_FORMATS = {'JPEG', 'PNG', 'TIFF'}
ASSET_SCHEMA_VERSION = 'rootdetector-web-rc2-1'
MAX_FILENAME_BYTES = 240
MAX_UPLOAD_BYTES = 256 * 1024 * 1024
MAX_CONFIGURABLE_UPLOAD_MIB = 4096
UPLOAD_FORM_OVERHEAD_BYTES = 1024 * 1024
MAX_UPLOAD_FILES = 16
MAX_IMAGE_PIXELS = 200_000_000
PIL.Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


class ValidationError(ValueError):
    """Raised when untrusted request data violates a local safety boundary."""

    def __init__(self, message:str, code:str='invalid_request', status:int=400):
        super().__init__(message)
        self.code = code
        self.status = status


def configured_max_upload_bytes() -> int:
    """Return the explicit per-file limit, retaining 256 MiB by default."""
    raw_value = os.environ.get('ROOTDETECTOR_MAX_UPLOAD_MIB', '256')
    try:
        size_mib = int(raw_value)
    except ValueError as exc:
        raise ValueError('ROOTDETECTOR_MAX_UPLOAD_MIB must be a whole number of MiB.') from exc
    if not 1 <= size_mib <= MAX_CONFIGURABLE_UPLOAD_MIB:
        raise ValueError(
            'ROOTDETECTOR_MAX_UPLOAD_MIB must be between 1 and {} MiB.'.format(
                MAX_CONFIGURABLE_UPLOAD_MIB
            )
        )
    return size_mib * 1024 * 1024


def upload_limit_label(max_upload_bytes:int) -> str:
    return '{} MiB'.format(max_upload_bytes // (1024 * 1024))


def validate_filename(
    value:tp.Any,
    allowed_extensions:tp.Optional[tp.Set[str]]=None,
) -> str:
    """Accept one portable filename, never a path."""
    if not isinstance(value, str) or not value:
        raise ValidationError('A non-empty filename is required.', 'invalid_filename')
    if '\x00' in value or value in {'.', '..'}:
        raise ValidationError('The filename is not valid.', 'invalid_filename')
    if os.path.isabs(value) or ntpath.isabs(value) or ntpath.splitdrive(value)[0]:
        raise ValidationError('Absolute filenames are not allowed.', 'invalid_filename')
    if os.path.basename(value) != value or ntpath.basename(value) != value:
        raise ValidationError('Folders and path separators are not allowed in filenames.', 'invalid_filename')
    if any(unicodedata.category(character).startswith('C') for character in value):
        raise ValidationError('Control characters are not allowed in filenames.', 'invalid_filename')
    if len(value.encode('utf-8')) > MAX_FILENAME_BYTES:
        raise ValidationError('The filename is too long.', 'invalid_filename')

    extension = os.path.splitext(value)[1].lower()
    if allowed_extensions is not None and extension not in allowed_extensions:
        raise ValidationError(
            'Unsupported file type for {}.'.format(value),
            'unsupported_file_type',
            415,
        )
    return value


def safe_resolve(
    base_path:str,
    untrusted_name:tp.Any,
    allowed_extensions:tp.Optional[tp.Set[str]]=None,
    must_exist:bool=False,
) -> str:
    """Resolve a validated filename and prove that it remains below ``base_path``."""
    name = validate_filename(untrusted_name, allowed_extensions)
    base = os.path.realpath(base_path)
    candidate = os.path.realpath(os.path.join(base, name))
    try:
        contained = os.path.commonpath([base, candidate]) == base
    except ValueError:
        contained = False
    if not contained:
        raise ValidationError('The requested path is outside the allowed directory.', 'unsafe_path')
    if must_exist and not os.path.isfile(candidate):
        raise ValidationError('The requested file does not exist.', 'file_not_found', 404)
    return candidate


def sha256(path:str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def files_are_identical(path0:str, path1:str) -> bool:
    return os.path.getsize(path0) == os.path.getsize(path1) and sha256(path0) == sha256(path1)


def validate_image_file(
    path:str,
    max_upload_bytes:int=MAX_UPLOAD_BYTES,
) -> tp.Dict[str, tp.Any]:
    """Fully decode the first frame to reject inputs processing cannot read."""
    size = os.path.getsize(path)
    if size == 0:
        raise ValidationError('Uploaded images must not be empty.', 'empty_upload')
    if size > max_upload_bytes:
        raise ValidationError(
            'The uploaded image exceeds the {} file limit.'.format(
                upload_limit_label(max_upload_bytes)
            ),
            'upload_too_large',
            413,
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', PIL.Image.DecompressionBombWarning)
            with PIL.Image.open(path) as image:
                image_format = image.format
                width, height = image.size
                frames = getattr(image, 'n_frames', 1)
                if image_format not in SUPPORTED_IMAGE_FORMATS:
                    raise ValidationError(
                        'Unsupported image encoding. Use PNG, JPEG, TIFF, or TIF.',
                        'unsupported_image',
                        415,
                    )
                if (
                    width <= 0
                    or height <= 0
                    or frames <= 0
                    or width * height * frames > MAX_IMAGE_PIXELS
                ):
                    raise ValidationError(
                        'The image dimensions exceed the 200-megapixel safety limit.',
                        'image_too_large',
                        413,
                    )
                # ``verify()`` only checks container structure for some formats. In
                # particular, malformed LZW TIFF data can pass ``verify()`` and then
                # fail at scanline 0 when detection calls ``convert('RGB')``. Loading
                # the pixels here keeps that failure in the import/preflight phase.
                image.load()
    except ValidationError:
        raise
    except (OSError, ValueError, PIL.Image.DecompressionBombError) as exc:
        raise ValidationError(
            'The uploaded image could not be decoded completely. Re-export or '
            'convert it to a standard TIFF, PNG, or JPEG and try again.',
            'invalid_image',
            415,
        ) from exc

    return {
        'bytes': size,
        'format': image_format,
        'width': width,
        'height': height,
        'frames': frames,
    }
