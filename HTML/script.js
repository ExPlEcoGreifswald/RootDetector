const SETTINGS = {
  active_model : '',         //root segmentation model
  exmask_model : '',         //exclusion mask model
  exmask_enabled : false,
}



global = {
  input_files      : {},      //{"banana.JPG": FILE}
  metadata         : {},

  cancel_requested : false,   //user requested cancelling either inference or training
  skeletonize      : false,   //whether to show normal or skeletonized segmentations

  settings         : deepcopy(SETTINGS),  //settings that are saved to file (but also some more)
  active_mode      : 'inference',         //inference or training
};



const FILE = {name:          '',
              file:          undefined,    //javascript file object
              processed:     false,
              mask:          undefined,    //javascript file object (optional)
              training_mask: undefined,    //javascript file object (optional)
              statistics:    undefined,    //dict e.g: {"sum":9999, ...}
              tracking_results : {},       //dict e.g: {'right-image.jpg':data}
};








function init(){
  load_settings();
}


//update the accordion file list/table
function update_inputfiles_list(){
  $filestable = $('#filetable');
  $filestable.find('tbody').html('');
  for(f of Object.values(global.input_files)){
      $("#filetable-item-template").tmpl([{filename:f.name}]).appendTo($filestable.find('tbody'));
  }
}

//set global.input_files and update ui
function set_input_files(files){
  global.input_files = {};
  global.metadata    = {};
  for(f of files)
    global.input_files[f.name] = Object.assign({}, deepcopy(FILE), {name: f.name, file: f});
  update_inputfiles_list();

  for(f of files){
      EXIF.getData(f, function() {
        global.input_files[this.name].datetime = EXIF.getTag(this, "DateTime");
    });
  }

  RootTracking.set_input_files(files);
}

//called when user selects one or multiple input files
function on_inputfiles_select(input){
  set_input_files(input.target.files);
}

//called when user selects a folder with input files
function on_inputfolder_select(input){
  files = [];
  for(f of input.files)
    if(f.type.startsWith('image'))
        files.push(f);
  set_input_files(files);
}

//sends an image and mark it as an exclusion mask
function upload_mask(inputfilename){
  var maskfile = global.input_files[inputfilename].mask;
  var formData = new FormData();
  formData.append('files', maskfile );
  formData.append('filename', `mask_${filebasename(inputfilename)}.png` );
  result = $.ajax({
      url: 'file_upload',      type: 'POST',
      data: formData,          async: false,
      cache: false,            contentType: false,
      enctype: 'multipart/form-data',
      processData: false,
  });
  return result;
}




//send an image to flask and request to process it
function process_file(filename){
  $(`[id="dimmer_${filename}"]`).dimmer('show');
  $process_button = $(`.ui.primary.button[filename="${filename}"]`);
  $process_button.html(`<div class="ui active tiny inline loader"></div> Processing...`);
  set_processed(filename, false);

  function progress_polling(){
    $.get(`/processing_progress/${filename}`, function(data) {
        if(!global.input_files[filename].processed){
          $process_button = $(`.ui.primary.button[filename="${filename}"]`);
          $process_button.html(`<div class="ui active tiny inline loader"></div> Processing...${Math.round(data*100)}%`);
          setTimeout(progress_polling,1000);
        }
    });
  }
  setTimeout(progress_polling,1000);



  upload_file_to_flask('/file_upload', global.input_files[filename].file);
  if(!!global.input_files[filename].mask)
    upload_mask(filename);
  
  //send a processing request to python update gui with the results
  return $.get(`/process_image/${filename}`).done(function(data){
      set_processed(filename, true);
      global.input_files[filename].statistics = data.statistics;
      
      var url = src_url_for_segmented_image(filename);
      $(`[filename="${filename}"]`).find('img.segmented').attr('src', url);
      $(`[id="dimmer_${filename}"]`).dimmer('hide');
      $process_button.html(`Process Image`);

      delete_image(filename);
    });
}

//send command to delete a file from the server's temporary folder (to not waste space)
function delete_image(filename){
  $.get(`/delete_image/${filename}`);
}


//called when user clicks on a file table row to open it
function on_accordion_open(x){
  var contentdiv = this.find('.content');
  var imgelement = contentdiv.find('.input-image');
  var content_already_loaded = !!imgelement.attr('src')
  if(content_already_loaded)
    return;
  //load full image
  var filename   = contentdiv.attr('filename');
  var file       = global.input_files[filename].file;
  upload_file_to_flask('/file_upload',file).done(()=>{
    imgelement.attr('src', `/images/${filename}.jpg`);
    imgelement.on('load', ()=>{delete_image(filename);})
    if(!global.input_files[filename].processed)
      contentdiv.find('.ui.dimmer').dimmer({'closable':false}).dimmer('show');
  });
}

//called when user clicks the (single image) 'Process' button
function on_process_image(e){
  var filename = $(e.target).closest('[filename]').attr('filename');
  process_file(filename);
}

//called when user clicks the 'Process all' button
function process_all(){
  $button = $('#process-all-button')

  j=0;
  async function loop_body(){
    if(j>=Object.values(global.input_files).length || global.cancel_requested ){
      $button.html('<i class="play icon"></i>Process All Images');
      $('#cancel-button').hide();
      return;
    }
    $('#cancel-button').show();
    $button.html(`Processing... ${j}/${Object.values(global.input_files).length}`);

    f = Object.values(global.input_files)[j];
    //if(!f.processed)  //re-processing anyway, the model may have been retrained
      await process_file(f.name);

    j+=1;
    setTimeout(loop_body, 1);
  }
  global.cancel_requested = false;
  setTimeout(loop_body, 1);  //using timeout to refresh the html between iterations
}

//called when user clicks the 'Cancel' button
function on_cancel(){
  global.cancel_requested = true;
  if(global.active_mode=='training'){
    $.get('/stop_training');
    $('#cancel-button').html('<div class="ui active tiny inline loader"></div>Cancelling...');
  }
}









//returns the correct url for the segmented <img>, depending on whether global.skeletonize is set
function src_url_for_segmented_image(filename){
  if(!global.input_files[filename].processed)
    return "";
  else if(global.skeletonize)
    return `/images/skeletonized_${filename}.png?=${new Date().getTime()}`
  else
    return `/images/segmented_${filename}.png?=${new Date().getTime()}`
}

function set_skeletonized(x){
  global.skeletonize = !!x;
  for(var fname in global.input_files){
    var img_element = $(`[filename="${fname}"]`).find('img.segmented');
    if(!!img_element.attr('src') && !img_element.attr('src').startsWith('blob')){
      var url         = src_url_for_segmented_image(fname);
      img_element.attr('src', url);
    }
  }
}



function wildcard_test(wildcard_pattern, str) {
  //string comparison with wildcard characters * and ~
  //https://stackoverflow.com/questions/26246601/wildcard-string-comparison-in-javascript
  let w = wildcard_pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&'); // regexp escape 
      w = w.replace(/~/g,'*');                                   //allow ~ as wildcard (for windows paths)
  const re = new RegExp(`^${w.replace(/\*/g,'.*').replace(/\?/g,'.')}$`,'i');
  return re.test(str); // remove last 'i' above to have case sensitive
}


//called when user selected exclusion masks (in the 'File' menu)
function on_inputmasks_select(input){
  console.log(input);
  for(maskfile of input.target.files){
    //var maskfile     = input.target.files[i];
    var maskbasename = filebasename(maskfile.name);

    for(inputfile of Object.values(global.input_files)){
      //if(filebasename(inputfile.name) == maskbasename){
      if( wildcard_test(maskbasename, filebasename(inputfile.name)) ){
        console.log('Matched mask for input file ',inputfile.name);

        //indicate in the file table that a mask is available with a red plus icon
        var $tablerow = $(`.ui.title[filename="${inputfile.name}"]`)
        $tablerow.find('.has-mask-indicator').show();

        //set file as not processed and show the dimmer again to hide previous results
        set_processed(inputfile.name, false);
        $(`[id="dimmer_${inputfile.name}"]`).dimmer('show');

        inputfile.mask = maskfile;
      }
    }
  }
}

//sets the global.input_files[x].processed variable and updates icons accordingly
function set_processed(filename, value){
  var $tablerow = $(`.ui.title[filename="${filename}"]`);
  var $icon     = $tablerow.find('.image.icon');
  var $label    = $tablerow.find('label');

  //remove the <b> tag around the label if needed
  if($label.parent().prop('tagName') == 'B')
    $label.unwrap();

  if(!value){
    $icon.attr('class', 'image outline icon');
    $icon.attr('title', 'File not yet processed');
  }
  else if(value=='training_mask'){
    $icon.attr('class', 'image violet icon');
    $icon.attr('title', 'Training mask loaded');
    $label.wrap($('<b>'));
  }
  else if(!!value){
    $icon.attr('class', 'image icon');
    $icon.attr('title', 'File processed');
    $label.wrap($('<b>'))
  }
  global.input_files[filename].processed = !!value;
}


