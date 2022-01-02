//called when user clicks on save in the settings dialog
function save_settings(_){
    global.settings.active_model = $("#settings-active-model").dropdown('get value');
    global.settings.exmask_model = $("#settings-exclusionmask-model").dropdown('get value');

    $('#settings-ok-button').addClass('loading');
    var data = JSON.stringify({
        active_model: global.settings.active_model,
        exmask_model: global.settings.exmask_model,
        exmask_enabled: global.settings.exmask_enabled,
    });
    $.post(`/settings`, data,).done((x)=>{
        $('#settings-dialog').modal('hide');
        $('#settings-ok-button').removeClass('loading');
        console.log('Settings:',x)
    });
  
    var skeletonize  = $("#settings-skeletonize").checkbox('is checked');
    set_skeletonized(skeletonize);
    //set_training_mode($('#settings-enable-retraining').checkbox('is checked'));

    //do not close the dialog, doing this manually
    return false;
}
  
//called when the settings button is clicked
function on_settings(){
    load_settings();
    $('#settings-dialog').modal({onApprove: save_settings}).modal('show');
}


function load_settings(){
    $('#settings-exclusionmask-enable').checkbox({onChange: on_exmask_checkbox});

    $.get('/settings').done(function(settings){
        console.log('Loaded settings: ',settings)
        global.settings.active_model = settings.active_model
        global.settings.exmask_model = settings.exmask_active_model

        var models_list = []
        for(var modelname of settings.models)
            models_list.push({name:modelname, value:modelname, selected:(modelname==global.settings.active_model)})
        if(settings.active_model=='')
            models_list.push({name:'[UNSAVED MODEL]', value:'', selected:true})
        $("#settings-active-model").dropdown({values: models_list, showOnFocus:false })

        $('#settings-exclusionmask-enable').checkbox(settings.exmask_enabled? 'check' : 'uncheck');
        var exmaskmodels_list = []
        for(var name of settings.exmask_models)
            exmaskmodels_list.push({name:name, value:name, selected:(name==global.settings.exmask_model)})
        $("#settings-exclusionmask-model").dropdown({values: exmaskmodels_list, showOnFocus:false })

        var $new_name_elements = $("#settings-new-modelname-field");
        (settings.active_model=='')? $new_name_elements.show(): $new_name_elements.hide();
    })
}


function set_training_mode(x){
    if(x){
      global.active_mode = 'training';
      $('#process-all-button').hide();
      $('.process-single-image').hide();  //the play buttons on the individual images
      $('#retrain-button').show();
    } else {
      global.active_mode = 'inference';
      $('#process-all-button').show();
      $('.process-single-image').show();
      $('#retrain-button').hide();
    }
  }

//called when user clicks on the save button in settings to save a retrained model
function on_save_model(){
    var newname = $('#settings-new-modelname')[0].value
    if(newname.length==0){
      console.log('Name too short!')
      return;
    }
    $.get('/save_model', {newname:newname}).done(load_settings);
}



function on_exmask_checkbox(){
    var enabled = $('#settings-exclusionmask-enable').checkbox('is checked');
    global.settings.exmask_enabled = enabled;
    if(enabled){
        $("#settings-exclusionmask-model-field").show()
    } else {
        $("#settings-exclusionmask-model-field").hide()
    }
}
