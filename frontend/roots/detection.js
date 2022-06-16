


RootDetection = class extends BaseDetection{
    //override
    static async set_results(filename, results){
        if(results!=undefined && is_string(results.skeleton))
            results.skeleton = await fetch_as_file(url_for_image(results.skeleton))
        
        await super.set_results(filename, results);

        var clear = (results==undefined)
        $(`[filename="${filename}"] .skeletonized-checkbox`)
            .toggleClass('disabled', clear)
            .checkbox({onChange: this.on_toggle_skeleton})
    }

    static on_toggle_skeleton(){
        var $root    = $(this).closest('[filename]')
        var filename = $root.attr('filename')
        var checked  = $(this).closest('.checkbox').checkbox('is checked')
        var src      = checked? GLOBAL.files[filename].results.skeleton : GLOBAL.files[filename].results.segmentation;

        var $result_image   = $root.find('img.result-image')
        GLOBAL.App.ImageLoading.set_image_src($result_image, src)
        var $result_overlay = $root.find(`img.overlay`)
        GLOBAL.App.ImageLoading.set_image_src($result_overlay, src)
    }
}

