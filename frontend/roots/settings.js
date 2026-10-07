

RootsSettings = class extends BaseSettings{

    static settings_keydown_handler = undefined

    static on_settings(){
        super.on_settings()
        const $dialog = $('#settings-dialog')
        const dialog = $dialog[0]
        if(this.settings_keydown_handler)
            dialog.removeEventListener('keydown', this.settings_keydown_handler, true)
        this.settings_keydown_handler = event => {
            if(event.key != 'Tab')
                return
            const selector = [
                'button:not([disabled])',
                'input:not([type="hidden"]):not([disabled])',
                '.ui.dropdown[tabindex]:not(.disabled)',
                '[tabindex]:not([tabindex="-1"])',
            ].join(',')
            const focusable = [...new Set($dialog.find(selector).filter(':visible').get())]
            if(!focusable.length)
                return
            const current = focusable.indexOf(document.activeElement)
            const direction = event.shiftKey ? -1 : 1
            const next = current < 0
                ? 0
                : (current + direction + focusable.length) % focusable.length
            event.preventDefault()
            event.stopPropagation()
            focusable[next].focus()
        }
        dialog.addEventListener('keydown', this.settings_keydown_handler, true)
        setTimeout(() => $dialog.find('button.close')[0]?.focus(), 0)
    }

    //override
    static async load_settings(){
        const data = await super.load_settings();

        this.update_gpu_info(data);
    }

    //override
    static update_settings_modal(models){
        super.update_settings_modal(models)

        const settings = GLOBAL.settings;
        $('#settings-exclusionmask-enable')
            .checkbox({onChange: _ => this.on_exmask_checkbox()})
            .checkbox(settings.exmask_enabled? 'check' : 'uncheck');
        $('#settings-too-many-roots-input')[0].value = settings.too_many_roots;
        if(models['exclusion_mask'])
            this.update_model_selection_dropdown(
                models['exclusion_mask'], settings.active_models['exclusion_mask'], $("#settings-exclusionmask-model")
            )
        if(models['tracking'])
            this.update_model_selection_dropdown(
                models['tracking'], settings.active_models['tracking'], $("#settings-tracking-model")
            )
    }


    //override
    static apply_settings_from_modal(){
        GLOBAL.settings.active_models['detection']      = $("#settings-active-model").dropdown('get value');
        GLOBAL.settings.active_models['exclusion_mask'] = $("#settings-exclusionmask-model").dropdown('get value');
        GLOBAL.settings.active_models['tracking']       = $("#settings-tracking-model").dropdown('get value');

        GLOBAL.settings.use_gpu
            = $('#settings-gpu-enable').checkbox('is checked')
        GLOBAL.settings.too_many_roots
            = Number($("#settings-too-many-roots-input")[0].value);
    }

    static on_exmask_checkbox(){
        var enabled = $('#settings-exclusionmask-enable').checkbox('is checked');
        GLOBAL.settings.exmask_enabled = enabled;
        $("#settings-exclusionmask-model-field").toggle(enabled)
    }

    static update_gpu_info(data){
        if(data['available_gpu']){
            $('#settings-no-gpu-warning').hide()
            $('#settings-gpu-available-box').show()
            $('#settings-gpu-name').text(data['available_gpu'])
        } else {
            $('#settings-no-gpu-warning').show()                        //maybe just hide the whole gpu field?
            $('#settings-gpu-available-box').hide()
        }
        console.log(data.settings)
        $('#settings-gpu-enable').checkbox(!!data.settings['use_gpu']? 'check' : 'uncheck')
    }
}
