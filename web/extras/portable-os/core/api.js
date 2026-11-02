export class ApiError extends Error {
    constructor(message, status) { super(message); this.status = status; }
}
export class Client {
    constructor(store, fetcher = globalThis.fetch.bind(globalThis)) { this.store = store; this.fetcher = fetcher; }
    async request(url, {method = 'GET', body, signal, timeout = 15000} = {}) {
        const controller = new AbortController();
        const abort = () => controller.abort();
        signal?.addEventListener('abort', abort, {once: true});
        if (signal?.aborted) abort();
        const timer = setTimeout(abort, timeout);
        try {
            const headers = method !== 'GET' ? {'X-Pikvm-Share': '1', 'X-Pikvm-Portable': '1'} : {};
            if (body !== undefined) headers['Content-Type'] = body instanceof Blob ? 'application/octet-stream' : 'application/json';
            const response = await this.fetcher(url, {method, credentials: 'same-origin', cache: 'no-store',
                redirect: 'error', signal: controller.signal, headers,
                body: body === undefined ? undefined : body instanceof Blob ? body : JSON.stringify(body)});
            if (response.status === 401) {
                this.store.update({session: 'expired'});
                throw new ApiError('Session PiKVM expirée ou accès refusé. Reconnecte-toi.', response.status);
            }
            if (response.status === 403) {
                // KVMD can also return 403 for an expired token. Distinguish it
                // from a real permission/CSRF denial via the native auth endpoint.
                let expired = url === '/api/auth/check';
                if (!expired) {
                    try {
                        const check = await this.fetcher('/api/auth/check', {credentials: 'same-origin',
                            cache: 'no-store', redirect: 'error', signal: controller.signal});
                        expired = [401, 403].includes(check.status);
                    } catch { /* Unavailable auth is not proof that the cookie expired. */ }
                }
                if (expired) this.store.update({session: 'expired'});
                throw new ApiError(expired ? 'Session PiKVM expirée ; reconnecte-toi.' :
                    'Accès refusé par le service (permission ou protection CSRF).', 403);
            }
            let data;
            try { data = await response.json(); } catch { throw new ApiError('Réponse incompatible avec l’API attendue.', response.status); }
            if (!response.ok || data.ok === false) throw new ApiError(data.error || `Erreur HTTP ${response.status}`, response.status);
            return data;
        } catch (error) {
            if (controller.signal.aborted) throw new ApiError('Délai dépassé ou opération annulée. Vérifie l’état avant de réessayer.', 408);
            throw error;
        } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
    }
    async native(path, params, method = 'GET') {
        return (await this.request('/api/' + path + (params ? '?' + new URLSearchParams(params) : ''), {method})).result;
    }
    async share(path, body, params) {
        return (await this.request('/extras/pikvm-share/api/' + path + (params ? '?' + new URLSearchParams(params) : ''),
            {method: body === undefined ? 'GET' : 'POST', body, timeout: path === 'status' ? 10000 : 150000})).result;
    }
    async system(path, body, params) {
        return (await this.request('/extras/portable-os/api/' + path + (params ? '?' + new URLSearchParams(params) : ''),
            {method: body === undefined ? 'GET' : 'POST', body, timeout: body ? 70000 : 15000})).result;
    }
    wifi(path, body) { return this.request('/extras/wifi-wizard/api/' + path,
        {method: body === undefined ? 'GET' : 'POST', body, timeout: 30000}); }
    folders(action, payload = {}) {
        return this.request('/extras/image-manager/api/image-manager/folders' + (action === 'list' ? '' : '/action'),
            action === 'list' ? {} : {method: 'POST', body: {action, ...payload}}).then(data => data.result);
    }
}

export class Poller {
    constructor(client, store) { this.client = client; this.store = store; this.pending = false; this.timer = null; this.running = false; this.epoch = 0; }
    async refresh() {
        if (this.pending || this.store.data.session === 'expired') return;
        this.pending = true;
        const reads = {msd: () => this.client.native('msd'), share: () => this.client.share('status'),
            network: () => this.client.wifi('status').then(data => data.status),
            battery: () => this.client.wifi('battery').then(data => data.battery),
            system: () => this.client.system('status'), usb: () => this.client.system('usb')};
        await Promise.allSettled(Object.entries(reads).map(async ([name, read]) => {
            try { this.store.resource(name, await read()); }
            catch (error) { this.store.resource(name, null, error.message); }
        }));
        this.pending = false;
    }
    start() {
        if (this.running) return;
        this.running = true;
        const epoch=++this.epoch;
        const tick = async () => {
            await this.refresh();
            if (this.running && this.epoch===epoch && this.store.data.session !== 'expired')
                this.timer = setTimeout(tick, document.hidden ? 45000 : 8000);
        };
        tick();
    }
    stop() { this.running = false; this.epoch++; clearTimeout(this.timer); this.timer = null; }
}
