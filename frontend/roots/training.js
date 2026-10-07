

RootsTraining = class extends BaseTraining {
    static active_run_id = undefined
    static terminal_states = ['completed', 'cancelled', 'failed']
    static training_states = {}
    static imported_labels = new Map()

    static clear_imported_labels(){
        this.imported_labels = new Map()
        $('#training-reviewed-labels-checkbox').prop('checked', false)
        this.update_number_of_training_files_info()
    }

    static forget_imported_label(filename){
        if(this.imported_labels.delete(filename)){
            $('#training-reviewed-labels-checkbox').prop('checked', false)
            this.update_number_of_training_files_info()
        }
    }

    static register_imported_label(filename, label){
        this.imported_labels.set(filename, label)
        $('#training-reviewed-labels-checkbox').prop('checked', false)
        this.update_number_of_training_files_info()
    }

    //override
    static refresh_tab(){
        super.refresh_tab()
        this.update_number_of_training_files_info()
    }
    
    // Detection predictions are never selected as training labels automatically.
    static get_selected_files(){
        return Array.from(this.imported_labels.keys()).filter(name => !!GLOBAL.files[name])
    }

    //override
    static get_training_options(){
        const training_type = $('#training-model-type').dropdown('get value');
        return {
            training_type       : training_type,
            learning_rate       : Number($('#training-learning-rate')[0].value),
            epochs              : Number($('#training-number-of-epochs')[0].value),
        };
    }

    static async on_start_training(){
        if(this.active_run_id)
            return

        const filenames = this.get_selected_files()
        const options = this.get_training_options()
        if(!filenames.length || !$('#training-reviewed-labels-checkbox').is(':checked')){
            $('body').toast({
                message: 'Load a small set of reviewed labels and confirm their review before training.',
                class: 'error', displayTime: 0, closeIcon: true,
            })
            return
        }
        this.training_states[options.training_type] = 'running'
        $('#training-new-modelname-field').hide()
        try {
            this.show_modal()
            await this.upload_training_data(filenames)
            const run = await RootSecurity.request('/api/training/runs', 'POST', {
                filenames: filenames,
                label_filenames: filenames.map(filename => this.imported_labels.get(filename).name),
                options: options,
                label_review: {source: 'user_reviewed', confirmed: true},
            })
            this.active_run_id = run.id
            const result = await this.poll_until_finished(options)
            await GLOBAL.App.Settings.load_settings()
            this.update_model_info()
            return result
        } catch(error) {
            console.error(error)
            this.training_states[options.training_type] = 'failed'
            const diagnostic = error?.responseJSON?.diagnostic_id
            const message = error?.responseJSON?.message ?? error?.message ?? 'Training failed.'
            this.fail_modal(message)
            $('body').toast({
                message: diagnostic ? `${message} Diagnostic ID: ${diagnostic}` : message,
                class: 'error',
                displayTime: 0,
                closeIcon: true,
            })
            throw error
        }
    }

    static async poll_until_finished(options){
        while(this.active_run_id){
            const run = await RootSecurity.request(
                `/api/training/runs/${this.active_run_id}`,
                'GET',
            )
            $('#training-modal .progress').progress({
                percent: Math.min(Number(run.progress) * 100, 99),
                autoSuccess: false,
            })
            $('#training-modal .label').text(
                run.state == 'cancelling' ? 'Stopping training...' : 'Training in progress...'
            )
            if(this.terminal_states.includes(run.state)){
                this.training_states[options.training_type] = run.state
                if(run.state == 'completed')
                    this.success_modal()
                else if(run.state == 'cancelled')
                    this.interrupted_modal()
                else {
                    const message = run.error?.message ?? run.result?.message ?? 'Training failed.'
                    this.fail_modal(message)
                    const diagnostic = run.error?.diagnostic_id
                    $('body').toast({
                        message: diagnostic ? `${message} Diagnostic ID: ${diagnostic}` : message,
                        class: 'error',
                        displayTime: 0,
                        closeIcon: true,
                    })
                }
                this.active_run_id = undefined
                return run
            }
            await sleep(300)
        }
    }

    static show_modal(){
        super.show_modal()
        $('#training-modal #cancel-training-button')
            .prop('disabled', false)
            .attr('aria-disabled', 'false')
            .removeClass('disabled loading')
            .show()
        $('#training-modal #retry-training-button, #training-modal #close-training-button').hide()
    }

    static interrupted_modal(){
        const $progress = $('#training-modal .ui.progress')
        $progress.removeClass('active success').addClass('error')
        $progress.find('.label').text('Training interrupted. You can retry with the same settings.')
        $('#training-modal #cancel-training-button').hide()
        $('#training-modal #retry-training-button, #training-modal #close-training-button').show()
        $('#training-modal').modal({closable:true})
    }

    static fail_modal(message){
        const $progress = $('#training-modal .ui.progress')
        $progress.removeClass('active success').addClass('error')
        $progress.find('.label').text(
            message || 'Training failed. Review the console details, then retry.'
        )
        $('#training-modal #cancel-training-button').hide()
        $('#training-modal #retry-training-button, #training-modal #close-training-button').show()
        $('#training-modal').modal({closable:true})
    }

    static success_modal(){
        const $progress = $('#training-modal .ui.progress')
        $progress.progress({percent:100, autoSuccess:false})
            .removeClass('active error').addClass('success')
        $progress.find('.label').text('Training finished')
        $('#training-modal #cancel-training-button, #training-modal #retry-training-button').hide()
        $('#training-modal #close-training-button').show()
        $('#training-modal').modal({closable:true})
    }

    static on_retry_training(){
        $('#training-modal').modal('hide')
        return this.on_start_training()
    }

    static async upload_training_data(filenames){
        for(const filename of filenames){
            await RootsFileInput.ensure_uploaded(GLOBAL.files[filename])
            await RootsFileInput.ensure_uploaded(this.imported_labels.get(filename))
        }
    }

    //override
    static update_model_info(){
        const model_type  = $('#training-model-type').dropdown('get value');
        if(!model_type)
            return;
        
        super.update_model_info(model_type)
        const state = this.training_states[model_type]
        if(state == 'cancelled' || state == 'failed' || state == 'running'){
            $('#training-new-modelname-field').hide()
            if(GLOBAL.settings.active_models[model_type] == '')
                $('#training-model-info-label').text(
                    state == 'cancelled'
                        ? '[INTERRUPTED - NOT SAVABLE]'
                        : '[INCOMPLETE - NOT SAVABLE]'
                )
        }
    }

    static update_number_of_training_files_info(){
        const n = this.get_selected_files().length;
        $('#training-number-of-files-info-label').text(n)
        $('#training-label-file-list').text(
            n ? this.get_selected_files().join(', ') : 'No annotations imported yet.'
        )
        $('#training-number-of-files-info-message').removeClass('hidden')
        const confirmed = $('#training-reviewed-labels-checkbox').is(':checked')
        $('#start-training-button')
            .prop('disabled', n == 0 || !confirmed)
            .attr('aria-disabled', String(n == 0 || !confirmed))
    }

    static async on_cancel_training(){
        const $button = $('#training-modal #cancel-training-button')
            .prop('disabled', true)
            .attr('aria-disabled', 'true')
            .addClass('disabled loading')
        $('#training-modal .label').text('Stopping training safely...')
        try {
            if(this.active_run_id)
                await RootSecurity.request(
                    `/api/training/runs/${this.active_run_id}/cancel`,
                    'POST',
                )
            else
                await RootSecurity.request('/stop_training', 'POST')
        } catch(error) {
            $button
                .prop('disabled', false)
                .attr('aria-disabled', 'false')
                .removeClass('disabled loading')
            $('body').toast({message:'Stopping failed.', class:'error'})
        }
        return false
    }

    static on_save_model(){
        const new_modelname = $('#training-new-modelname')[0].value
        RootSecurity.request('/save_model', 'POST', {
            newname: new_modelname,
            options: this.get_training_options(),
        })
            .done(_ => $('#training-new-modelname-field').hide())
            .fail(_ => $('body').toast({message:'Saving failed.', class:'error', displayTime:0, closeIcon:true}))
        $('#training-new-modelname')[0].value = ''
    }
}
