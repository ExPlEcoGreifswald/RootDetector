


RootDetection = class extends BaseDetection{
    static async on_process_image(event){
        const filename = $(event.target).closest('[filename]').attr('filename')
        return await this.process_image(filename)
    }

    static async on_process_all(event){
        const filenames = Object.keys(GLOBAL.files)
        const $button = $(event.currentTarget || event.target)
        $button.hide()
        $button.siblings('.cancel-processing, .processing').show().removeClass('disabled')
        GLOBAL.cancel_requested = false
        const failed = []
        for(const filename of filenames){
            if(GLOBAL.cancel_requested)
                break
            try {
                await this.process_image(filename)
            } catch(error) {
                failed.push({filename: filename, error: error})
                $('body').toast({
                    message: (
                        `Processing failed for ${filename}. `
                        + `${RootSecurity.error_message(error)} `
                        + 'Continuing with the next image.'
                    ),
                    class: 'error', displayTime: 0, closeIcon: true,
                })
            }
        }
        $button.show()
        $button.siblings('.cancel-processing, .processing').hide()
        return {failed: failed, cancelled: GLOBAL.cancel_requested}
    }

    static async process_image(filename, upload_image=true){
        await this.set_results(filename, undefined)
        this.set_processing(filename)

        function on_message(event){
            const data = JSON.parse(event.originalEvent.data)
            if(data.image == filename)
                console.log(event)
        }
        $(GLOBAL.event_source).on('message', on_message)

        try {
            if(upload_image)
                await RootsFileInput.ensure_uploaded(GLOBAL.files[filename])
            const results = await RootSecurity.request(
                `/process_image/${encodeURIComponent(filename)}`,
                'POST',
            )
            await this.set_results(filename, results)
            return results
        } catch(error) {
            console.error(`Processing failed for ${filename}.`, error)
            this.set_failed(filename)
            const report = await RootSecurity.report_client_error(
                'manual_detection',
                filename,
                error,
            )
            const diagnostic = report?.diagnostic_id ? ` [${report.diagnostic_id}]` : ''
            throw new Error(`${RootSecurity.error_message(error)}${diagnostic}`)
        } finally {
            $(GLOBAL.event_source).off('message', on_message)
        }
    }

    //override
    static async set_results(filename, results){
        RootsTraining.forget_imported_label(filename)
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

        //var $result_image   = $root.find('img.result-image')
        //GLOBAL.App.ImageLoading.set_image_src($result_image, src)
        var $result_overlay = $root.find(`img.overlay`)
        GLOBAL.App.ImageLoading.set_image_src($result_overlay, src)
    }
}
