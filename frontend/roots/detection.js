


RootDetection = class extends BaseDetection{
    //override
    static async set_results(filename, results){
        if(results!=undefined && is_string(results.skeleton))
            results.skeleton = await fetch_as_file(url_for_image(results.skeleton))
        return super.set_results(filename, results);
    }
}

