import os
os.environ['TESTS_TO_SKIP'] = (
    '''test_download_all'''              #needs non-static
    '''test_load_results'''              #needs non-static, replaced with test_load_root_results.py:test_basic_load_results
    '''test_add_boxes'''                 #no boxes
    '''test_overlay_side_by_side_switch'''   #side-by-side removed
)

