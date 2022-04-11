
RootDetectorApp = class extends BaseApp {
    static Detection       = BaseDetection;
    static Download        = RootDetectionDownload;
    static ViewControls    = ViewControls;
    static Settings        = RootsSettings;
    static FileInput       = RootsFileInput;
}


//override
App = RootDetectorApp;
