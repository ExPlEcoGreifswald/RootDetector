

RootsFileInput = class extends BaseFileInput{
    //override
    static refresh_filetable(files){
        BaseFileInput.refresh_filetable(files)
        RootTracking.set_input_files(files)
    }


    //override
    static async load_result(filename, file){
        const inputfile = GLOBAL.files[filename]
        if(inputfile != undefined){
            const blob   = await(file.async? file.async('blob') : file)
            file         = new File([blob], `${filename}.segmentation.png`, {type:'image/png'})

            //upload to flask & postprocess
            await upload_file_to_flask(file)
            const result = await $.get(`/postprocess_detection/${file.name}`)
            //const result = {segmentation: file}  //TODO replace string with file
            App.Detection.set_results(filename, result)
        }
    }
}




