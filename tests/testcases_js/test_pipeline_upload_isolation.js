const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')


const repository = path.resolve(__dirname, '..', '..')
global.$ = () => ({hasClass: () => false})
global.GLOBAL = {
    files: {
        'first.tiff': {name: 'first.tiff'},
        'broken.tiff': {name: 'broken.tiff'},
        'last.tiff': {name: 'last.tiff'},
    },
}
global.RootSecurity = {
    error_message: error => error.responseJSON?.message ?? error.message,
}
global.RootTracking = {
    get_file_pairs: () => [
        ['first.tiff', 'broken.tiff'],
        ['first.tiff', 'last.tiff'],
    ],
}
global.App = {Detection: {set_failed: () => {}}}
global.sleep = async () => {}

vm.runInThisContext(
    fs.readFileSync(path.join(repository, 'frontend/roots/pipeline.js'), 'utf8'),
    {filename: 'pipeline.js'},
)


async function test_failed_upload_is_excluded_without_aborting(){
    const uploadRows = []
    const failedCards = []
    let requestBody

    RootsFileInput = {
        ensure_uploaded: async file => {
            if(file.name == 'broken.tiff')
                throw {responseJSON: {message: 'Unreadable TIFF'}}
            return {skipped: false, attempts: 1}
        },
    }
    App.Detection.set_failed = filename => failedCards.push(filename)
    RootPipeline.set_running = () => {}
    RootPipeline.show_modal = function(){
        this.upload_failures = new Map()
        this.excluded_pairs = []
    }
    RootPipeline.set_message = () => {}
    RootPipeline.set_progress = () => {}
    RootPipeline.render_upload = (filename, state, details) => {
        uploadRows.push({filename, state, details})
    }
    RootPipeline.show_error = message => assert.fail(message)
    RootPipeline.request = async (_url, _method, body) => {
        requestBody = body
        return {id: 'run-1'}
    }
    RootPipeline.poll_until_finished = async () => {}

    await RootPipeline.on_run_analysis({preventDefault: () => {}})

    assert.deepStrictEqual(requestBody.filenames, ['first.tiff', 'last.tiff'])
    assert.deepStrictEqual(requestBody.file_pairs, [['first.tiff', 'last.tiff']])
    assert.deepStrictEqual(failedCards, ['broken.tiff'])
    assert.strictEqual(RootPipeline.upload_failures.get('broken.tiff'), 'Unreadable TIFF')
    assert.deepStrictEqual(
        RootPipeline.excluded_pairs.map(item => [item.filename0, item.filename1, item.state]),
        [['first.tiff', 'broken.tiff', 'skipped']],
    )
    assert(uploadRows.some(row => row.filename == 'broken.tiff' && row.state == 'failed'))
}


Promise.resolve()
    .then(test_failed_upload_is_excluded_without_aborting)
    .then(() => console.log('Pipeline upload-isolation tests passed.'))
    .catch(error => {
        console.error(error)
        process.exitCode = 1
    })
