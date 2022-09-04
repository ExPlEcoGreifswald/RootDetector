import os, subprocess
BaseCase = __import__('base_case').BaseCase



class TestDownloadRootDetection(BaseCase):
    def test_download_root_detection(self):
        if not self.is_chromium() and not self.headed:
            self.skipTest('xdotool does not work with headless firefox for some reason')
        self.open_main(static=False)

        self.send_input_files_from_assets([ "test_image0.jpg", "test_image1.jpg" ])
        self.click('label:contains("test_image1.jpg")')

        root_css = '[filename="test_image1.jpg"]'
        down_css = root_css + ' a.download'
        
        #click on the processing button
        self.click(root_css+' .play.icon')
        #wait until done
        self.wait_for_element_not_visible(root_css+' .dimmer', timeout=6)

        self.click(down_css)
        #send enter key to x11 to confirm the download dialog window
        if not self.is_chromium():  #self.is_firefox()
            self.sleep(1.0)
            subprocess.call('xdotool key Return', shell=True)

        self.sleep(0.5)
        f = self.get_path_of_downloaded_file('test_image1.jpg.results.zip')
        import zipfile
        zip = zipfile.ZipFile(f)
        assert 'test_image1.jpg.segmentation.png' in zip.namelist()
        assert 'test_image1.jpg.skeleton.png' in zip.namelist()
        assert 'statistics.csv' in zip.namelist()

        #TODO: more checks: csv format & values, segmentation etc

        if self.demo_mode:
            self.sleep(1)
