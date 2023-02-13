

RootDetectionDownload = class extends BaseDownload{
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

    //override
    static zipdata_for_files(filenames){
        var zipdata      = super.zipdata_for_files(filenames)
        var combined_csv = ''
        for(var i in filenames){
            var single_csv = this.csv_data_for_file(filenames[i], i==0)
            if(single_csv!=undefined)
                combined_csv += single_csv;
        }
        if(combined_csv.length > 0)
            zipdata['statistics.csv'] = combined_csv;
        return zipdata;
    }

    static csv_data_for_file(filename, header=true){
        var csvtxt = '';
        if(header){
            csvtxt += 'Filename, '
                + '# root pixels, # background pixels, '
                + '# mask pixels, # skeleton pixels, '
                + '# skeleton pixels (<3px width), # skeleton pixels (3-7px width), # skeleton pixels (>7px width),'
                + 'Kimura length'
                + ';\n';
        }
        
        var f = GLOBAL.files[filename]
        if(!f.results)
            return;
        
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
        zipdata[`${filename0}.${filename1}.csv`]  = this.csv_data_statistics(filename0, filename1)
        return zipdata;
    }

    //override
    static on_download_all(event){
        var filenames          = Object.keys(GLOBAL.files)
        var filenames_combined = []
        var filenames_pairs    = []
        for(var filename0 of filenames){
            var tracking_results = GLOBAL.files[filename0].tracking_results
            if(tracking_results == undefined)
                continue;
            for(var filename1 of Object.keys(tracking_results))
                if(Object.keys(tracking_results[filename1]).length>0){
                    filenames_combined.push(`${filename0}.${filename1}`)
                    filenames_pairs.push([filename0, filename1])
                }
        }

        var zipdata = this.zipdata_for_files(filenames_combined)
        var combined_csv = ''
        for(var i in filenames_combined){
            var single_csv = this.csv_data_statistics(...filenames_pairs[i], i==0)
            if(single_csv!=undefined)
                combined_csv += single_csv;
        }
        if(combined_csv.length > 0)
            zipdata['statistics.csv'] = combined_csv;

        if(Object.keys(zipdata).length==0)
            return
        download_zip('tracking_results.zip', zipdata)
    }


    static csv_data_statistics(filename0, filename1, include_header=true){
        const result = GLOBAL.files[filename0].tracking_results[filename1]
        const stats  = result.statistics ?? {};
        const status_map = {
            true                : 'OK',
            false               : 'WARNING: No matching roots found',
            'TOO_MANY_ROOTS'    : 'SKIPPED: Too many roots'
        }

        const header = [
            'Filename 1',           'Filename 2', 
            'same pixels',          'decay pixels',          'growth pixels',
            'background pixels',    'mask pixels',
            'same skeleton pixels', 'decay skeleton pixels', 'growth skeleton pixels',
            'same kimura length',   'decay kimura length',   'growth kimura length',
            'status',
        ]
        const data   = [
            filename0,         filename1,    
            stats.sum_same,    stats.sum_decay,    stats.sum_growth,
            stats.sum_negative,stats.sum_exmask,
            stats.sum_same_sk, stats.sum_decay_sk, stats.sum_growth_sk,
            stats.kimura_same, stats.kimura_decay, stats.kimura_growth,
            status_map[result.success],
        ]

        //sanity check
        if(header.length != data.length){
            console.error('CSV data length mismatch:', header, data)
            $('body').toast({message:'CSV data length mismatch', class:'error'})
            return;
        }

        return (include_header? [header] : []).concat([data.join(', '), '']).join(';\n')
    }
}
