var RootTracking = new function() {
    
    this.set_input_files = function(files){
        var $table = $('#tracking-filetable tbody')
        $table.find('tr').remove()

        for(var f0 of files){
            for(var f1 of files){
                if(f0 == f1)
                    continue;
                
                var parsed0 = parse_filename(f0.name)
                var parsed1 = parse_filename(f1.name)
                if(parsed0.base == parsed1.base && parsed0.date < parsed1.date)
                    $('template#tracking-item').tmpl({filename0:f0.name, filename1:f1.name}).appendTo($table)
            }
        }
    };

    var parse_filename = function(fname){
        var splits = fname.split('_')
        var base   = splits.slice(0,3).join('_')
        var [d,m,y]  = splits[3].split('.').map(Number)
        y          = (y>70)? y+1900 : y+2000;           //1970...2069
        return {base:base, date:new Date(y,m,d)}
    }


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
        var $root     = $(event.target).closest("[filename0][filename1]")
        var filename0 = $root.attr("filename0");
        var filename1 = $root.attr("filename1");

        console.log(`Sending root tracking request for files ${filename0} and ${filename1}`);
        upload_file_to_flask('/file_upload', global.input_files[filename0].file);
        upload_file_to_flask('/file_upload', global.input_files[filename1].file);

        $root.find('.dimmer').dimmer('show');
        
        //send a processing request to python & update gui with the results
        return $.get(`/process_root_tracking`, {filename0:filename0, filename1:filename1}).done( data => {   //TODO: code re-use
            console.log(data)
            paint_matched_points(filename0, filename1, data.points0, data.points1);
            var $overlay = $(`[filename0="${filename0}"][filename1="${filename1}"] img.left-overlay`)
            $overlay.attr('src', `/images/${data.growthmap_rgba}?_=${new Date().getTime()}`).show()
            var $chkbx = $(`[filename0="${filename0}"][filename1="${filename1}"] .view-menu-popup .checkbox`)
            $chkbx.removeClass('disabled').checkbox('set checked').checkbox({onChange:function(){
                $overlay.toggle($chkbx.checkbox('is checked'));
                //TODO: also toggle svg
            }})
            global.input_files[filename0].tracking_results[filename1] = data;
            delete_image(filename0);
            delete_image(filename1);
            $root.find('.dimmer').dimmer('hide');
        });
    };


    this.on_svg_mousemove = function(event){
        var img  = $(event.target).find('img')[0];
        var $svg = $(event.target).find('svg');

        var svg_xy  = page2img_coordinates([event.pageX, event.pageY], img, $(event.target))
        $svg.find('circle.cursor').attr({cx:svg_xy[0], cy:svg_xy[1]})

        //TODO
        /*if(event.shiftKey)
            $(event.target).css('cursor', 'move')
        else if (event.ctrlKey)
            $(event.target).css('cursor', 'copy')
        else
            $(event.target).css('cursor', 'default')*/

        //FIXME: left or right image
        var filename0 = $(img).closest('[filename0]').attr('filename0')
        var filename1 = $(img).closest('[filename1]').attr('filename1')
        highlight_closest_matched_point(filename0, filename1, svg_xy);
    }

    //translate page coordinates xy to img coordinates
    //(viewport element provides topleft corner and transform)
    var page2img_coordinates = function(xy, img, $viewport){   //TODO: simplify/reduce number of arguments
        if(navigator.userAgent.indexOf('Chrom') != -1){
            //some layout issues with chrome
            var H = img.clientHeight;  //integer
            var W = img.clientWidth;
        } else {
            var H = $(img).height()      //float
            var W = $(img).width()
        }
        var xform        = parse_css_matrix($viewport.css('transform'));
        //absolute coordinates on the html element in pixels
        var html_x_abs   = xy[0] - $viewport.offset().left
        var html_y_abs   = xy[1] - $viewport.offset().top
        //relative coordinates on the html element, range 0.0..1.0
        var html_x_rel   = html_x_abs / W / xform.scale
        var html_y_rel   = html_y_abs / H / xform.scale
        //absolute coordinates on the svg element
        var svg_x_abs    = html_x_rel * img.naturalWidth
        var svg_y_abs    = html_y_rel * img.naturalHeight
        
        //console.log('>', [H,W], [html_x_abs, html_y_abs], [html_x_rel, html_y_rel], [svg_x_abs, svg_y_abs], xform)
        return [svg_x_abs, svg_y_abs];
    }

    var get_viewport_coordinates_of_image = function(img){
        var $viewbox    = $(img).parent()
        var topleft     = [$viewbox.parent().offset().left, $viewbox.parent().offset().top]
        var bottomright = [topleft[0]+$viewbox.width(), topleft[1]+$viewbox.height()]
        return {
            topleft:    page2img_coordinates(topleft,     img, $viewbox),
            bottomright:page2img_coordinates(bottomright, img, $viewbox),
        }
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

    this.on_svg_mousedown = function(event){
        if(event.shiftKey)
            start_move_image(event)
        else if(event.ctrlKey){
            var removed = remove_point_from_click(event)
            if(!removed)
                start_draw_correction(event)
        }
    }

    var start_move_image = function(mousedown_event){
        var $img    = $(mousedown_event.target)
        var click_y = mousedown_event.pageY;
        var click_x = mousedown_event.pageX;

        $(document).on('mousemove', function(mousemove_event) {
            if( (mousemove_event.buttons & 0x01)==0 ){
                $(document).off('mousemove');
                return;
            }

            var delta_y = mousemove_event.pageY - click_y;
            var delta_x = mousemove_event.pageX - click_x;
                click_y = mousemove_event.pageY;
                click_x = mousemove_event.pageX;
            mousemove_event.stopPropagation();
            
            var xform  = parse_css_matrix($img.css('transform'));
            var x      = xform.x + delta_x;
            var y      = xform.y + delta_y;
            var matrix = `matrix(${xform.scale}, 0, 0, ${xform.scale}, ${x}, ${y})`
            $img.css('transform', matrix);
        })
    }

    var start_draw_correction = function(mousedown_event){
        //TODO: check if growth map is loaded
        var $img    = $(mousedown_event.target).find('.left-image')
        if($img.get().length==0)
            return;
        var $svg     = $img.siblings('svg');
        
        $(document).on('mousemove', function(mousemove_event) {
            if( (mousemove_event.buttons & 0x01)==0 ){
                $svg.find('polyline.correction-line.unfinished').removeClass('unfinished')
                $(document).off('mousemove');
                return;
            }

            var start_xy = [mousedown_event.pageX, mousedown_event.pageY]
            var end_xy   = [mousemove_event.pageX, mousemove_event.pageY]
                start_xy = page2img_coordinates(start_xy, $img[0], $img.parent())
                end_xy   = page2img_coordinates(end_xy,   $img[0], $img.parent())
            
            $svg.find('polyline.correction-line.unfinished').remove()
            var $line = $(document.createElementNS('http://www.w3.org/2000/svg','polyline'));
            var points_str = `${start_xy[0]},${start_xy[1]}  ${end_xy[0]},${end_xy[1]}`;
            const line_attrs = {
                stroke         : "cyan",
                "stroke-width" : "1",
                fill           : "none",
                "marker-start" : "url(#dot-marker-green)",
                "marker-end"   : "url(#dot-marker-red)",
            };
            $line.attr(line_attrs).attr("points", points_str).addClass(['correction-line', 'unfinished']);
            $svg.append($line);
        });
    }

    var remove_point_from_click = function(mousedown_event){
        var $highlighted_point = $(mousedown_event.target).find('svg').find('.highlighted-matched-point')
        if($highlighted_point.length>0){
            var filename0 = $(mousedown_event.target).closest('[filename0]').attr('filename0');
            var filename1 = $(mousedown_event.target).closest('[filename1]').attr('filename1');

            var index = Number($highlighted_point.attr('index'));
            var tracking_results = global.input_files[filename0].tracking_results[filename1];
            tracking_results.points0.splice(index, 1)
            tracking_results.points1.splice(index,1)
            paint_matched_points(filename0, filename1, tracking_results.points0, tracking_results.points1)
            $('.highlighted-matched-point').remove()
            return true;
        }
        return false;
    }

    //reset view
    this.on_svg_dblclick = function(e){
        if(!e.shiftKey)
            return;
        var $img   = $(e.target).closest('.view-box').find('.transform-box');
        $img.css('transform', "matrix(1,0,0,1,0,0)");
    }

    //called when user clicks on the "check" button to apply manual corrrections to the growth map
    this.on_apply_corrections = function(event){
        //TODO: check if growth map is loaded
        var $svg = $(event.target).closest("[filename0]").find('svg.tracking-left-overlay-svg')
        var $correction_lines = $svg.find('polyline.correction-line')
        var points_str        = $correction_lines.get().map(x=>x.getAttribute('points'));
        var points            = points_str.map( x => x.split(/[, ]/g).filter(Boolean).map(Number) )

        var filename0 = $(event.target).closest("[filename0]").attr("filename0");
        var filename1 = $(event.target).closest("[filename1]").attr("filename1");
        var tracking_results = global.input_files[filename0].tracking_results[filename1];
        var post_data = {
            filename0:filename0, points0:tracking_results.points0,
            filename1:filename1, points1:tracking_results.points1,
            corrections:points
        }

        console.log(`Sending root tracking request for files ${filename0} and ${filename1} with corrections ${points}`);
        $.post('/process_root_tracking', JSON.stringify(post_data)).done( data => {   //TODO: code re-use
            console.log(data)
            paint_matched_points(filename0, filename1, data.points0, data.points1);
            $(`[filename0="${filename0}"] img.left-overlay`).attr('src', `/images/${data.growthmap_rgba}?_=${new Date().getTime()}`)  //FIXME: WRONG! see above
            global.input_files[filename0].tracking_results[filename1] = data;

            $correction_lines.remove()
        });
    }


    var paint_matched_points = function(filename0, filename1, p0,p1){
        var p0_str = p0.map(p => `${p[1]},${p[0]}`).join(' ')
        var p1_str = p1.map(p => `${p[1]},${p[0]}`).join(' ')

        var $parent = $(`[filename0="${filename0}"][filename1="${filename1}"]`)
        var $svg0 = $parent.find(`.tracking-left-overlay-svg`)
        var $svg1 = $parent.find(`.tracking-right-overlay-svg`)
        $svg0.find('polyline.matched-points').attr('points', p0_str);
        $svg1.find('polyline.matched-points').attr('points', p1_str);
    }

    var find_closest_point = function(p, points, return_index=false, max_distance=undefined){
        var distances = points.map( x => ((x[0]-p[0])**2 + (x[1]-p[1])**2)**0.5 )
        var i         = argmin(distances)
        if(distances[i]<=max_distance || max_distance==undefined)
            if(return_index)
                return i;
            else
                return points[i];
    }

    var clip_point_to_viewport = function(xy, img){
        var viewport = get_viewport_coordinates_of_image(img)
        return [
            Math.max(Math.min(xy[0], viewport.bottomright[0]), viewport.topleft[0]),
            Math.max(Math.min(xy[1], viewport.bottomright[1]), viewport.topleft[1]),
        ]
    }

    //highlights a point closest to `xy` in the left image and the corresponding point in the right image
    //TODO: accept a point from the right image
    var highlight_closest_matched_point = function(filename0, filename1, xy){
        var tracking_results = global.input_files[filename0].tracking_results[filename1]
        if(tracking_results==undefined)
            return;
        
        var $parent = $(`[filename0="${filename0}"][filename1="${filename1}"]`)  //FIXME? pass $svg as argument
        var $svg0 = $parent.find(`.tracking-left-overlay-svg`)
        var $svg1 = $parent.find(`.tracking-right-overlay-svg`)
        $svg0.find('circle.highlighted-matched-point').remove()
        $svg1.find('circle.highlighted-matched-point').remove()

        var idx = find_closest_point([xy[1], xy[0]], tracking_results.points0, true, 3)  //FIXME: or points1
        if(idx==undefined)
            return;
        var p0_yx  = tracking_results.points0[idx];
        var p1_yx  = tracking_results.points1[idx];
        var img0   = $svg0.siblings('.left-image')[0]
        var img1   = $svg1.siblings('.right-image')[0]
        var p0_xy  = clip_point_to_viewport([p0_yx[1],p0_yx[0]], img0)
        var p1_xy  = clip_point_to_viewport([p1_yx[1],p1_yx[0]], img1)

        const attrs = {
            r    : 3,
            fill : "cyan",
            index: idx,
        };
        var $point0     = $(document.createElementNS('http://www.w3.org/2000/svg','circle'));
        var $point1     = $(document.createElementNS('http://www.w3.org/2000/svg','circle'));
        $point0.attr(attrs).attr({cx:p0_xy[0], cy:p0_xy[1]}).addClass('highlighted-matched-point');
        $point1.attr(attrs).attr({cx:p1_xy[0], cy:p1_xy[1]}).addClass('highlighted-matched-point');
        $svg0.append($point0);
        $svg1.append($point1);
    }

}; //RootTracking



