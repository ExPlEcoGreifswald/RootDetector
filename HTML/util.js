deepcopy = function(x){return JSON.parse(JSON.stringify(x))};
sleep    = function(ms) { return new Promise(resolve => setTimeout(resolve, ms));  } //XXX: await sleep(x)

//returns the name of a file without its ending
filebasename = (filename) => filename.split('.').slice(0, -1).join('.');

function sortObjectByValue(o) {
    return Object.keys(o).sort(function(a,b){return o[b]-o[a]}).reduce((r, k) => (r[k] = o[k], r), {});
}

function arange(x0,x1=undefined){
    var start = (x1==undefined)?  0 : x0;
    var stop  = (x1==undefined)? x0 : x1-start;
    return [...Array(stop).keys()].map(x=>x+start)
}

function argmin(x){
    return arange(x.length).reduce( (carry,i) => x[i]<x[carry]? i : carry );
}


function upload_file_to_flask(url, file){
    var formData = new FormData();
    formData.append('files', file);
    return $.ajax({
        url: url, type: 'POST',
        data: formData,
        processData: false, cache: false,
        contentType: false, async: false,
        enctype: 'multipart/form-data'
    });
}


function set_imgsrc_from_file($img, file){
    if(file.type=="image/tiff" || file.name.endsWith('.tif') || file.name.endsWith('.tiff')){
        var freader = new FileReader()
        freader.onload = function(event){
            var buffer = event.target.result
            var ifds   = UTIF.decode(buffer);
            UTIF.decodeImage(buffer, ifds[0], ifds)
            var rgba   = UTIF.toRGBA8(ifds[0]);
            var canvas = $(`<canvas width="${ifds[0].width}" height="${ifds[0].height}">`)[0]
            var ctx    = canvas.getContext('2d')
            ctx.putImageData(new ImageData(new Uint8ClampedArray(rgba.buffer),ifds[0].width,ifds[0].height),0,0);
            canvas.toBlob(blob =>  {
                $img.attr('src', URL.createObjectURL(blob)); 
            }, 'image/jpeg', 0.92 );
        }
        freader.readAsArrayBuffer(file);
    } else {
        $img.attr('src', URL.createObjectURL(file));
    }
}


//parses a string like "matrix(1,0,0,1,0,0)"
function parse_css_matrix(maxtrix_str){
    var x      = Number(maxtrix_str.split(')')[0].split(', ')[4])
    var y      = Number(maxtrix_str.split(')')[0].split(', ')[5])
    var scale  = Number(maxtrix_str.split('(')[1].split(',')[0])
    return {x:x, y:y, scale:scale};
}

//reload a script file (for debugging/development)
function reload_js(src) {
    $(`script[src^="${src}"]`).remove();
    $('<script>').attr('src', `${src}?cachebuster=${new Date().getTime()}`).appendTo('head');
}
