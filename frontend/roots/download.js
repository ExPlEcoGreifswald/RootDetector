



RootDetectionDownload = class RootDetectionDownload extends BaseDownload{
    //override
    static zipdata_for_file(filename){
        var f                           = GLOBAL.files[filename];
        if(!f.results)
            return undefined;
        
        var zipdata                     = {};
        var segmentation                = f.results.segmentation
        var skeleton                    = f.results.skeleton
        zipdata[`${segmentation.name}`] = segmentation
        zipdata[`${skeleton.name}`]     = skeleton
        zipdata[`statistics.csv`]       = this.csv_data_for_file(filename)
        return zipdata;
    }

    static csv_data_for_file(filename){
        var csvtxt = 'Filename, '
                + '# root pixels, # background pixels, '
                + '# mask pixels, # skeleton pixels, '
                + '# skeleton pixels (<3px width), # skeleton pixels (3-7px width), # skeleton pixels (>7px width),'
                + 'Kimura length'
                + ';\n';
        
        var f = GLOBAL.files[filename]
        if(!f.results)
            return;
        
        console.log(f)
        var stats = f.results.statistics;
        csvtxt   += [
            filename,
            stats.sum,       stats.sum_negative,
            stats.sum_mask,  stats.sum_skeleton, 
            stats.widths[0], stats.widths[1], stats.widths[2],
            stats.kimura_length,
        ].join(', ')+';\n'

        return csvtxt;
    }
}



RootTrackingDownload = class extends BaseDownload {
    //override
    static zipdata_for_file(filename){
        var $root     = $(`[filename0][filename1][filename="${filename}"]`)
        if($root.length==0) //should not happen
            return;
        
        var filename0     = $root.attr('filename0')
        var filename1     = $root.attr('filename1')
        var tracking_data = GLOBAL.files[filename0].tracking_results[filename1];
        if(tracking_data==undefined)
        return;

        var zipdata  = {};
        zipdata[tracking_data.growthmap]     = fetch_as_blob(url_for_image(tracking_data.growthmap))
        zipdata[tracking_data.segmentation0] = fetch_as_blob(url_for_image(tracking_data.segmentation0))
        zipdata[tracking_data.segmentation1] = fetch_as_blob(url_for_image(tracking_data.segmentation1))
        var jsondata = {
        filename0 : filename0,
        filename1 : filename1,
        points0   : tracking_data.points0,
        points1   : tracking_data.points1,
        n_matched_points   : tracking_data.n_matched_points,
        tracking_model     : tracking_data.tracking_model,
        segmentation_model : tracking_data.segmentation_model,
        }
        zipdata[`${filename0}.${filename1}.json`] = JSON.stringify(jsondata);
        return zipdata;
    }

    //override
    static on_download_all(event){
        var zipdata   = {}
        var filenames = Object.keys(GLOBAL.files)
        //testing all possible combinations. FIXME: make this a bit smarter
        for(var filename0 of filenames){
            for(var filename1 of filenames){
                var combined = `${filename0}.${filename1}`
                var fzipdata = this.zipdata_for_file(combined)
                if(fzipdata == undefined)
                    continue;
            
                Object.assign(zipdata, fzipdata)
            }
        }
        //TODO: check if empty
        download_zip('results.zip', zipdata)
    }
}
