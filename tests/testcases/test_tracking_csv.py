import csv
import io
import os
import json
import zipfile

import pytest

from backend import root_tracking


def test_tracking_csv_header_matches_values_and_quotes_filenames():
    stats = {
        'sum_same': 11,
        'sum_decay': 12,
        'sum_growth': 13,
        'sum_negative': 14,
        'sum_exmask': 15,
        'sum_same_sk': 16,
        'sum_decay_sk': 17,
        'sum_growth_sk': 18,
        'kimura_same': 19,
        'kimura_decay': 20,
        'kimura_growth': 21,
    }
    csv_text = root_tracking.statistics_to_csv(
        stats,
        'first,image.png',
        'second image.png',
        True,
    )
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert len(rows) == 1
    row = rows[0]
    assert row['Filename 1'] == 'first,image.png'
    assert row['same pixels'] == '11'
    assert row['decay pixels'] == '12'
    assert row['growth pixels'] == '13'
    assert row['background pixels'] == '14'
    assert row['mask pixels'] == '15'
    assert row['status'] == 'OK'

    skipped = root_tracking.statistics_to_csv(
        {},
        'first.png',
        'second.png',
        root_tracking.TOO_MANY_ROOTS_ERROR,
    )
    skipped_row = list(csv.DictReader(io.StringIO(skipped)))[0]
    assert skipped_row['status'] == 'SKIPPED: Too many roots'

    quoted = root_tracking.statistics_to_csv(
        stats,
        'first,"line\nimage.png',
        'second image.png',
        True,
    )
    quoted_row = list(csv.DictReader(io.StringIO(quoted)))[0]
    assert quoted_row['Filename 1'] == 'first,"line\nimage.png'


def test_combined_tracking_csv_uses_first_valid_header(tmp_path, monkeypatch):
    monkeypatch.setattr(root_tracking.paths, 'get_cache_path', lambda: str(tmp_path))
    first = ('broken-a.png', 'broken-b.png')
    second = ('good,a.png', 'good-b.png')
    with open(os.path.join(str(tmp_path), '{}.{}.csv'.format(*first)), 'w') as output:
        output.write('incomplete\n')
    with open(os.path.join(str(tmp_path), '{}.{}.csv'.format(*second)), 'w') as output:
        output.write(root_tracking.statistics_to_csv({}, second[0], second[1], True))

    with pytest.warns(UserWarning, match='incomplete tracking CSV'):
        combined = root_tracking.combine_csv_statistics([first, second])
    rows = list(csv.reader(io.StringIO(combined)))
    assert rows[0][0:2] == ['Filename 1', 'Filename 2']
    assert rows[1][0:2] == list(second)


def test_combined_tracking_csv_keeps_every_valid_data_row(tmp_path, monkeypatch):
    monkeypatch.setattr(root_tracking.paths, 'get_cache_path', lambda: str(tmp_path))
    pair = ('one.png', 'two.png')
    csv_path = tmp_path / '{}.{}.csv'.format(*pair)
    csv_path.write_text(
        root_tracking.statistics_to_csv({}, pair[0], pair[1], True)
        + root_tracking.statistics_to_csv(
            {}, 'three.png', 'four.png', True, include_header=False
        )
    )
    rows = list(csv.DictReader(io.StringIO(root_tracking.combine_csv_statistics([pair]))))
    assert [(row['Filename 1'], row['Filename 2']) for row in rows] == [
        pair,
        ('three.png', 'four.png'),
    ]


def test_compile_tracking_results_records_schema_and_migration_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(root_tracking.paths, 'get_cache_path', lambda: str(tmp_path))
    pair = ('one.png', 'two.png')
    segmentation0 = tmp_path / 'rootdetector-segmentation-a.png'
    segmentation1 = tmp_path / 'rootdetector-segmentation-b.png'
    growthmap = tmp_path / '{}.{}.growthmap.png'.format(*pair)
    for path in [segmentation0, segmentation1, growthmap]:
        path.write_bytes(b'fixture')
    metadata_path = tmp_path / '{}.{}.json'.format(*pair)
    metadata_path.write_text(json.dumps({
        'segmentation0': segmentation0.name,
        'segmentation1': segmentation1.name,
        'growthmap': growthmap.name,
        'tracking_matcher': {
            'name': 'rootdetector-cancellable-bruteforce',
            'version': 1,
            'batch_size': 512,
        },
        'exclusion_mask_policy': 'first',
        'exclusion_masks': {'combined_pixels': 17},
    }))
    (tmp_path / '{}.{}.csv'.format(*pair)).write_text(
        root_tracking.statistics_to_csv({}, pair[0], pair[1], True)
    )

    archive_path = tmp_path / root_tracking.compile_results_into_zip([pair])
    with zipfile.ZipFile(str(archive_path)) as archive:
        manifest = json.loads(archive.read('tracking-results-manifest.json'))
        assert manifest['tracking_csv_schema'] == root_tracking.TRACKING_CSV_SCHEMA
        assert manifest['exclusion_mask_coordinate_system'] == 'observation1'
        assert manifest['pair_exclusion_masks'] == [{
            'filename0': 'one.png',
            'filename1': 'two.png',
            'policy': 'first',
            'masks': {'combined_pixels': 17},
            'matcher': {
                'name': 'rootdetector-cancellable-bruteforce',
                'version': 1,
                'batch_size': 512,
            },
        }]
        assert manifest['tracking_matcher_schema'] == 1
        assert 'incorrect headers' in manifest['migration_warning']
        assert any(name.endswith('one.png.segmentation.cache.png') for name in archive.namelist())
