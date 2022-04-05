



RootDetectionDownload = class RootDetectionDownload extends BaseDownload{
    //override
    static zipdata_for_file(filename){
        var f            = GLOBAL.files[filename];
        var zipdata      = {};
        var segmentation = fetch_as_blob(url_for_image(f.results.segmentation))
        var skeleton     = fetch_as_blob(url_for_image(f.results.skeleton))
        zipdata[`${f.results.segmentation}`] = segmentation
        zipdata[`${f.results.skeleton}`]     = skeleton
        zipdata[`statistics.csv`]            = this.csv_data_for_file(filename)
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

