
export function parse_filename(filename){
    const date_candidates   = filename.split('_')
    let date                = new Date(NaN)
    let datestring          = '';

    for(datestring of date_candidates) {
        const splits = datestring.split('.')
        if(splits.map(Number).filter(Boolean).length == 3){
            const [a,b,c] = splits;
            if(a.length > 2)
                //interpreting as format YYYYMMDD
                var [y,m,d] = [a,b,c].map(Number)
            else if(c.length > 2)
                //interpreting as format DDMMYYYY
                var [y,m,d] = [c,b,a].map(Number)
            else {
                //interpreting as format DDMMYY
                var [y,m,d] = [c,b,a].map(Number)
                y           = y<70? (y+2000) : (y+1900);    //1970-2069
            }
            date = new Date(y, m-1, d);
            break;
        }
    }
    
    const base = filename.split(datestring)[0]
    return {base, date}
}


window.parse_filename = parse_filename;
