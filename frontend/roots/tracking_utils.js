
export function parse_filename(filename){
    const date_candidates   = filename.split('_')
    let date                = new Date(NaN)
    let datestring          = ''

    for(const candidate of date_candidates) {
        const splits = candidate.split('.')
        if(splits.length == 3 && splits.every(value => /^\d+$/.test(value))){
            const [a,b,c] = splits;
            if(a.length > 2)
                // interpreting as format YYYY.MM.DD
                var [y,m,d] = [a,b,c].map(Number)
            else if(c.length > 2)
                // interpreting as format DD.MM.YYYY
                var [y,m,d] = [c,b,a].map(Number)
            else {
                // interpreting as format DD.MM.YY
                var [y,m,d] = [c,b,a].map(Number)
                y           = y<70? (y+2000) : (y+1900);    //1970-2069
            }
            const parsed = new Date(y, m-1, d)
            if(
                parsed.getFullYear() == y
                && parsed.getMonth() == m-1
                && parsed.getDate() == d
            ){
                date = parsed
                datestring = candidate
                break
            }
        }
    }

    const base = datestring ? filename.split(datestring)[0] : undefined
    return {base, date, datestring}
}


function date_key(date){
    const year = String(date.getFullYear()).padStart(4, '0')
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
}


export function plan_tracking_pairs(files){
    const groups = new Map()
    const issues = []

    for(const file of files){
        const filename = typeof file == 'string' ? file : file.name
        const parsed = parse_filename(filename)
        if(!parsed.base || !Number.isFinite(parsed.date.getTime())){
            issues.push({code: 'invalid_date', filename: filename})
            continue
        }
        const group = groups.get(parsed.base) ?? []
        group.push({filename: filename, date: parsed.date})
        groups.set(parsed.base, group)
    }

    const pairs = []
    for(const base of [...groups.keys()].sort()){
        const observations = groups.get(base)
        const by_date = new Map()
        for(const observation of observations){
            const key = date_key(observation.date)
            const same_date = by_date.get(key) ?? []
            same_date.push(observation)
            by_date.set(key, same_date)
        }

        const duplicates = [...by_date.entries()].filter(([_date, items]) => items.length > 1)
        if(duplicates.length){
            for(const [date, items] of duplicates){
                issues.push({
                    code: 'duplicate_date',
                    base: base,
                    date: date,
                    filenames: items.map(item => item.filename).sort(),
                })
            }
            continue
        }

        observations.sort((first, second) => (
            first.date - second.date || first.filename.localeCompare(second.filename)
        ))
        for(let index = 0; index < observations.length - 1; index += 1){
            pairs.push([
                observations[index].filename,
                observations[index + 1].filename,
            ])
        }
    }

    return {pairs: pairs, issues: issues}
}


if(typeof window != 'undefined'){
    window.parse_filename = parse_filename
    window.plan_tracking_pairs = plan_tracking_pairs
}
