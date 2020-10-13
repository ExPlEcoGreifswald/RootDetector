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
function on_retrain(){
  //collect files with predictions
  var files = Object.values(global.input_files).filter(x => x.processed);
  if(files.length==0)
    return;  //TODO: show message that no files for training are available
  
  console.log(`Training with ${files.length} files`);

  //upload input and training mask images
  for(var f of files){
    upload_file_to_flask('/file_upload', f.file);
    upload_file_to_flask('/file_upload', f.training_mask);
  }

  var filenames = files.map(x => x.name);
  $.post('/start_training', {'filenames':filenames});
  $('#cancel-processing-button').show();
  global.cancel_requested = false;
}
