RootSecurity = class {
    static token = undefined
    static limits = undefined
    static asset_schema = 'rootdetector-web-rc2-1'

    static async initialize(){
        const session = await $.get('/api/session')
        if(session.asset_schema != this.asset_schema){
            const error = new Error(
                'RootDetector browser files do not match the running application. '
                + 'Close old RootDetector tabs, start the intended extracted folder, and reload.'
            )
            error.code = 'asset_schema_mismatch'
            throw error
        }
        this.token = session.token
        this.limits = session.limits
        $.ajaxPrefilter((options, _originalOptions, request) => {
            const method = String(options.method ?? options.type ?? 'GET').toUpperCase()
            const target = new URL(options.url, window.location.href)
            if(target.origin == window.location.origin && !['GET', 'HEAD', 'OPTIONS'].includes(method))
                request.setRequestHeader('X-RootDetector-Token', this.token)
        })
        return session
    }

    static upload_file(file){
        const max_bytes = Number(this.limits?.max_upload_bytes)
        if(Number.isFinite(max_bytes) && max_bytes > 0 && file?.size > max_bytes){
            const limit_mib = Math.floor(max_bytes / (1024 * 1024))
            const error = new Error(
                `${file.name} exceeds the ${limit_mib} MiB file limit. `
                + 'Choose a smaller image or ask a maintainer to adjust the local upload setting.'
            )
            error.code = 'upload_too_large'
            error.status = 413
            throw error
        }
        return upload_file_to_flask(file)
    }

    static request(url, method, data=undefined){
        return $.ajax({
            url: url,
            method: method,
            contentType: data == undefined ? undefined : 'application/json',
            data: data == undefined ? undefined : JSON.stringify(data),
        })
    }

    static error_message(error, fallback='The request could not be completed.'){
        const candidates = [
            error?.responseJSON?.message,
            error?.responseJSON?.error?.message,
            error?.message,
        ]
        if(error?.responseText){
            try {
                const parsed = JSON.parse(error.responseText)
                candidates.push(parsed?.message, parsed?.error?.message)
            } catch(_ignored) {
                if(!String(error.responseText).trim().startsWith('<'))
                    candidates.push(error.responseText)
            }
        }
        if(Number(error?.status) == 0)
            candidates.push(
                'The connection to the local RootDetector process was interrupted. '
                + 'Keep this window open, verify the selected file is still available, and retry.'
            )
        if(error?.statusText && error.statusText != 'error')
            candidates.push(error.statusText)

        for(const candidate of candidates){
            if(typeof candidate == 'string' && candidate.trim()){
                const normalized = candidate.trim()
                if(normalized != '[object Object]')
                    return normalized.slice(0, 2000)
            }
        }
        return fallback
    }

    static async report_client_error(stage, item_id, error){
        const message = this.error_message(error)
        try {
            return await this.request('/api/diagnostics/client', 'POST', {
                stage: stage,
                item_id: item_id ?? '',
                message: message,
                error_type: error?.name ?? error?.constructor?.name ?? '',
                status: Number.isFinite(Number(error?.status)) ? Number(error.status) : undefined,
            })
        } catch(report_error) {
            console.error('Could not record browser diagnostic.', report_error)
            return undefined
        }
    }
}
