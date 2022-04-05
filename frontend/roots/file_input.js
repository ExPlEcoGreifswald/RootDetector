

class RootsFileInput extends BaseFileInput{
    static regenerate_filetable(files){
        BaseFileInput.regenerate_filetable(files)
        RootTracking.set_input_files(files)
    }
}




