var RootDetection = new function() {

    //update the accordion file list/table
    this.update_inputfiles_list = function(){
        var $table = $('#filetable tbody');
            $table.find('tr').remove();
        for(var f of Object.values(global.input_files)){
            $("template#filetable-item-template").tmpl([{filename:f.name}]).appendTo($table);
        }
    }


    //called when user clicks on a file table row to open it
    this.on_accordion_open = function(){
        var $top        = this.closest('[filename]')
        var $imgelement = $top.find('img.input-image');
        var content_already_loaded = !!$imgelement.attr('src')
        if(content_already_loaded)
            return;
        
        //hide all content except the loading message to avoid jerking
        $top.find('div.content').hide()
        $top.find('.loading-message').show()
        
        //load full image
        var filename   = $top.attr('filename');
        var file       = global.input_files[filename].file;

        var $resultelement = $top.find('img.detection-result')
        $imgelement.on('load', function(){
            $top.find('div.content').show()
            $top.find('.loading-message').hide()

            var result_already_loaded = !!$resultelement.attr('src')
            if(result_already_loaded)
                return;
            $resultelement.attr('src', $imgelement.attr('src'));
            $resultelement.css('filter', 'contrast(0.0)')
        })
        set_imgsrc_from_file($imgelement, file);
    }

    //called when user clicks the (single image) 'Process' button
    this.on_process_image = function(event){
        var filename = $(event.target).closest('[filename]').attr('filename');
        RootDetection.process_file(filename);
    }


    //send an image to flask and request to process it
    this.process_file = function(filename){
        set_processed(filename, false);
        var $root          = $(`[filename="${filename}"]`)
        var $resultelement = $root.find('img.detection-result')
        $resultelement.parent().dimmer('show')  //TODO: refactor into set_processed()

        $(global.event_source).on('message', function(ev){
            var data = JSON.parse(ev.originalEvent.data);
            if(data.image!=filename)
                return;
            
            var prcnt = (data.progress*100).toFixed(0);
            var what  = (data.stage=='roots')? 'roots' : 'tape';
            $root.find('.dimmer p').text(`Detecting ${what} ... ${prcnt}%`)
        })
    
        upload_file_to_flask('/file_upload', global.input_files[filename].file);
        if(!!global.input_files[filename].mask)
            upload_file_to_flask('/file_upload', global.input_files[filename].mask)
        
        //send a processing request to python update gui with the results
        return $.get(`/process_image/${filename}`).done(function(result){
            set_processed(filename, true);
            global.input_files[filename].statistics = result.statistics;
            global.input_files[filename].detection_result = result;
            
            //TODO: refactor into set_processed()
            var url = url_for_image(result.segmentation);
            $resultelement.attr('src', url).on('load', ()=>$resultelement.css('filter', ''));
            
            var $chkbx = $root.find('.skeletonized-checkbox')
            $chkbx.removeClass('disabled').checkbox('set unchecked').checkbox({onChange:function(){
                var fname = $chkbx.checkbox('is checked')? result.skeleton : result.segmentation;
                $resultelement.attr('src', url_for_image(fname))
            }})
            
        }).always(function(){
            $resultelement.parent().dimmer('hide')
            delete_image(filename);
            if(!!global.input_files[filename].mask)
                delete_image(global.input_files[filename].mask.name)
        });
    }

}; //namespace RootDetection
