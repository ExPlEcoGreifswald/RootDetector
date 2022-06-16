

RootsSettings = class extends BaseSettings{

    //override
    static update_settings_modal(models){
        super.update_settings_modal(models)

        const settings = GLOBAL.settings;
        $('#settings-exclusionmask-enable')
            .checkbox({onChange: _ => this.on_exmask_checkbox()})
            .checkbox(settings.exmask_enabled? 'check' : 'uncheck');
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
    }

    static on_exmask_checkbox(){
        var enabled = $('#settings-exclusionmask-enable').checkbox('is checked');
        GLOBAL.settings.exmask_enabled = enabled;
        $("#settings-exclusionmask-model-field").toggle(enabled)
    }

}