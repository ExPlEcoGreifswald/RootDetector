import os
os.environ['TESTS_TO_SKIP'] = (
    '''test_download_all'''              #needs non-static
    '''test_load_results'''              #needs non-static, replaced with test_load_root_results.py:test_basic_load_results
)

