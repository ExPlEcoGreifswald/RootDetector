const SETTINGS = {
  active_model : '',         //root segmentation model
  exmask_model : '',         //exclusion mask model
  exmask_enabled : false,
}



global = {
  input_files      : {},      //{"banana.JPG": FILE}
  metadata         : {},

  settings         : deepcopy(SETTINGS),  //settings that are saved to file (but also some more)
  active_mode      : 'inference',         //inference or training
};



const FILE = {
  name:          '',
  file:          undefined,    //javascript file object
  processed:     false,
  mask:          undefined,    //javascript file object (optional)
  training_mask: undefined,    //javascript file object (optional)
  statistics:    undefined,    //dict e.g: {"sum":9999, ...}
  detection_results: {},       //dict e.g. {statistics:{}, segmentation:"XX.png", skeleton:"XX.png"}
  tracking_results : {},       //dict e.g: {'right-image.jpg':data}
};








function init(){
  load_settings();
  setup_sse();
}


//set global.input_files and update ui
function set_input_files(files){
  if(files.length==0)
    return;
  global.input_files = {};
  global.metadata    = {};
  for(var f of files)
    global.input_files[f.name] = Object.assign({}, deepcopy(FILE), {name: f.name, file: f});
  
  RootDetection.update_inputfiles_list();
  RootTracking.set_input_files(files);
}

//called when user selects one or multiple input files
function on_inputfiles_select(input){
  set_input_files(input.target.files);
}

//called when user selects a folder with input files
function on_inputfolder_select(input){
  var files = [];
  for(var f of input.files)
    if(f.type.startsWith('image'))
        files.push(f);
  set_input_files(files);
}



//called when user clicks the 'Process all' button
function process_all(){
  var $button = $('#process-all-button')

  let cancel_requested = false;
  $('#cancel-button').on('click', ()=>{cancel_requested = true;})

  var j=0;
  async function loop_body(){
    if(j>=Object.values(global.input_files).length || cancel_requested ){
      $button.html('<i class="play icon"></i>Process All Images');
      $('#cancel-button').hide();
      return;
    }
    $('#cancel-button').show();
    $button.html(`Processing... ${j}/${Object.values(global.input_files).length}`);

    f = Object.values(global.input_files)[j];
    //if(!f.processed)  //re-processing anyway, the model may have been retrained
      await RootDetection.process_file(f.name);

    j+=1;
    setTimeout(loop_body, 1);
  }
  setTimeout(loop_body, 1);  //using timeout to refresh the html between iterations
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
  for(var maskfile of input.target.files){
    var maskbasename = filebasename(maskfile.name);

    for(inputfile of Object.values(global.input_files)){
      if( wildcard_test(maskbasename, filebasename(inputfile.name)) ){
        console.log('Matched mask for input file ',inputfile.name);

        //indicate in the file table that a mask is available with a red plus icon
        var $tablerow = $(`.ui.title[filename="${inputfile.name}"]`)
        $tablerow.find('.has-mask-indicator').show();

        //set file as not processed and show the dimmer again to hide previous results
        set_processed(inputfile.name, false);
        $(`[id="dimmer_${inputfile.name}"]`).dimmer('show');

        var new_name   = `mask_${filebasename(inputfile.name)}.png`
        inputfile.mask = rename_file(maskfile, new_name)
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


//set up server-side events
function setup_sse(){
  global.event_source = new EventSource('/stream');
  //global.event_source.onmessage = (msg => console.log('>>',msg));
  global.event_source.onerror   = (x) => console.error('SSE Error', x);
}

