

RootsSettings = class extends BaseSettings{

    //override
    static update_settings_modal(models){
        $('#settings-exclusionmask-enable').checkbox({onChange: _ => this.on_exmask_checkbox()});

        const settings = GLOBAL.settings;
        
        var models_list = []
        for(var modelname of models.detection)
            models_list.push({name:modelname, value:modelname, selected:(modelname==settings.active_models.detection)})
        if(settings.active_models.detection=='')
            models_list.push({name:'[UNSAVED MODEL]', value:'', selected:true})
        $("#settings-active-model").dropdown({values: models_list, showOnFocus:false })


        $('#settings-exclusionmask-enable').checkbox(settings.exmask_enabled? 'check' : 'uncheck');
        var exmaskmodels_list = []
        for(var name of models.exclusion_mask)
            exmaskmodels_list.push({name:name, value:name, selected:(name==settings.active_models.exclusion_mask)})
        $("#settings-exclusionmask-model").dropdown({values: exmaskmodels_list, showOnFocus:false })

        var trackingmodels_list = []
        for(var name of models.tracking)
            trackingmodels_list.push({name:name, value:name, selected:(name==settings.active_models.tracking)})
        $("#settings-tracking-model").dropdown({values: trackingmodels_list, showOnFocus:false })
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