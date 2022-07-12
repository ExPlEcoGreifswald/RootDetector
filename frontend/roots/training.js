

RootsTraining = class extends BaseTraining {
    
    //dummy override: all files selected  //TODO: move upstream
    static get_selected_files(){
        const files_with_results = Object.values(GLOBAL.files).filter( x => !!x.results )
        return files_with_results.map( x => x.name)
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

    //override
    static update_model_info(){
        const model_type  = $('#training-model-type').dropdown('get value');
        if(!model_type)
            return;
        
        super.update_model_info(model_type)
    }
}

