
global = {
  input_files : {},      //{"banana.JPG": FILE}
  metadata    : {},

  cancel_requested : false,
  skeletonize      : false,   //whether to show normal or skeletonized segmentations

  settings    : {}
};


const FILE = {name: '',
              file: undefined,    //javascript file object
              processed: false,
              mask: undefined,    //javascript file object (optional)
};

deepcopy = function(x){return JSON.parse(JSON.stringify(x))};


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

//sends a file to the flask server
function upload_file(file){
  var formData = new FormData();
  formData.append('files', file );
  result = $.ajax({
      url: 'file_upload',      type: 'POST',
      data: formData,          async: false,
      cache: false,            contentType: false,
      enctype: 'multipart/form-data',
      processData: false,
  }).done(function (response) { create_filelist_item_content(file.name); });
  return result;
}

//creates the ui item in the accodion list (that shows the input image and segmentation mask)
function create_filelist_item_content(filename){
  target  = $(`td.content[filename="${filename}"]`);
  if(target.html().trim().length>0)
    //only do this once
    return;

  target.html('');
  content = $("#filelist-item-content-template").tmpl([{filename:filename}]);
  content.appendTo(target);
  content.find('.ui.dimmer').dimmer({'closable':false}).dimmer('show');
}

//sends an image and mark it as an exclusion mask
function upload_mask(file){
  var formData = new FormData();
  formData.append('files', file );
  formData.append('filename', 'mask_'+file.name );
  result = $.ajax({
      url: 'file_upload',      type: 'POST',
      data: formData,          async: false,
      cache: false,            contentType: false,
      enctype: 'multipart/form-data',
      processData: false,
  });
  return result;
}



function sortObjectByValue(o) {
    return Object.keys(o).sort(function(a,b){return o[b]-o[a]}).reduce((r, k) => (r[k] = o[k], r), {});
}



//send an image to flask and request to process it
function process_file(filename){
  $process_button = $(`.ui.primary.button[filename="${filename}"]`);
  $process_button.html(`<div class="ui active tiny inline loader"></div> Processing...`);


  function progress_polling(){
    $.get(`/processing_progress/${filename}`, function(data) {
        //console.log(filename, data);
        $process_button = $(`.ui.primary.button[filename="${filename}"]`);
        $process_button.html(`<div class="ui active tiny inline loader"></div> Processing...${Math.round(data*100)}%`);
        if(!global.input_files[filename].processed)
          setTimeout(progress_polling,1000);
    });
  }
  setTimeout(progress_polling,1000);



  upload_file(global.input_files[filename].file);
  if(!!global.input_files[filename].mask)
    upload_mask(global.input_files[filename].mask);
  
  //send a processing request to python update gui with the results
  return $.get(`/process_image/${filename}`).done(function(data){
      global.input_files[filename].processed=true;
      
      var url = src_url_for_segmented_image(filename);
      $(`[filename="${filename}"]`).find('img.segmented').attr('src', url);
      $(`[id="dimmer_${filename}"]`).dimmer('hide');


      //add
      $(`.ui.title[filename="${filename}"]`).find('label').wrap($('<b>'))
      delete_image(filename);
    });
}

//send command to delete a file from the server's temporary folder (to not waste space)
function delete_image(filename){
  $.get(`/delete_image/${filename}`);
}


//called when user clicks on a file table row to open it
function on_accordion_open(x){
  target     = this;
  contentdiv = this.find('.content');
  if(contentdiv[0].innerHTML.trim())
    return;
  filename   = contentdiv.attr('filename');
  file       = global.input_files[filename].file;
  upload_file(file);

  //document.getElementById(`image_${filename}`).onload = function(){magnify(`image_${filename}`)};
}

//called when user clicks the 'Process' button
function on_process_image(e){
  filename = e.target.attributes['filename'].value;
  process_file(filename);
}

//called when user clicks the 'Process all' button
function process_all(){
  $button = $('#process-all-button')

  j=0;
  async function loop_body(){
    if(j>=Object.values(global.input_files).length || global.cancel_requested ){
      $button.html('<i class="play icon"></i>Process All Images');
      $('#cancel-processing-button').hide();
      return;
    }
    $('#cancel-processing-button').show();
    $button.html(`Processing... ${j}/${Object.values(global.input_files).length}`);

    f = Object.values(global.input_files)[j];
    if(!f.processed)
      await process_file(f.name);

    j+=1;
    setTimeout(loop_body, 1);
  }
  global.cancel_requested = false;
  setTimeout(loop_body, 1);  //using timeout to refresh the html between iterations
}

//called when user clicks the 'Cancel Processing' button
function cancel_processing(){
  global.cancel_requested = true;
}




function downloadURI(uri, name) 
{
    var link = document.createElement("a");
    // If you don't know the name or want to use
    // the webserver default set name = ''
    link.setAttribute('download', name);
    link.href = uri;
    document.body.appendChild(link);
    link.click();
    link.remove();
}

//called when user clicks on the download button; downloads all segmented images
async function on_download_processed(){
  if(Object.keys(global.input_files).length==0){
    $('#download-processed-button').popup({on       : 'manual',
                                     position : 'bottom right',
                                     delay    : {'show':0, 'hide':0}, duration:0,
                                     content  : 'Nothing to download'}).popup('show');
    return;
  }

  for(f in global.input_files){
    if(global.input_files[f].processed){
      processed_f = $(`[filename="${f}"]`).find('img.segmented').attr('src');
      downloadURI(processed_f, '');
      //sleep for a few milliseconds because chrome does not allow more than 10 simulataneous downloads
      await new Promise(resolve => setTimeout(resolve, 250));
    }
  }
}







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
    var url = src_url_for_segmented_image(fname);
    $(`[filename="${fname}"]`).find('img.segmented').attr('src', url);
  }
}


function save_settings(_){
  var active_model = $("#settings-active-model").dropdown('get value');
  $.post(`/settings?active_model=${active_model}`).done(load_settings);

  var skeletonize  = $("#settings-skeletonize").checkbox('is checked');
  set_skeletonized(skeletonize);
}

//called when the settings button is clicked
function on_settings(){
  $('#settings-dialog').modal({onApprove: save_settings}).modal('show');
  $("#settings-active-model").dropdown('hide')
}

function load_settings(){
  $.get('/settings').done(function(data){
    global.settings = data;
    console.log(global.settings);

    models_list = []
    for(modelname of global.settings.models)
      models_list.push({name:modelname, value:modelname, selected:(modelname==global.settings.active_model)})
    $("#settings-active-model").dropdown({values: models_list, showOnFocus:false })
  })
}






filebasename = (filename) => filename.split('.').slice(0, -1).join('.');

//called when user selected exclusion masks (in the 'File' menu)
function on_inputmasks_select(input){
  console.log(input);
  for(maskfile of input.target.files){
    //var maskfile     = input.target.files[i];
    var maskbasename = filebasename(maskfile.name);

    for(inputfile of Object.values(global.input_files)){
      if(filebasename(inputfile.name) == maskbasename){
        console.log('Matched mask for input file ',inputfile.name);

        //indicate in the file table that a mask is available with a red plus icon
        var $tablerow = $(`.ui.title[filename="${inputfile.name}"]`)
        $tablerow.find('.has-mask-indicator').show();
        $tablerow.find('.image.icon').addClass('outline');

        inputfile.mask = maskfile;
      }
    }
  }
}

//
