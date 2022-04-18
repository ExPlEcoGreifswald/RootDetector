

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

    static on_excludemasks_select(event){
        for(var maskfile of event.target.files){
            var maskbasename = remove_file_extension(maskfile.name)

            for(var inputfile of Object.values(GLOBAL.files)){
                if( wildcard_test(maskbasename, remove_file_extension(inputfile.name)) ){
                    console.log('Matched mask for input file ', inputfile.name);
            
                    //indicate in the file table that a mask is available
                    //FIXME: this belongs into HTML files //FIXME:  class="cornered red circle icon"
                    $(`tr.title.table-row[filename="${inputfile.name}"]`)
                        .find('.status.icon.image').addClass('red')
            
                    //set file as not processed (needs reprocessing)
                    App.Detection.set_results(inputfile.name, undefined)
            
                    var new_name   = `${remove_file_extension(inputfile.name)}.excludemask.png`
                        maskfile   = rename_file(maskfile, new_name)
                    upload_file_to_flask(maskfile)
                }
            }
        }
        event.target.value = ""; //reset the input
    }
}




function wildcard_test(wildcard_pattern, str) {
    //string comparison with wildcard characters * and ~
    //https://stackoverflow.com/questions/26246601/wildcard-string-comparison-in-javascript
    let w = wildcard_pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&'); // regexp escape 
        w = w.replace(/~/g,'*');                                   //allow ~ as wildcard (for windows paths)
    const re = new RegExp(`^${w.replace(/\*/g,'.*').replace(/\?/g,'.')}$`,'i');
    return re.test(str); // remove last 'i' above to have case sensitive
}
