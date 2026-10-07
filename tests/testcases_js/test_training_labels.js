const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')

const repository = path.resolve(__dirname, '..', '..')
let confirmed = false
const controls = {}
global.$ = selector => ({
    prop(name, value){
        if(value !== undefined) controls[selector + ':' + name] = value
        return this
    },
    attr(){ return this },
    text(){ return this },
    removeClass(){ return this },
    toast(){ return this },
    is(){ return confirmed },
})
global.BaseTraining = class {}
global.GLOBAL = {files: {
    'first.tif': {name: 'first.tif', results: {segmentation: {name: 'prediction.png'}}},
    'second.tif': {name: 'second.tif', results: {segmentation: {name: 'prediction2.png'}}},
}}
const uploads = []
global.RootsFileInput = {
    ensure_uploaded: async file => { uploads.push(file.name) },
}
vm.runInThisContext(
    fs.readFileSync(path.join(repository, 'frontend/roots/training.js'), 'utf8'),
    {filename: 'training.js'},
)

async function test_reviewed_labels_only(){
    assert.deepStrictEqual(RootsTraining.get_selected_files(), [])
    const label = {name: 'first.tif.segmentation.png'}
    RootsTraining.register_imported_label('first.tif', label)
    assert.deepStrictEqual(RootsTraining.get_selected_files(), ['first.tif'])
    assert.strictEqual(controls['#start-training-button:disabled'], true)
    confirmed = true
    RootsTraining.update_number_of_training_files_info()
    assert.strictEqual(controls['#start-training-button:disabled'], false)
    await RootsTraining.upload_training_data(['first.tif'])
    assert.deepStrictEqual(uploads, ['first.tif', label.name])
    RootsTraining.forget_imported_label('first.tif')
    assert.deepStrictEqual(RootsTraining.get_selected_files(), [])
    RootsTraining.clear_imported_labels()
}

async function test_import_does_not_replace_existing_detection(){
    global.BaseFileInput = class {}
    global.File = class {
        constructor(_parts, name){ this.name = name }
    }
    vm.runInThisContext(
        fs.readFileSync(path.join(repository, 'frontend/roots/file_input.js'), 'utf8'),
        {filename: 'file_input.js'},
    )
    const previous = GLOBAL.files['first.tif'].results
    await RootsFileInput.load_result('first.tif', [{name: 'reviewed.png'}])
    assert.strictEqual(GLOBAL.files['first.tif'].results, previous)
    assert.match(RootsTraining.imported_labels.get('first.tif').name, /^training-label-.*\.png$/)
}

test_reviewed_labels_only()
    .then(test_import_does_not_replace_existing_detection)
    .then(() => console.log('Reviewed training label tests passed.'))
    .catch(error => { console.error(error); process.exitCode = 1 })
