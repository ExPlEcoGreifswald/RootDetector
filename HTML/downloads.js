


//downloads an element from the uri (to the user hard drive)
function downloadURI(filename, uri) {
  var element = document.createElement('a');
  element.setAttribute('href', uri);
  element.setAttribute('download', filename);
  element.style.display = 'none';
  document.body.appendChild(element);
  element.click();
  document.body.removeChild(element);
}

function download_text(filename, text){
  return downloadURI(filename, 'data:text/plain;charset=utf-8,'+encodeURIComponent(text))
}

function download_blob(filename, blob){
  return downloadURI(filename, URL.createObjectURL(blob));
}

//fetch request that returns a blob
function fetch_as_blob(uri){
  return fetch(uri).then(r => r.ok? r.blob() : undefined);
}

//called when user clicks on the "download segmented images" button
async function on_download_processed(){
  if(Object.keys(global.input_files).length==0){
    show_nothing_to_download_popup('#download-processed-button');
    return;
  }

  var zipdata  = {};
  for(var filename in global.input_files){
    var f = global.input_files[filename];
    if(f.processed){
      var segmentation = fetch_as_blob(url_for_image(f.detection_result.segmentation))
      var skeleton     = fetch_as_blob(url_for_image(f.detection_result.skeleton))
      zipdata[`${filename}/${f.detection_result.segmentation}`] = segmentation
      zipdata[`${filename}/${f.detection_result.skeleton}`]     = skeleton
    }
  }

  var zip = new JSZip();
  for(var fname in zipdata){
    zip.file(fname, await zipdata[fname], {binary:true});
  }
  zip.generateAsync({type:"blob"}).then( blob => {
    download_blob( `segmented_images.zip`, blob  );
  } );
}


//called when user clicks on the "download statistics" button
function on_download_csv(){
    if(Object.keys(global.input_files).length==0){
        show_nothing_to_download_popup('#download-csv-button');
        return;
    }

    var csvtxt = 'Filename, '
               + '# root pixels, # background pixels, '
               + '# mask pixels, # skeleton pixels, '
               + '# skeleton pixels (<3px width), # skeleton pixels (3-7px width), # skeleton pixels (>7px width),'
               + '# orthogonal connections, # diagonal connections, '
               + 'Kimura length,'
               + ';\n';
    for(filename of Object.keys(global.input_files)){
        if(!global.input_files[filename].processed)
            continue;
        
        var stats = global.input_files[filename].statistics;
        csvtxt   += [
            filename,
            stats.sum,      stats.sum_negative,
            stats.sum_mask, stats.sum_skeleton, 
            stats.widths[0], stats.widths[1], stats.widths[2],
            stats.connections_orth, stats.connections_diag,
            stats.kimura_length,
        ].join(', ')+';\n'
    }

    if(!!csvtxt)
        download_text('statistics.csv', csvtxt)
}


function show_nothing_to_download_popup(id_string){
    $(id_string).popup({on       : 'manual',
                        position : 'bottom right',
                        delay    : {'show':0, 'hide':0}, duration:0,
                        content  : 'Nothing to download'}).popup('show');
}




//called when user clicks on the download button in a root tracking accordion item
async function on_download_tracking_single(event){
    var filename0 = $(event.target).closest('[filename0]').attr('filename0')
    var filename1 = $(event.target).closest('[filename1]').attr('filename1')
    var tracking_data = global.input_files[filename0].tracking_results[filename1];
    if(tracking_data==undefined)
      return;
    
    var zipdata  = {};
    zipdata[tracking_data.growthmap] = fetch_as_blob('/images/'+tracking_data.growthmap)
    var jsondata = {
      filename0 : filename0,
      filename1 : filename1,
      points0   : tracking_data.points0,
      points1   : tracking_data.points1,
    }
    zipdata[`${filename0}.${filename1}.json`] = JSON.stringify(jsondata);

    var zip = new JSZip();
    for(var fname in zipdata){
      zip.file(fname, await zipdata[fname], {binary:true});
    }
    zip.generateAsync({type:"blob"}).then( blob => {
      download_blob( `${filename0}.${filename1}.zip`, blob  );
    } );
}

