

FileInput.regenerate_filetable = function(files){
    BaseFileInput.regenerate_filetable(files)
    RootTracking.set_input_files(files)
}


