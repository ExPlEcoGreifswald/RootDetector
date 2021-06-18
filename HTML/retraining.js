function load_training_mask(maskfile, jpgfile){
    var url = URL.createObjectURL(maskfile);
    $(`[filename="${jpgfile}"]`).find('img.segmented').attr('src', url);
    $(`[id="dimmer_${jpgfile}"]`).dimmer('hide');
    set_processed(inputfile.name, 'training_mask')
    global.input_files[inputfile.name].training_mask = maskfile;
}


//called when user selected Training Masks files (in the 'File' menu)
function on_trainingmasks_select(input){
    console.log(input.target.files);
    for(maskfile of input.target.files){
      var basename = filebasename(maskfile.name);
      for(inputfile of Object.values(global.input_files)){
        if(filebasename(inputfile.name) == basename){
          console.log('Matched mask for input file ',inputfile.name);
          load_training_mask(maskfile, inputfile.name);
        }
      }
    }
}


//called when user clicks on the 'Retrain' button
async function on_retrain(){
  //collect files with predictions
  var files = Object.values(global.input_files).filter(x => (x.training_mask!=undefined) );
  if(files.length==0)
    return;  //TODO: show message that no files for training are available
  
  console.log(`Training with ${files.length} files`);
  var $retrain_button = $(`#retrain-button`);
  $retrain_button.html(`<div class="ui active tiny inline loader"></div> Retraining...`);

  //upload input and training mask images
  for(var f of files){
    await upload_file_to_flask('/file_upload', f.file);
    await upload_file_to_flask('/file_upload', f.training_mask);
  }

  var filenames = files.map(x => x.name);
  $.post('/start_training', {'filenames':filenames}).done(()=>{
    //after training is finished restore the buttons to the original state
    $retrain_button.html('<i class="redo alternate icon"></i>Retrain');
    $('#cancel-button').hide();
    $('#cancel-button').html('<i class="x icon"></i>Cancel');
  }).fail( () => {console.log("Retraining request failed");} );

  $('#cancel-button').show();
  global.cancel_requested = false;
  setTimeout(monitor_training_progress,1000);  //timeout against raceconditions //FIXME: ugly ugly
}



function monitor_training_progress(){
  var $retrain_button = $(`#retrain-button`);
  $.ajax('/retraining_progress', { xhrFields: { onprogress: function(e){
            var last_progress = e.currentTarget.response.split(')').reverse()[1].split('(')[1];
            $retrain_button.html(`<div class="ui active tiny inline loader"></div> Retraining...${Math.round(last_progress*100)}%`);
          }
      }
  }).done(function(data)  {
      
  });
}