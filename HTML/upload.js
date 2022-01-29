

function on_drop(event){
    event.preventDefault();

    load_results_from_list_of_files(event.dataTransfer.files)
}

function on_dragover(event){
    event.preventDefault();
}




function load_results_grom_zipfile(zipfile){
    return JSZip.loadAsync(zipfile).then(function(zip) {
        load_results_from_list_of_files(zip.files)
    })
}

function maybe_decompress_file(f){
    return (f.async)? f.async('blob') : f
}

async function load_results_from_list_of_files(files){
    for(var f of Object.values(files)){
        if(["application/zip", "application/x-zip-compressed"].indexOf(f.type)!=-1)
        load_results_grom_zipfile(f);
    }

    for(var image_filename0 in global.input_files){
        for(var image_filename1 in global.input_files[image_filename0].tracking_results){
            let tracking_results_file    = undefined
            let segmentation0_file       = undefined
            let segmentation1_file       = undefined

            for(var f of Object.values(files)){
                var zipped_filename = remove_dirname(f.name);
                switch(zipped_filename){
                    case `${image_filename0}.segmentation.png`:
                        segmentation0_file = maybe_decompress_file(f);
                        break;
                    case `${image_filename1}.segmentation.png`:
                        segmentation1_file = maybe_decompress_file(f);
                        break;
                    case `${image_filename0}.${image_filename1}.json`:
                        tracking_results_file = maybe_decompress_file(f);
                        break;
                }
            }

            if(tracking_results_file && segmentation0_file && segmentation1_file)
                RootTracking.load_result(image_filename0, image_filename1, tracking_results_file, segmentation0_file, segmentation1_file)
        }
    }
}

