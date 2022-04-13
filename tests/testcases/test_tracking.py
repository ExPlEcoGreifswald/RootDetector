BaseCase = __import__('base_case').BaseCase
import pytest, os, subprocess


class TrackingTest(BaseCase):
    @pytest.mark.slow
    def test_basic_tracking_success(self):
        self.open_main(static=False)
        
        #open the tracking tab
        self.click('a:contains("Tracking")')

        filenames = [
            "PD_T088_L004_13.11.18_091057_015_SS_crop.tiff",
            "PD_T088_L004_17.10.18_140056_014_SS_crop.tiff",
        ]
        self.send_input_files_from_assets(filenames)

        #open one file
        self.click(f'#tracking-filetable label:contains("{filenames[0]}")')
        root_css = f'#tracking-filetable [filename0="{filenames[1]}"]'

        #set the right models                      #FIXME: this is very brittle
        self.click("#settings-button")                                              
        self.click("div#settings-active-model")                                          
        self.click("div#settings-active-model div>:contains('2022-01-11_022_segmentation.full')")    
        self.click("div#settings-tracking-model")                                        
        self.click("div#settings-tracking-model div>:contains('2022-01-10_022_roottracking.stage2')")  
        self.click("div#settings-ok-button i")

        #click on the processing button
        self.click(root_css+' .play.icon')

        #a dimmer that indicates that processing is in progress should be visible
        self.wait_for_element_visible(root_css+' .dimmer', timeout=2)
        #there should be no error indication
        assert not self.find_visible_elements('.error') + self.find_visible_elements('.failed') 
        #after processing is done, the dimmer should be gone (can take a while)
        self.wait_for_element_not_visible(root_css+' .dimmer', timeout=15)

        #TODO: check some indication that a file is finished processing (bold font in the file list)

        #download button should not be disabled
        assert 'disabled' not in self.get_attribute(root_css + ' a.download', 'class')
        #download result
        if self.is_chromium() or self.headed:
            self.click(root_css + ' a.download')
            #send enter key to x11 to confirm the download dialog window
            if not self.is_chromium():  #self.is_firefox()
                self.sleep(1.0)
                subprocess.call('xdotool key Return', shell=True)

            fname = 'PD_T088_L004_17.10.18_140056_014_SS_crop.tiff.PD_T088_L004_13.11.18_091057_015_SS_crop.tiff.results.zip'
            self.assert_downloaded_file(fname)
            f = self.get_path_of_downloaded_file(fname)
            import zipfile
            zip = zipfile.ZipFile(f)
            assert 'PD_T088_L004_17.10.18_140056_014_SS_crop.tiff.PD_T088_L004_13.11.18_091057_015_SS_crop.tiff.csv' in zip.namelist()
        
        if self.demo_mode:
            self.sleep(1)

        #assert 0



#TODO: change segmentation model inbetween two processing runs
