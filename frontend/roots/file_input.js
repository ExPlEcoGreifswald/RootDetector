

class RootsFileInput extends BaseFileInput{
    //override
    static refresh_filetable(files){
        BaseFileInput.refresh_filetable(files)
        RootTracking.set_input_files(files)
    }
}




