const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')


const repository = path.resolve(__dirname, '..', '..')
global.$ = {
    get: async () => ({}),
    ajax: () => ({}),
}
global.BaseFileInput = class {}
global.sleep = async () => {}
global.upload_file_to_flask = undefined

vm.runInThisContext(
    fs.readFileSync(path.join(repository, 'frontend/roots/util.js'), 'utf8'),
    {filename: 'util.js'},
)
vm.runInThisContext(
    fs.readFileSync(path.join(repository, 'frontend/roots/security.js'), 'utf8'),
    {filename: 'security.js'},
)
vm.runInThisContext(
    fs.readFileSync(path.join(repository, 'frontend/roots/file_input.js'), 'utf8'),
    {filename: 'file_input.js'},
)


async function test_error_normalization(){
    assert.strictEqual(
        RootSecurity.error_message({responseJSON: {message: 'Structured failure'}}),
        'Structured failure',
    )
    assert.match(
        RootSecurity.error_message({status: 0}),
        /connection to the local RootDetector process was interrupted/i,
    )
    assert.notStrictEqual(
        RootSecurity.error_message({message: '[object Object]'}),
        '[object Object]',
    )
}


async function test_upload_preflight_uses_session_limit(){
    let transfer_count = 0
    global.upload_file_to_flask = () => {
        transfer_count += 1
        return Promise.resolve({files: []})
    }
    RootSecurity.limits = {max_upload_bytes: 1024}
    const oversized = {name: 'large.tiff', size: 1025}
    assert.throws(
        () => RootSecurity.upload_file(oversized),
        error => error.code === 'upload_too_large' && error.status === 413,
    )
    assert.strictEqual(transfer_count, 0)
    await RootSecurity.upload_file({name: 'small.tiff', size: 1024})
    assert.strictEqual(transfer_count, 1)
    RootSecurity.limits = undefined
}


async function test_boot_recovery(){
    const template = fs.readFileSync(path.join(repository, 'templates/index.html'), 'utf8')
    const inlineScript = template.match(/<script>([\s\S]*?)<\/script>/)?.[1]
    assert(inlineScript, 'RootDetector boot script not found')

    const body = {
        innerHTML: '',
        box: undefined,
        appendChild(box){ this.box = box },
    }
    const context = {
        console: {error(){}},
        document: {
            body,
            createElement: () => ({
                innerHTML: '',
                style: {},
                detail: {textContent: ''},
                setAttribute(){},
                querySelector(){ return this.detail },
            }),
        },
        addEventListener(){},
    }
    context.window = context
    vm.runInNewContext(
        fs.readFileSync(path.join(repository, 'frontend/roots/security.js'), 'utf8'),
        context,
    )
    vm.runInNewContext(inlineScript, context)

    context.RootDetectorApp = {init: async () => { throw {status: 0, message: '[object Object]'} }}
    await context.RootDetectorBoot.start()
    assert.match(body.box.innerHTML, /RootDetector is not reachable/)
    assert.match(body.box.innerHTML, /StartRootDetector\.bat/)
    assert.doesNotMatch(body.box.detail.textContent, /\[object Object\]/)

    context.RootDetectorApp = {init: async () => {
        const error = new Error('Browser version does not match')
        error.code = 'asset_schema_mismatch'
        throw error
    }}
    await context.RootDetectorBoot.start()
    assert.match(body.box.innerHTML, /different RootDetector version/)
    assert.strictEqual(body.box.detail.textContent, 'Browser version does not match')

    context.RootDetectorApp = {init: async () => { throw {message: 'Model setup failed'} }}
    await context.RootDetectorBoot.start()
    assert.match(body.box.innerHTML, /could not initialize this page/)
    assert.strictEqual(body.box.detail.textContent, 'Model setup failed')

    context.$ = {get: async () => ({asset_schema: 'old-version'})}
    await assert.rejects(
        context.RootSecurity.initialize(),
        error => error.code === 'asset_schema_mismatch',
    )

    context.RootDetectorBoot.failed_assets.push('/roots/pipeline.js')
    delete context.RootDetectorApp
    delete context.RootSecurity
    await context.RootDetectorBoot.start()
    assert.match(body.box.innerHTML, /could not load its browser files/)
    assert.match(body.box.detail.textContent, /Missing: \/roots\/pipeline\.js/)
    assert.doesNotMatch(body.box.innerHTML, /Start RootDetector\.bat/)
}


async function test_result_fetch_retry(){
    let calls = 0
    global.fetch = async () => {
        calls += 1
        if(calls == 1)
            throw new TypeError('temporary connection failure')
        return {ok: true, status: 200, blob: async () => 'result-blob'}
    }
    assert.strictEqual(await fetch_as_blob('/images/result.png'), 'result-blob')
    assert.strictEqual(calls, 2)

    calls = 0
    global.fetch = async () => {
        calls += 1
        return {ok: false, status: 404}
    }
    await assert.rejects(fetch_as_blob('/images/missing.png'), /\(404\)/)
    assert.strictEqual(calls, 1)
}


async function test_item_71_resume(){
    RootsFileInput.reset_uploaded_files()
    const files = Array.from({length: 86}, (_value, index) => ({
        name: `image-${String(index + 1).padStart(2, '0')}.tiff`,
        size: 1000 + index,
        lastModified: 1234,
        type: 'image/tiff',
    }))
    const attempts = new Map()
    let fail_item_71 = true
    global.upload_file_to_flask = file => {
        const attempt = (attempts.get(file.name) ?? 0) + 1
        attempts.set(file.name, attempt)
        if(file == files[70] && fail_item_71)
            return Promise.reject({status: 0})
        return Promise.resolve({files: [{name: file.name}]})
    }

    for(const file of files.slice(0, 70))
        await RootsFileInput.ensure_uploaded(file)
    await assert.rejects(
        RootsFileInput.ensure_uploaded(files[70], {max_attempts: 3}),
    )
    assert.strictEqual(attempts.get(files[70].name), 3)

    fail_item_71 = false
    for(const file of files)
        await RootsFileInput.ensure_uploaded(file)

    for(const file of files.slice(0, 70))
        assert.strictEqual(attempts.get(file.name), 1)
    assert.strictEqual(attempts.get(files[70].name), 4)
    assert.strictEqual(attempts.get(files[85].name), 1)
}


Promise.resolve()
    .then(test_error_normalization)
    .then(test_upload_preflight_uses_session_limit)
    .then(test_boot_recovery)
    .then(test_result_fetch_retry)
    .then(test_item_71_resume)
    .then(() => console.log('Browser-side upload reliability tests passed.'))
    .catch(error => {
        console.error(error)
        process.exitCode = 1
    })
