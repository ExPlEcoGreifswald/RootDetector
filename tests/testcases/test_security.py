import os

import PIL.Image
import pytest

from backend import security


@pytest.mark.parametrize('value', [
    '../image.png',
    '..\\image.png',
    '/tmp/image.png',
    'C:\\temp\\image.png',
    'folder/image.png',
    'folder\\image.png',
    'bad\x00name.png',
    'bad\nname.png',
])
def test_validate_filename_rejects_paths_and_control_characters(value):
    with pytest.raises(security.ValidationError):
        security.validate_filename(value)


def test_safe_resolve_rejects_symlink_escape(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    outside = tmp_path / 'outside.png'
    outside.write_bytes(b'outside')
    os.symlink(str(outside), str(cache / 'linked.png'))

    with pytest.raises(security.ValidationError, match='outside'):
        security.safe_resolve(str(cache), 'linked.png')


def test_upload_limit_defaults_and_accepts_bounded_override(monkeypatch):
    monkeypatch.delenv('ROOTDETECTOR_MAX_UPLOAD_MIB', raising=False)
    assert security.configured_max_upload_bytes() == 256 * 1024 * 1024

    monkeypatch.setenv('ROOTDETECTOR_MAX_UPLOAD_MIB', '512')
    assert security.configured_max_upload_bytes() == 512 * 1024 * 1024

    for value in ('0', '-1', '4097', 'no-limit', '1.5'):
        monkeypatch.setenv('ROOTDETECTOR_MAX_UPLOAD_MIB', value)
        with pytest.raises(ValueError, match='ROOTDETECTOR_MAX_UPLOAD_MIB'):
            security.configured_max_upload_bytes()


def test_file_limit_uses_configured_value_before_decoding(tmp_path):
    image_path = tmp_path / 'oversize.png'
    image_path.write_bytes(b'x' * 1025)
    with pytest.raises(security.ValidationError, match='file limit') as error:
        security.validate_image_file(str(image_path), max_upload_bytes=1024)
    assert error.value.code == 'upload_too_large'
    assert error.value.status == 413


def test_validate_image_checks_encoding_and_pixel_limit(tmp_path, monkeypatch):
    image_path = tmp_path / 'valid.png'
    PIL.Image.new('RGB', (8, 6)).save(str(image_path))
    metadata = security.validate_image_file(str(image_path))
    assert metadata['format'] == 'PNG'
    assert metadata['width'] == 8
    assert metadata['height'] == 6

    monkeypatch.setattr(security, 'MAX_IMAGE_PIXELS', 10)
    with pytest.raises(security.ValidationError, match='megapixel'):
        security.validate_image_file(str(image_path))


def test_validate_image_counts_all_tiff_frames(tmp_path, monkeypatch):
    image_path = tmp_path / 'stack.tiff'
    frames = [PIL.Image.new('L', (8, 8)) for _ in range(2)]
    frames[0].save(str(image_path), save_all=True, append_images=frames[1:])

    monkeypatch.setattr(security, 'MAX_IMAGE_PIXELS', 100)
    with pytest.raises(security.ValidationError, match='megapixel'):
        security.validate_image_file(str(image_path))


def test_validate_image_rejects_tiff_that_opens_but_cannot_fully_decode(tmp_path):
    image_path = tmp_path / 'truncated.tiff'
    PIL.Image.new('RGB', (100, 100), 'red').save(str(image_path))
    image_path.write_bytes(image_path.read_bytes()[:-100])

    # Pillow can still inspect this TIFF's header, but processing its pixels fails.
    with PIL.Image.open(str(image_path)) as image:
        image.verify()

    with pytest.raises(security.ValidationError, match='decoded completely') as error:
        security.validate_image_file(str(image_path))
    assert error.value.code == 'invalid_image'
