function save_settings(_){
    var active_model = $("#settings-active-model").dropdown('get value');
    $.post(`/settings?active_model=${active_model}`).done(load_settings);
  
    var skeletonize  = $("#settings-skeletonize").checkbox('is checked');
    set_skeletonized(skeletonize);
    set_training_mode($('#settings-enable-retraining').checkbox('is checked'));
}
  
//called when the settings button is clicked
function on_settings(){
    load_settings();
    $('#settings-dialog').modal({onApprove: save_settings}).modal('show');
}


function load_settings(){
    $.get('/settings').done(function(settings){
        global.settings.models       = settings.models;
        global.settings.active_model = settings.active_model;
        console.log(global.settings);

        models_list = []
        for(modelname of global.settings.models)
            models_list.push({name:modelname, value:modelname, selected:(modelname==global.settings.active_model)})
        if(settings.active_model=='')
            models_list.push({name:'[UNSAVED MODEL]', value:'', selected:true})
        $("#settings-active-model").dropdown({values: models_list, showOnFocus:false })

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