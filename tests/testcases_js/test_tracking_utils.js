import { assert }               from "https://deno.land/std@0.149.0/testing/asserts.ts";
import * as tracking_utils      from "../../frontend/roots/tracking_utils.js"



Deno.test('tracking.parse_filename', () => {
    const filenames = {
        'DE_T027_L003_09.07.20_111637_001_JS.tiff':         {date:new Date(2020, 7-1, 9)},
        'DE_T027_L003_09.07.2015_111637_001_JS.tiff':       {date:new Date(2015, 7-1, 9)},
        'XXX Scanns_T009_L001_03.07.18_082024_003_SB.tiff': {date:new Date(2018, 7-1, 3)},
        'XXX_Scanns_T009_L001_03.07.18_082024_003_SB.tiff': {date:new Date(2018, 7-1, 3)},
        'invalid_filename.tiff':                            {date:new Date(NaN)},
    }

    for(const [filename, expected] of Object.entries(filenames)){
        const parsed  =   tracking_utils.parse_filename(filename)

        console.log(filename, parsed.date, expected.date)
        if( isFinite(expected.date.getTime()) )
            assert( parsed.date.getTime() == expected.date.getTime() )
        else
            assert( isNaN(parsed.date.getTime()) )
    }
    //assert (0)
})
