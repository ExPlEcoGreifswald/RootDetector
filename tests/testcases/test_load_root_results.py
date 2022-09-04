BaseCase = __import__('base_case').BaseCase



class LoadResultsTest(BaseCase):
    def test_basic_load_results(self):
        self.open_main(static=False)        #currently nonstatic required

        filenames = [
            "PD_T088_L004_13.11.18_091057_015_SS_crop.tiff",
            "PD_T088_L004_17.10.18_140056_014_SS_crop.tiff",
            "PD_T088_L004_13.11.18_091057_015_SS_crop.tiff.results.zip"
        ]
        self.send_input_files_from_assets(filenames)
        #some time needed for postprocessing
        self.sleep(0.5)

        root_css = f'[filename="{filenames[0]}"]'

        #make sure the row label is bold to indicate that this file is processed
        script = f''' return $('{root_css} label').css('font-weight') '''
        assert int(self.execute_script(script)) > 500

        #re-download result
        self.click(f'label:contains("{filenames[0]}")')
        if self.is_chromium() or self.headed:
            self.click(root_css + ' a.download')
            #send enter key to x11 to confirm the download dialog window
            if not self.is_chromium():  #self.is_firefox()
                self.sleep(1.0)
                subprocess.call('xdotool key Return', shell=True)

            fname = f'{filenames[0]}.results.zip'
            f = self.get_path_of_downloaded_file(fname)
            self.assert_downloaded_file(fname)
            import zipfile
            zip = zipfile.ZipFile(f)
            assert f'{filenames[0]}.segmentation.png' in zip.namelist()
            assert f'{filenames[0]}.skeleton.png' in zip.namelist()
            assert 'statistics.csv' in zip.namelist()

        #test loading filename.png (without .segmentation.png )
        extra_filenames = [
            "PD_T088_L004_17.10.18_140056_014_SS_crop.png",
        ]
        self.send_input_files_from_assets(extra_filenames)
        #some time needed for postprocessing
        self.sleep(0.5)
        self.assert_no_js_errors()

        root_css = f'[filename="{filenames[1]}"]'

        #make sure the row label is bold to indicate that this file is processed
        script = f''' return $('{root_css} label').css('font-weight') '''
        assert int(self.execute_script(script)) > 500






