// RootDetector-specific hardening for the shared base helper.
fetch_as_blob = async function(url, max_attempts=3){
    let last_error
    for(let attempt = 1; attempt <= max_attempts; attempt += 1){
        try {
            const response = await fetch(url)
            if(response.ok)
                return await response.blob()
            const error = new Error(`Request failed (${response.status}) while loading a result.`)
            error.status = response.status
            throw error
        } catch(error) {
            last_error = error
            const status = Number(error?.status ?? 0)
            const retryable = status == 0 || [408, 425, 429].includes(status) || status >= 500
            if(attempt == max_attempts || !retryable)
                throw error
            await sleep(250 * attempt)
        }
    }
    throw last_error
}
