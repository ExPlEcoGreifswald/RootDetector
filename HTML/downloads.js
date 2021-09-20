


function downloadURI(uri, name) {
    var link = document.createElement("a");
    // If you don't know the name or want to use
    // the webserver default set name = ''
    link.setAttribute('download', name);
    link.href = uri;
    document.body.appendChild(link);
    link.click();
    link.remove();
}

//download a text file with context `text`
function download_text(filename, text) {
    var element = document.createElement('a');
    element.setAttribute('href', 'data:text/plain;charset=utf-8,' + encodeURIComponent(text));
    element.setAttribute('download', filename);
    element.style.display = 'none';
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
}


//called when user clicks on the "download segmented images" button
async function on_download_processed(){
  if(Object.keys(global.input_files).length==0){
    show_nothing_to_download_popup('#download-processed-button');
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
