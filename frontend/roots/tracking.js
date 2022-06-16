var RootTracking = new function() {
    
    this.set_input_files = function(files){
        var $table = $('#tracking-filetable tbody')
        $table.find('tr').remove()

        var n_pairs = 0
        for(var f0 of files){
            for(var f1 of files){
                if(f0 == f1)
                    continue;
                
                try{
                    var parsed0 = parse_filename(f0.name)
                    var parsed1 = parse_filename(f1.name)
                } catch {
                    continue;
                }
                if(parsed0.base == parsed1.base && parsed0.date < parsed1.date){
                    $('template#tracking-item').tmpl({filename0:f0.name, filename1:f1.name}).appendTo($table)
                    //GLOBAL.files[f0.name].tracking_results[f1.name] = {};
                    GLOBAL.files[f0.name].tracking_results = {[f1.name]: {}};  //TODO: refactor
                    n_pairs += 1;
                }
            }
        }

        $('#tracking-filetable thead th').text(`${n_pairs} Image Pair${(n_pairs==1)?'':'s'} Loaded`)
    };

    this.load_result = async function(filename0, filename1, tracking_results_file, segmentation0_file, segmentation1_file){
        tracking_results_file = await tracking_results_file
        segmentation0_file    = rename_file(await segmentation0_file, `${filename0}.segmentation.png`)
        segmentation1_file    = rename_file(await segmentation1_file, `${filename1}.segmentation.png`)

        upload_file_to_flask('/file_upload', segmentation0_file);
        upload_file_to_flask('/file_upload', segmentation1_file);

        tracking_results_file.text().then(function(text){
            var jsondata = JSON.parse(text);
            jsondata['corrections'] = [];
            process_single(filename0, filename1, false, jsondata)
        });
    }
    

    var parse_filename = function(fname){
        var splits = fname.split('_')
        var base   = splits.slice(0,3).join('_')
        var date   = splits[3];
        var [a,b,c]    = date.split('.')
        if(a.length>2)
            var [y,m,d] = [a,b,c].map(Number)
        else {
            var [y,m,d] = [c,b,a].map(Number)
            y           = y<70? (y+2000) : (y+1900);    //1970-2069
        }
        return {base:base, date:new Date(y,m-1,d)}
    }


    //called when user clicks on a file table row to open it
    this.on_accordion_open = function(){
        var $root = $(this)

        var $imgelement0 = this.find('img.left.input-image');
        var $imgelement1 = this.find('img.right.input-image');

        var content_already_loaded = !!$imgelement0.attr('src') && !!$imgelement1.attr('src')
        if(!content_already_loaded){
            var filename0   = this.attr('filename0');
            var filename1   = this.attr('filename1');
            var file0       = GLOBAL.files[filename0];
            var file1       = GLOBAL.files[filename1];

            //hide all content except the loading message to avoid jerking //FIXME: jerking anyway
            $root = this;
            $root.find('div.tracking-content').hide()
            $root.find('.loading-message').show()
            
            var promise = $imgelement0.one('load', function(){
                $imgelement0.siblings('svg').attr('viewBox', `0 0 ${$imgelement0[0].naturalWidth} ${$imgelement0[0].naturalHeight}`);
            });
            $imgelement1.one('load', async function(){
                $imgelement1.siblings('svg').attr('viewBox', `0 0 ${$imgelement1[0].naturalWidth} ${$imgelement1[0].naturalHeight}`);

                await promise;
                $root.find('.loading-message').hide()
                $root.find('div.tracking-content').show()
            });
            GLOBAL.App.ImageLoading.set_image_src($imgelement0, file0);
            GLOBAL.App.ImageLoading.set_image_src($imgelement1, file1);
        }
    };

    //called when user clicks on the "play" button to perform root tracking
    this.on_process_clicked = function(event){
        var $root     = $(event.target).closest("[filename0][filename1]")
        var filename0 = $root.attr("filename0");
        var filename1 = $root.attr("filename1");

        process_single(filename0, filename1)
    };

    this.on_process_all = async function(event){
        for(var file0 of Object.values(GLOBAL.files)){
            if(file0.tracking_results==undefined)
                continue
            
            for(var filename1 of Object.keys(file0.tracking_results))
                await process_single(file0.name, filename1)
        }
    }

    var process_single = async function(filename0, filename1, upload_images=true, extra_data={}){
        //TODO: clear
        var $root     = $(`[filename0="${filename0}"][filename1="${filename1}"]`)
        var $dimmer   = $root.find('.dimmer')
        
        $dimmer.dimmer({closable:false}).dimmer('show');
        $dimmer.find('.content.processing').show()
        $dimmer.find('.content.failed').hide()

        if(upload_images){
            await upload_file_to_flask(GLOBAL.files[filename0]);
            await upload_file_to_flask(GLOBAL.files[filename1]);
        }

        console.log(`Sending root tracking request for files ${filename0} and ${filename1}`);
        var request_data = {filename0:filename0, filename1:filename1};
        Object.assign(request_data, extra_data)
        
        var request_method = $.get;
        if(Object.keys(extra_data).length>0){
            request_method = $.post;
            request_data   = JSON.stringify(request_data)
        }
        return request_method(`/process_root_tracking`, request_data).done( data => {
            set_tracking_data(filename0, filename1, data)
            if(data.success)
                $dimmer.dimmer('hide');
            else{
                $dimmer.find('.content.processing').hide()
                $dimmer.find('.content.failed').show()
                $dimmer.dimmer({closable:true});
            }
        }).fail( () => {
            $dimmer.find('.content.processing').hide()
            $dimmer.find('.content.failed').show()
            $dimmer.dimmer({closable:true});
        } ).always( () => {
            $root.find('polyline.correction-line').remove()
            delete_image(filename0);
            delete_image(filename1);
        });
    }

    /* TODO: states
    unprocessed: dimmer off, view checkboxes/download disabled, global.data clear, growthmap cleared, processing button enabled
    processing:  dimmer on,  view checkboxes/download disabled, ---              , ---,               processing button disabled
    processed:   dimmer off, view checkboxes/download enabled,  global.data set  , growthmap set,     processing button enabled
    failed: ?
    */
    var set_tracking_data = function(filename0, filename1, data){
        console.log('Tracking results: ', data)
        GLOBAL.files[filename0].tracking_results[filename1] = data;
        paint_matched_points(filename0, filename1, data.points0, data.points1);

        var $root    = $(`[filename0="${filename0}"][filename1="${filename1}"]`);
        var $overlay = $root.find(`img.right.overlay`)
            $overlay.attr('src', url_for_image(data.growthmap_rgba))
        var $chkbx0 = $root.find('.show-turnover-checkbox')
            $chkbx0.removeClass('disabled').checkbox({onChange:()=>{
                $overlay.toggle($chkbx0.checkbox('is checked'));
        }}).checkbox('check')
        var $chkbx1 = $root.find('.show-matched-points-checkbox')
            $chkbx1.removeClass('disabled').checkbox({onChange:()=>{
            $root.find('svg .matched-points').toggle($chkbx1.checkbox('is checked'));
        }})
        $root.find('a.download').removeClass('disabled')
        $root.filter('.title').find('label').css('font-weight', 'bold')
    }


    this.on_svg_mousemove = function(event){
        var img  = $(event.target).find('img')[0];
        var $svg = $(event.target).find('svg');

        var svg_xy  = page2img_coordinates([event.pageX, event.pageY], img, $(event.target))
        $svg.find('circle.cursor').attr({cx:svg_xy[0], cy:svg_xy[1]})

        highlight_closest_matched_point($svg, svg_xy);
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

    this.single_click_correction = function(mousedown_event){
        var $root   = $(mousedown_event.target).closest("[filename0][filename1]");
        var $img    = $(mousedown_event.target).find('.input-image')
        var $svg    = $img.siblings('svg');

        var filename0 = $root.attr("filename0");
        var filename1 = $root.attr("filename1");
        if(!is_processed(filename0, filename1))
            return;
        
        $(document).one('mouseup', function(mouseup_event){
            $svg.find('.single-click-correction-point').remove()
            const attrs = {
                r    : 3,
                fill : "pink",
            };
            var start_xy = [mousedown_event.pageX, mousedown_event.pageY]
                start_xy = page2img_coordinates(start_xy, $img[0], $img.parent())
            var $point0     = $(document.createElementNS('http://www.w3.org/2000/svg','circle'));
            $point0.attr(attrs).attr({cx:start_xy[0], cy:start_xy[1]}).addClass('single-click-correction-point');
            $svg.append($point0);

            var $single_point_left  = $root.find('svg.left.overlay .single-click-correction-point')
            var $single_point_right = $root.find('svg.right.overlay .single-click-correction-point')
            if($single_point_left.length>0 && $single_point_right.length>0){
                var tracking_results = GLOBAL.files[filename0].tracking_results[filename1];
                tracking_results.points0.push([Number($single_point_left.attr('cy')),  Number($single_point_left.attr('cx')) ])
                tracking_results.points1.push([Number($single_point_right.attr('cy')), Number($single_point_right.attr('cx'))])
                paint_matched_points(filename0, filename1, tracking_results.points0, tracking_results.points1)

                $single_point_left.remove()
                $single_point_right.remove()
                $root.find('.show-matched-points-checkbox').checkbox('check') //TODO: refactor
            }

        }).one('mousemove', function(mousemove_event) {
            //mouse moved, not a single click anymore, cancel
            $(document).off('mouseup');
        });
    }

    this.drag_line_correction = function(mousedown_event){
        var $root   = $(mousedown_event.target).closest("[filename0][filename1]");
        var filename0 = $root.attr("filename0");
        var filename1 = $root.attr("filename1");
        if(!is_processed(filename0, filename1))
            return;

        var $img    = $(mousedown_event.target).find('.right.input-image')
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
                "marker-start" : "url(#dot-marker-red)",
                "marker-end"   : "url(#dot-marker-green)",
            };
            $line.attr(line_attrs).attr("points", points_str).addClass(['correction-line', 'unfinished']);
            $svg.append($line);
        });
    }

    this.remove_point_from_click = function(mousedown_event){
        var $highlighted_point = $(mousedown_event.target).find('svg').find('.highlighted-matched-point')
        if($highlighted_point.length>0){
            var filename0 = $(mousedown_event.target).closest('[filename0]').attr('filename0');
            var filename1 = $(mousedown_event.target).closest('[filename1]').attr('filename1');

            var index = Number($highlighted_point.attr('index'));
            var tracking_results = GLOBAL.files[filename0].tracking_results[filename1];
            tracking_results.points0.splice(index, 1)
            tracking_results.points1.splice(index,1)
            paint_matched_points(filename0, filename1, tracking_results.points0, tracking_results.points1)
            $('.highlighted-matched-point').remove()
            return true;
        }
        return false;
    }

    //called when user clicks on the "check" button to apply manual corrrections to the growth map
    this.on_apply_corrections = function(event){
        var $root             = $(event.target).closest("[filename0][filename1]");
        var filename0 = $root.attr("filename0");
        var filename1 = $root.attr("filename1");
        if(!is_processed(filename0, filename1))
            return;
        
        var $svg              = $root.find('svg.right.overlay')
        var $correction_lines = $svg.find('polyline.correction-line')
        var points_str        = $correction_lines.get().map(x=>x.getAttribute('points'));
        var points            = points_str.map( x => x.split(/[, ]/g).filter(Boolean).map(Number) )

        var tracking_results = GLOBAL.files[filename0].tracking_results[filename1];
        var post_data = {
            points0:           tracking_results.points0,
            points1:           tracking_results.points1,
            corrections:       points,
            n_matched_points   : tracking_results.n_matched_points,
            tracking_model     : tracking_results.tracking_model,
            segmentation_model : tracking_results.segmentation_model,
        }

        process_single(filename0, filename1, false, post_data);
    }

    var is_processed = function(filename0, filename1){
        var r = GLOBAL.files[filename0].tracking_results[filename1];
        return r.growthmap != undefined;
    }


    var paint_matched_points = function(filename0, filename1, p0,p1){
        var p0_str = p0.map(p => `${p[1]},${p[0]}`).join(' ')
        var p1_str = p1.map(p => `${p[1]},${p[0]}`).join(' ')

        var $root = $(`[filename0="${filename0}"][filename1="${filename1}"]`)
        var $svg0 = $root.find(`.left.overlay`)
        var $svg1 = $root.find(`.right.overlay`)
        $svg0.find('polyline.matched-points').attr('points', p0_str);
        $svg1.find('polyline.matched-points').attr('points', p1_str);
    }

    var find_closest_point = function(p, points, return_index=false, max_distance=undefined){
        if(points.length==0)
            return;
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

    //highlight a point closest to `xy` in one image and the corresponding point in the other image
    var highlight_closest_matched_point = function($svg, xy){
        var $root            = $svg.closest('[filename0][filename1]');
        var filename0        = $root.attr('filename0')
        var filename1        = $root.attr('filename1')
        var tracking_results = GLOBAL.files[filename0].tracking_results[filename1]
        if(tracking_results==undefined)
            return;

        var $svg0 = $root.find(`.left.overlay`)
        var $svg1 = $root.find(`.right.overlay`)
        $svg0.find('circle.highlighted-matched-point').remove()
        $svg1.find('circle.highlighted-matched-point').remove()
        if(!$root.find('svg .matched-points').is(':visible'))
            return;

        var position = $svg.hasClass('left')? 'left' : 'right';
        var points = (position=='left')? tracking_results.points0 : tracking_results.points1;
        var idx = find_closest_point([xy[1], xy[0]], points, true, 3)
        if(idx==undefined)
            return;
        var p0_yx  = tracking_results.points0[idx];
        var p1_yx  = tracking_results.points1[idx];
        var img0   = $svg0.siblings('.left.input-image')[0]
        var img1   = $svg1.siblings('.right.input-image')[0]
        var p0_xy  = clip_point_to_viewport([p0_yx[1],p0_yx[0]], img0)
        var p1_xy  = clip_point_to_viewport([p1_yx[1],p1_yx[0]], img1)

        const attrs = {
            fill : "cyan",
            index: idx,
        };
        var xform0  = parse_css_matrix($svg0.closest('.transform-box').css('transform'));
        var radius0 = Math.min(Math.max(16/xform0.scale, 3), 16)
        var xform1  = parse_css_matrix($svg1.closest('.transform-box').css('transform'));
        var radius1 = Math.min(Math.max(16/xform1.scale, 3), 16)

        var $point0     = $(document.createElementNS('http://www.w3.org/2000/svg','circle'));
        var $point1     = $(document.createElementNS('http://www.w3.org/2000/svg','circle'));
        $point0.attr(attrs).attr({cx:p0_xy[0], cy:p0_xy[1], r:radius0}).addClass('highlighted-matched-point');
        $point1.attr(attrs).attr({cx:p1_xy[0], cy:p1_xy[1], r:radius1}).addClass('highlighted-matched-point');
        $svg0.append($point0);
        $svg1.append($point1);
    }


    this._dbg_highlight_manual_matches = function(radius=10){
        $('.highlighted-manual-point').remove()

        for(var fname0 in GLOBAL.files){
            var f = GLOBAL.files[fname0];
            for(var fname1 in f.tracking_results){
                console.log(fname0, fname1, is_processed(fname0, fname1))
                if(!is_processed(fname0, fname1))
                    continue;
                var tracking_results = f.tracking_results[fname1];
                var n_auto_points    = tracking_results.n_matched_points;
                var manual_points0   = tracking_results.points0.slice(n_auto_points)
                var manual_points1   = tracking_results.points1.slice(n_auto_points)

                var $svg0 = $(`[filename0="${fname0}"][filename1="${fname1}"] .left.overlay`)
                var $svg1 = $(`[filename0="${fname0}"][filename1="${fname1}"] .right.overlay`)

                for(var i of arange(manual_points0.length)){
                    var p0 = manual_points0[i]
                    var p1 = manual_points1[i]

                    var $point0     = $(document.createElementNS('http://www.w3.org/2000/svg','circle'));
                    var $point1     = $(document.createElementNS('http://www.w3.org/2000/svg','circle'));
                    const attrs = {
                        fill : "cyan",
                        r    : radius,
                    };
                    $point0.attr(attrs).attr({cx:p0[1], cy:p0[0]}).addClass('highlighted-manual-point');
                    $point1.attr(attrs).attr({cx:p1[1], cy:p1[0]}).addClass('highlighted-manual-point');
                    $svg0.append($point0);
                    $svg1.append($point1);
                }
            }
        }
    }

}; //RootTracking



TrackingViewControls = class TrackingViewControls extends ViewControls{
    //overwrite
    static on_transformbox_mousedown(event){
        if(super.on_transformbox_mousedown(event))
            return;
        else if(event.ctrlKey){
            var removed = RootTracking.remove_point_from_click(event)
            if(!removed){
                RootTracking.single_click_correction(event)
                RootTracking.drag_line_correction(event)
            }
        }
    }

    static on_transformbox_mousemove(event){
        RootTracking.on_svg_mousemove(event)
    }
}

