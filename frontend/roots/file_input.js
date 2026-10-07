

RootsFileInput = class extends BaseFileInput{
    static uploaded_files = new Map()

    static show_file_error(error){
        console.error(error)
        $('body').toast({
            message: RootSecurity.error_message(error, 'The selected files could not be loaded.'),
            class: 'error', displayTime: 0, closeIcon: true,
        })
    }

    static file_identity(file){
        return [file.name, file.size, file.lastModified ?? 0, file.type ?? ''].join('\u0000')
    }

    static reset_uploaded_files(){
        this.uploaded_files = new Map()
    }

    static is_retryable_upload_error(error){
        const status = Number(error?.status ?? 0)
        return status == 0 || [408, 425, 429].includes(status) || status >= 500
    }

    static async ensure_uploaded(file, options={}){
        const identity = this.file_identity(file)
        if(this.uploaded_files.get(file.name) == identity)
            return {skipped: true, attempts: 0}

        const max_attempts = Math.max(1, Number(options.max_attempts ?? 3))
        for(let attempt = 1; attempt <= max_attempts; attempt += 1){
            try {
                const request = RootSecurity.upload_file(file)
                if(options.on_request)
                    options.on_request(request)
                const response = await request
                this.uploaded_files.set(file.name, identity)
                return {response: response, skipped: false, attempts: attempt}
            } catch(error) {
                const will_retry = (
                    attempt < max_attempts
                    && this.is_retryable_upload_error(error)
                    && !options.is_cancelled?.()
                )
                if(!will_retry)
                    throw error
                const delay = 500 * attempt
                options.on_retry?.(attempt + 1, max_attempts, delay, error)
                await sleep(delay)
            } finally {
                options.on_request?.(undefined)
            }
        }
    }

    static async on_inputfiles_select(event){
        try {
            await this.load_list_of_files(event.target.files)
        } catch(error) {
            this.show_file_error(error)
        } finally {
            event.target.value = ''
        }
    }

    static async on_inputfolder_select(event){
        try {
            const files = Array.from(event.target.files).filter(file => this.is_supported_image(file))
            await this.set_input_files(files)
        } catch(error) {
            this.show_file_error(error)
        } finally {
            event.target.value = ''
        }
    }

    static async on_annotations_select(event){
        try {
            await this.load_result_files(event.target.files)
        } catch(error) {
            this.show_file_error(error)
        } finally {
            event.target.value = ''
        }
    }

    static async set_input_files(files){
        files = Array.from(files)
        const filenames = files.map(file => file.name)
        const duplicates = filenames.filter((name, index) => filenames.indexOf(name) != index)
        if(duplicates.length)
            throw new Error(`Duplicate filenames are not supported: ${[...new Set(duplicates)].join(', ')}`)

        if(!window.location.href.startsWith('file://'))
            await RootSecurity.request('/clear_cache', 'POST')

        this.reset_uploaded_files()
        RootsTraining.clear_imported_labels()
        GLOBAL.files = []
        for(const file of files)
            GLOBAL.files[file.name] = new InputFile(file)
        $('.tabs .item[data-tab="detection"]').click()
        const result = await this.refresh_filetable(files)
        RootPipeline.on_files_ready()
        return result
    }

    static async on_drop(event){
        event.preventDefault()
        try {
            await this.load_list_of_files(event.dataTransfer.files)
        } catch(error) {
            this.show_file_error(error)
        }
    }

    static is_supported_image(file){
        const extension = file.name.toLowerCase().split('.').pop()
        return file.type.startsWith('image/') || ['jpg', 'jpeg', 'png', 'tif', 'tiff'].includes(extension)
    }

    static async load_list_of_files(files){
        files = Array.from(files)
        const result_suffixes = ['.segmentation.png', '.skeleton.png', '.exclusionmask.png']
        const is_result_image = file => result_suffixes.some(
            suffix => file.name.toLowerCase().endsWith(suffix)
        )
        const inputfiles = files.filter(
            file => this.is_supported_image(file) && !is_result_image(file)
        )
        if(inputfiles.length)
            await this.set_input_files(inputfiles)

        const remaining_files = files.filter(file => !inputfiles.includes(file))
        await this.load_result_files(remaining_files)
    }

    static async load_result_files(files){
        const result_files = await this.collect_result_files(files)
        if(Object.keys(result_files).length == 0)
            return

        const $modal = $('#loading-files-modal')
        $modal.modal({closable: false, inverted: true, duration: 0}).modal('show')
        $modal.find('.progress').progress({
            total: Object.keys(result_files).length,
            value: 0,
            showActivity: false,
        })
        try {
            for(const [filename, results] of Object.entries(result_files)){
                const unzipped_results = await Promise.all(results.map(maybe_unzip))
                await this.load_result(filename, unzipped_results)
                $modal.find('.progress').progress('increment')
            }
        } finally {
            $modal.modal({closable: true}).modal('hide')
            await sleep(500)
            $modal.find('.progress').progress('reset')
        }
    }

    //override
    static async refresh_filetable(files){
        const promise  = BaseFileInput.refresh_filetable(files)
        const promise2 = RootTracking.set_input_files(files)
        const result = await Promise.all([promise, promise2])
        RootDetectorApp.enhance_accessibility()
        return result
    }

    //override
    static match_resultfile_to_inputfile(inputfilename, resultfilename){
        var basename          = file_basename(resultfilename)
        const no_ext_filename = remove_file_extension(inputfilename)
        const candidate_names = [
            inputfilename  +'.segmentation.png',
            no_ext_filename+'.segmentation.png',
            no_ext_filename+'.png',
        ]
        return (candidate_names.indexOf(basename) != -1)
    }

    //override
    static async load_result(filename, resultfiles){
        const inputfile = GLOBAL.files[filename]
        if(inputfile != undefined){
            const training_label = new File(
                [resultfiles[0]],
                `training-label-${Date.now()}-${Math.random().toString(36).slice(2)}.png`,
                {type:'image/png'},
            )
            // A prior prediction may already own the conventional result name
            // in the cache. Keep a separately named training label either way.
            if(inputfile.results){
                RootsTraining.register_imported_label(filename, training_label)
                $('body').toast({
                    message: `Imported a training label for ${filename}. The existing detection overlay was not replaced. Review the label before confirming training.`,
                    class: 'info', displayTime: 8000,
                })
                return
            }
            const resultfile = new File(
                //consistent file name
                [resultfiles[0]], `${filename}.segmentation.png`, {type:'image/png'}
            )

            //upload to flask & postprocess
            await this.ensure_uploaded(resultfile)
            const result = await RootSecurity.request(
                `/postprocess_detection/${encodeURIComponent(resultfile.name)}`,
                'POST',
            )
            await App.Detection.set_results(filename, result)
            RootsTraining.register_imported_label(filename, training_label)
        }
    }

    static async on_exclusionmasks_select(event){
        try {
            for(const selected_mask of event.target.files){
                const maskbasename = remove_file_extension(selected_mask.name)

                for(const inputfile of Object.values(GLOBAL.files)){
                    if( wildcard_test(maskbasename, remove_file_extension(inputfile.name)) ){
                        console.log('Matched mask for input file ', inputfile.name);
            
                        //indicate in the file table that a mask is available
                        //FIXME: this belongs into HTML files //FIXME:  class="cornered red circle icon"
                        $(`tr.title.table-row[filename="${inputfile.name}"]`)
                            .find('.status.icon.image').addClass('red')
            
                        //set file as not processed (needs reprocessing)
                        await App.Detection.set_results(inputfile.name, undefined)
            
                        const new_name = `${remove_file_extension(inputfile.name)}.exclusionmask.png`
                        const maskfile = rename_file(selected_mask, new_name)
                        await this.ensure_uploaded(maskfile)
                    }
                }
            }
        } finally {
            event.target.value = ""; //reset the input
        }
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
