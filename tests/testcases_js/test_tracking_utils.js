const assert = require('assert')
const fs = require('fs')
const path = require('path')


const repository = path.resolve(__dirname, '..', '..')
const source = fs.readFileSync(
    path.join(repository, 'frontend/roots/tracking_utils.js'),
    'utf8',
)


async function load_tracking_utils(){
    return await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
}


async function test_parse_filename(tracking_utils){
    const filenames = {
        'DE_T027_L003_09.07.20_111637_001_JS.tiff':         {date:new Date(2020, 7-1, 9)},
        'DE_T027_L003_09.07.2015_111637_001_JS.tiff':       {date:new Date(2015, 7-1, 9)},
        'XXX Scanns_T009_L001_03.07.18_082024_003_SB.tiff': {date:new Date(2018, 7-1, 3)},
        'XXX_Scanns_T009_L001_03.07.18_082024_003_SB.tiff': {date:new Date(2018, 7-1, 3)},
        'invalid_filename.tiff':                            {date:new Date(NaN)},
    }

    for(const [filename, expected] of Object.entries(filenames)){
        const parsed  =   tracking_utils.parse_filename(filename)

        if( isFinite(expected.date.getTime()) )
            assert.strictEqual(parsed.date.getTime(), expected.date.getTime())
        else
            assert(Number.isNaN(parsed.date.getTime()))
    }
    assert(Number.isNaN(tracking_utils.parse_filename('site_31.02.24.tif').date.getTime()))
}


async function test_pairing_key(tracking_utils){
    const first = tracking_utils.parse_filename('site_T001_L001_01.04.24_101500.tif')
    const second = tracking_utils.parse_filename('site_T001_L001_15.04.24_101500.tif')
    const otherSite = tracking_utils.parse_filename('site_T002_L001_15.04.24_101500.tif')

    assert.strictEqual(first.base, second.base)
    assert.notStrictEqual(first.base, otherSite.base)
}


async function test_valid_consecutive_pairs(tracking_utils){
    const files = [
        'site_T001_L001_30.04.24_101500.tif',
        'site_T002_L001_15.04.24_101500.tif',
        'site_T001_L001_01.04.24_101500.tif',
        'site_T001_L001_15.04.24_101500.tif',
    ]
    const plan = tracking_utils.plan_tracking_pairs(files)
    assert.deepStrictEqual(plan.pairs, [
        [files[2], files[3]],
        [files[3], files[0]],
    ])
    assert.deepStrictEqual(plan.issues, [])
}


async function test_same_day_duplicates_are_not_paired(tracking_utils){
    const files = [
        'Ref_T019_L001_13.04.26_114918_001_Untitled.tiff',
        'Ref_T019_L001_13.04.26_115454_001_Untitled.tiff',
        'Ref_T021_L001_13.04.26_113424_001_Untitled.tiff',
        'Ref_T021_L001_13.04.26_114654_001_Untitled.tiff',
    ]
    const plan = tracking_utils.plan_tracking_pairs(files)
    assert.deepStrictEqual(plan.pairs, [])
    assert.strictEqual(plan.issues.length, 2)
    assert(plan.issues.every(issue => issue.code == 'duplicate_date'))
    assert(plan.issues.every(issue => issue.date == '2026-04-13'))
}


async function test_invalid_dates_are_reported(tracking_utils){
    const plan = tracking_utils.plan_tracking_pairs([
        'invalid_filename.tiff',
        'site_T001_L001_31.02.24_101500.tif',
    ])
    assert.deepStrictEqual(plan.pairs, [])
    assert.deepStrictEqual(
        plan.issues.map(issue => issue.code),
        ['invalid_date', 'invalid_date'],
    )
}


async function test_windows_acceptance_fixture_names(tracking_utils){
    const stressFiles = []
    for(let site = 1; site <= 5; site += 1){
        const siteName = String(site).padStart(3, '0')
        stressFiles.push(
            `RDTEST_STRESS_S${siteName}_15.04.2026_OBS3.tiff`,
            `RDTEST_STRESS_S${siteName}_01.04.2026_OBS1.tiff`,
            `RDTEST_STRESS_S${siteName}_08.04.2026_OBS2.tiff`,
        )
    }
    const stressPlan = tracking_utils.plan_tracking_pairs(stressFiles)
    assert.strictEqual(stressPlan.pairs.length, 10)
    assert.deepStrictEqual(stressPlan.issues, [])

    const stablePlan = tracking_utils.plan_tracking_pairs([
        'RDTEST_STABLE_S001_15.04.2026_OBS3.tiff',
        'RDTEST_STABLE_S001_01.04.2026_OBS1.tiff',
        'RDTEST_STABLE_S001_08.04.2026_OBS2.tiff',
    ])
    assert.deepStrictEqual(stablePlan.pairs, [
        [
            'RDTEST_STABLE_S001_01.04.2026_OBS1.tiff',
            'RDTEST_STABLE_S001_08.04.2026_OBS2.tiff',
        ],
        [
            'RDTEST_STABLE_S001_08.04.2026_OBS2.tiff',
            'RDTEST_STABLE_S001_15.04.2026_OBS3.tiff',
        ],
    ])

    const edgePlan = tracking_utils.plan_tracking_pairs([
        'RDTEST_DUPLICATE_S001_08.04.2026_OBS1.tiff',
        'RDTEST_DUPLICATE_S001_08.04.2026_OBS2.tiff',
        'RDTEST_DUPLICATE_S001_15.04.2026_OBS3.tiff',
        'RDTEST_INVALID_S001_31.02.2026_OBS1.tiff',
    ])
    assert.deepStrictEqual(edgePlan.pairs, [])
    assert.deepStrictEqual(
        edgePlan.issues.map(issue => issue.code).sort(),
        ['duplicate_date', 'invalid_date'],
    )
}


async function test_rhizotron_producer_names_keep_levels_separate(tracking_utils){
    const pilotFiles = [
        '04_L003_22.08.2026_110357_IMG_0003.JPG',
        '04_L001_21.08.2026_110358_IMG_0001.JPG',
        '04_L002_22.08.2026_110356_IMG_0002.JPG',
        '04_L003_21.08.2026_110359_IMG_0003.JPG',
        '04_L001_22.08.2026_110355_IMG_0001.JPG',
        '04_L002_21.08.2026_110358_IMG_0002.JPG',
    ]
    const pilotPlan = tracking_utils.plan_tracking_pairs(pilotFiles)
    assert.deepStrictEqual(pilotPlan.pairs, [
        [pilotFiles[1], pilotFiles[4]],
        [pilotFiles[5], pilotFiles[2]],
        [pilotFiles[3], pilotFiles[0]],
    ])
    assert.deepStrictEqual(pilotPlan.issues, [])

    const qualificationFiles = [
        '04_L003_25.08.2026_110357_IMG_0003.JPG',
        '04_L001_21.08.2026_110358_IMG_0001.JPG',
        '04_L002_24.08.2026_110356_IMG_0002.JPG',
        '04_L003_22.08.2026_110357_IMG_0003.JPG',
        '04_L001_25.08.2026_110356_IMG_0001.JPG',
        '04_L002_21.08.2026_110358_IMG_0002.JPG',
        '04_L003_23.08.2026_110357_IMG_0003.JPG',
        '04_L001_22.08.2026_110355_IMG_0001.JPG',
        '04_L002_25.08.2026_110357_IMG_0002.JPG',
        '04_L003_21.08.2026_110359_IMG_0003.JPG',
        '04_L001_24.08.2026_110356_IMG_0001.JPG',
        '04_L002_22.08.2026_110356_IMG_0002.JPG',
        '04_L003_24.08.2026_110357_IMG_0003.JPG',
        '04_L001_23.08.2026_110356_IMG_0001.JPG',
        '04_L002_23.08.2026_110357_IMG_0002.JPG',
    ]
    const qualificationPlan = tracking_utils.plan_tracking_pairs(qualificationFiles)
    assert.strictEqual(qualificationPlan.pairs.length, 12)
    assert.deepStrictEqual(qualificationPlan.issues, [])
    assert(qualificationPlan.pairs.every(([first, second]) => (
        tracking_utils.parse_filename(first).base
        == tracking_utils.parse_filename(second).base
    )))
    assert(qualificationPlan.pairs.every(([first, second]) => (
        tracking_utils.parse_filename(first).date
        < tracking_utils.parse_filename(second).date
    )))
}


load_tracking_utils()
    .then(async tracking_utils => {
        await test_parse_filename(tracking_utils)
        await test_pairing_key(tracking_utils)
        await test_valid_consecutive_pairs(tracking_utils)
        await test_same_day_duplicates_are_not_paired(tracking_utils)
        await test_invalid_dates_are_reported(tracking_utils)
        await test_windows_acceptance_fixture_names(tracking_utils)
        await test_rhizotron_producer_names_keep_levels_separate(tracking_utils)
    })
    .then(() => console.log('Tracking filename and pairing tests passed.'))
    .catch(error => {
        console.error(error)
        process.exitCode = 1
    })
