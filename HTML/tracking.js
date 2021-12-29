var RootTracking = new function() {
    
    this.set_input_files = function(files){
        for(var f0 of files){
            for(var f1 of files){
                if(f0 == f1)
                    continue;
                
                var base0 = f0.name.split('_').slice(0,3).join('_')
                var base1 = f1.name.split('_').slice(0,3).join('_')
                if(base0 == base1)
                    $('template#tracking-item').tmpl({filename0:f0.name, filename1:f1.name}).appendTo('#tracking-filetable tbody')
            }
        }
    };


    //called when user clicks on a file table row to open it
    this.on_accordion_open = function(){
        var $imgelement0 = this.find('img.left-image');
        var content_already_loaded = !!$imgelement0.attr('src')
        if(!content_already_loaded){
            var filename0   = this.attr('filename0');
            var file0       = global.input_files[filename0].file;
            
            $imgelement0.one('load', function(){
                $imgelement0.siblings('svg').attr('viewBox', `0 0 ${$imgelement0[0].naturalWidth} ${$imgelement0[0].naturalHeight}`);
            });
            set_imgsrc_from_file($imgelement0, file0);
        }

        //TODO: code re-use
        var $imgelement1 = this.find('img.right-image');
        var content_already_loaded = !!$imgelement1.attr('src')
        if(!content_already_loaded){
            var filename1   = this.attr('filename1');
            var file1       = global.input_files[filename1].file;

            $imgelement1.one('load', function(){
                $imgelement1.siblings('svg').attr('viewBox', `0 0 ${$imgelement1[0].naturalWidth} ${$imgelement1[0].naturalHeight}`);
            });
            set_imgsrc_from_file($imgelement1, file1);
        }
    };

    //called when user clicks on the "play" button to perform root tracking
    this.on_process_clicked = function(event){
        var filename0 = $(event.target).closest("[filename0]").attr("filename0");
        var filename1 = $(event.target).closest("[filename1]").attr("filename1");

        console.log(`Sending root tracking request for files ${filename0} and ${filename1}`);
        upload_file_to_flask('/file_upload', global.input_files[filename0].file);
        upload_file_to_flask('/file_upload', global.input_files[filename1].file);
        
        //send a processing request to python & update gui with the results
        return $.get(`/process_root_tracking`, {filename0:filename0, filename1:filename1}).done( data => {
            console.log(data)
            RootTracking.paint_matched_points(filename0, filename1, data.points0, data.points1);
            $(`[filename0="${filename0}"] img.left-overlay`).attr('src', `/images/${data.growthmap_rgba}?_=${new Date().getTime()}`)
            delete_image(filename0);
            delete_image(filename1);
        });
    };


    this.on_svg_mousemove = function(event){
        var img  = $(event.target).find('img')[0];
        var $svg = $(event.target).find('svg');

        var $parent = $(img).parent().parent()
        var xform   = parse_css_matrix($(event.target).css('transform'));
        var svg_xy  = page2img_coordinates([event.pageX, event.pageY], img, xform, $parent[0])

        $svg.find('circle.cursor').attr({cx:svg_xy[0], cy:svg_xy[1]})
    }

    //translate page coordinates xy to img coordinates via transform `xform`
    //(viewport element provides topleft corner)
    var page2img_coordinates = function(xy, img, xform, viewport){   //TODO: simplify/reduce number of arguments
        //var H = img.clientHeight;  //integer
        //var W = img.clientWidth;
        var H = $(img).height()      //float    //FIXME: still inaccurate
        var W = $(img).width()
        //absolute coordinates on the html element in pixels
        var html_x_abs   = xy[0] - $(viewport).offset().left
        var html_y_abs   = xy[1] - $(viewport).offset().top
        //relative coordinates on the html element, range -0.5..+0.5
        var html_x_rel   = (html_x_abs - W/2)/W 
        var html_y_rel   = (html_y_abs - H/2)/H
        //relative coordinates on the svg element, range -0.5..+0.5
        var svg_x_rel    = (html_x_rel - xform.x/W) / xform.scale
        var svg_y_rel    = (html_y_rel - xform.y/H) / xform.scale
        //absolute coordinates on the svg element
        var svg_x_abs    = (svg_x_rel + 0.5) * img.naturalWidth
        var svg_y_abs    = (svg_y_rel + 0.5) * img.naturalHeight
        
        //console.log('>', [H,W], [html_x_abs, html_y_abs], [html_x_rel, html_y_rel], [svg_x_abs, svg_y_abs])
        return [svg_x_abs, svg_y_abs];
    }

    this.on_svg_wheel = function(event){
        if(!event.shiftKey)
            return;
        
        event.preventDefault();
        var $img   = $(event.target);
        var xform   = parse_css_matrix($(event.target).css('transform'));
        var x      = xform.x * (1 - 0.1*Math.sign(event.deltaY))
        var y      = xform.y * (1 - 0.1*Math.sign(event.deltaY))
        var scale  = Math.max(1.0, xform.scale * (1 - 0.1*Math.sign(event.deltaY)));
        var matrix = `matrix(${scale}, 0, 0, ${scale}, ${x}, ${y})`
        $img.css('transform', matrix);
        $img.find('svg').find('circle.cursor').attr('r', 5/scale)
    }

    this.on_svg_mousedown = function(md_evt){
        if(!md_evt.shiftKey && !md_evt.ctrlKey)
            return;

        var $img    = $(md_evt.target)
        var click_y = md_evt.pageY;
        var click_x = md_evt.pageX;

        function stop_drag(){
            $(document).off('mousemove');
            $(document).off('mouseup');
        }

        $(document).on('mousemove', function(mm_evt) {
            if( (mm_evt.buttons & 0x01)==0 ){
                stop_drag();
                return;
            }

            var delta_y = mm_evt.pageY - click_y;
            var delta_x = mm_evt.pageX - click_x;
                click_y = mm_evt.pageY;
                click_x = mm_evt.pageX;
            mm_evt.stopPropagation();

            if(md_evt.shiftKey)
                RootTracking.move_image($img, delta_x, delta_y);
            else if(md_evt.ctrlKey)
                RootTracking.draw_correction($img.find('.left-image'), [md_evt.pageX, md_evt.pageY], [mm_evt.pageX, mm_evt.pageY]);   //TODO: check if left image
        })
    }

    //reset view
    this.on_svg_dblclick = function(e){
        if(!e.shiftKey)
            return;
        var $img   = $(e.target);
        $img.css('transform', "matrix(1,0,0,1,0,0)");
    }

    this.move_image = function($img, dx, dy){
        var xform  = parse_css_matrix($img.css('transform'));
        var x      = xform.x + dx;
        var y      = xform.y + dy;
        var matrix = `matrix(${xform.scale}, 0, 0, ${xform.scale}, ${x}, ${y})`
        $img.css('transform', matrix);
    }

    this.draw_correction = function($img, start_xy, end_xy){
        var $parent = $img.parent().parent()
        var xform   = parse_css_matrix($img.parent().css('transform'));
        start_xy    = page2img_coordinates(start_xy, $img[0], xform, $parent[0])
        end_xy      = page2img_coordinates(end_xy,   $img[0], xform, $parent[0])

        var $svg    = $img.siblings('svg');
        $svg.find('polyline.correction-line').remove()
        var $line = $(document.createElementNS('http://www.w3.org/2000/svg','polyline'));
        var points_str = `${start_xy[0]},${start_xy[1]}  ${end_xy[0]},${end_xy[1]}`;
        const line_attrs = {
            stroke         : "white",
            "stroke-width" : "1",
            fill           : "none",
        };
        $line.attr(line_attrs).attr("points", points_str).addClass('correction-line');
        $svg.append($line);

    }

    //called when user clicks on the "check" button to apply manual corrrections to the growth map
    this.on_apply_corrections = function(event){
        var $svg = $(event.target).closest("[filename0]").find('svg.tracking-left-overlay-svg')
        var $correction_lines = $svg.find('polyline.correction-line')
        var points_str        = $correction_lines.get().map(x=>x.getAttribute('points'));
        var points            = points_str.map( x => x.split(/[, ]/g).filter(Boolean).map(Number) )

        var filename0 = $(event.target).closest("[filename0]").attr("filename0");
        var filename1 = $(event.target).closest("[filename1]").attr("filename1");
        var post_data = {filename0:filename0, filename1:filename1, corrections:points}

        console.log(`Sending root tracking request for files ${filename0} and ${filename1} with corrections ${points}`);
        upload_file_to_flask('/file_upload', global.input_files[filename0].file);
        upload_file_to_flask('/file_upload', global.input_files[filename1].file);
        $.post('/process_root_tracking', JSON.stringify(post_data)).done( data => {   //TODO: code re-use
            console.log(data)
            RootTracking.paint_matched_points(filename0, filename1, data.points0, data.points1);
            $(`[filename0="${filename0}"] img.left-overlay`).attr('src', `/images/${data.growthmap_rgba}?_=${new Date().getTime()}`)
            delete_image(filename0);
            delete_image(filename1);

            $correction_lines.remove()
        });
    }


    this.paint_matched_points = function(filename0, filename1, p0,p1){
        var p0_str = p0.map(p => `${p[1]},${p[0]}`).join(' ')
        var p1_str = p1.map(p => `${p[1]},${p[0]}`).join(' ')

        var $parent = $(`[filename0="${filename0}"][filename1="${filename1}"]`)
        var $svg0 = $parent.find(`.tracking-left-overlay-svg`)
        var $svg1 = $parent.find(`.tracking-right-overlay-svg`)
        $svg0.find('polyline.matched-points').attr('points', p0_str);
        $svg1.find('polyline.matched-points').attr('points', p1_str);
    }

}; //RootTracking



