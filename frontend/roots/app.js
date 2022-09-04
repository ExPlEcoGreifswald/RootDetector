
RootDetectorApp = class extends BaseApp {
    static Detection       = RootDetection;
    static Download        = RootDetectionDownload;
    static ViewControls    = ViewControls;
    static Settings        = RootsSettings;
    static FileInput       = RootsFileInput;
    static Training        = RootsTraining;
}


//override
GLOBAL.App = RootDetectorApp;
App        = RootDetectorApp;
