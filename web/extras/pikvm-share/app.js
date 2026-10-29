(() => {
    'use strict';
    const base = '/extras/pikvm-share/api/';
    const $ = id => document.getElementById(id);
    let folder = '', state = null, busy = false, uploading = false, cancelled = false;
    const sizes = bytes => {
        if (bytes === 0) return '0 o';
        const i = Math.min(3, Math.floor(Math.log(bytes) / Math.log(1024)));
        return `${(bytes / 1024 ** i).toLocaleString('fr-FR', {maximumFractionDigits: 1})} ${['o', 'Kio', 'Mio', 'Gio'][i]}`;
    };
    async function api(action, body, query = '') {
        const options = {credentials: 'same-origin', cache: 'no-store', redirect: 'error'};
        if (body !== undefined) {
            options.method = 'POST';
            options.headers = {'X-Pikvm-Share': '1', 'Content-Type': body instanceof Blob ? 'application/octet-stream' : 'application/json'};
            options.body = body instanceof Blob ? body : JSON.stringify(body);
        }
        const response = await fetch(base + action + query, options);
        if (response.status === 401 || response.status === 403) throw new Error('Session expirée ou accès refusé. Reconnecte-toi depuis la page PiKVM.');
        let result;
        try { result = await response.json(); } catch { throw new Error(`Réponse inattendue (HTTP ${response.status}).`); }
        if (!response.ok || !result.ok) throw new Error(result.error || `Erreur HTTP ${response.status}`);
        return result.result;
    }
    function showError(error) { $('error').textContent = error.message || String(error); $('error').hidden = false; }
    function controls() {
        const web = state?.mode === 'web';
        for (const id of ['mkdir', 'create-file', 'upload']) $(id).disabled = !web || busy || uploading;
        $('usb').disabled = busy || uploading || !state || ['usb', 'error'].includes(state.mode);
        $('web').disabled = busy || uploading || !state || web || state.mode === 'error' || !$('ejected').checked;
        $('recover').disabled = busy || uploading || !state || state.attached;
        $('refresh').disabled = busy;
    }
    async function run(work) {
        if (busy || uploading) return;
        busy = true; $('error').hidden = true; controls();
        try { await work(); } catch (error) { showError(error); }
        finally { busy = false; await refresh().catch(showError); controls(); }
    }
    function button(label, action, className = '') {
        const element = document.createElement('button');
        element.type = 'button'; element.textContent = label; element.className = className;
        element.addEventListener('click', action);
        return element;
    }
    function breadcrumbs() {
        const nav = $('breadcrumbs'); nav.replaceChildren();
        nav.append(button('PIKVM-SHARE', () => run(async () => { folder = ''; })));
        let prefix = '';
        for (const part of folder.split('/').filter(Boolean)) {
            prefix += (prefix ? '/' : '') + part;
            const dest = prefix;
            nav.append(document.createTextNode('/'), button(part, () => run(async () => { folder = dest; })));
        }
    }
    async function renderFiles() {
        const data = await api('files', undefined, '?' + new URLSearchParams({path: folder}));
        breadcrumbs(); $('entries').replaceChildren();
        for (const entry of data.items) {
            const path = folder ? `${folder}/${entry.name}` : entry.name;
            const row = document.createElement('tr');
            const cells = Array.from({length: 4}, () => document.createElement('td'));
            if (entry.directory) cells[0].append(button(`📁 ${entry.name}`, () => run(async () => { folder = path; }), 'name'));
            else cells[0].textContent = entry.name;
            cells[1].textContent = entry.directory ? 'Dossier' : sizes(entry.size);
            cells[2].textContent = new Date(entry.modified * 1000).toLocaleString('fr-FR');
            const actions = document.createElement('div'); actions.className = 'buttons';
            if (!entry.directory) {
                const link = document.createElement('a'); link.textContent = 'Télécharger';
                link.href = base + 'download?' + new URLSearchParams({path});
                link.setAttribute('download', entry.name); actions.append(link);
            }
            actions.append(button('Renommer', () => run(async () => {
                const name = prompt('Nouveau nom :', entry.name);
                if (name && name !== entry.name) await api('rename', {path, name});
            })), button('Supprimer', () => run(async () => {
                if (confirm(`Supprimer ${entry.directory ? 'le dossier vide' : 'le fichier'} « ${entry.name} » ?`)) await api('delete', {path});
            })));
            cells[3].append(actions); row.append(...cells); $('entries').append(row);
        }
        if (!data.items.length) {
            const row = document.createElement('tr'), cell = document.createElement('td');
            cell.colSpan = 4; cell.textContent = 'Ce dossier est vide.'; row.append(cell); $('entries').append(row);
        }
        if (data.space) {
            $('space').textContent = `${sizes(data.space.used)} utilisés · ${sizes(data.space.free)} disponibles / ${sizes(data.space.total)}`;
            $('usage').max = data.space.total; $('usage').value = data.space.used; $('usage').hidden = false;
        }
    }
    async function refresh() {
        state = await api('status');
        const names = {usb: 'USB connecté', detached: 'Lecteur détaché', web: 'Gestion Web', error: 'Vérification requise'};
        $('badge').textContent = names[state.mode] || state.mode;
        $('state-text').textContent = state.message || '';
        $('mode-help').textContent = state.mode === 'usb' ? 'Éjecte PIKVM-SHARE depuis le système du PC avant de passer en gestion Web.' :
            state.mode === 'web' ? 'Les fichiers sont accessibles ici. Termine les transferts avant de reconnecter le lecteur au PC.' :
            'Pour monter le volume, confirme son éjection propre côté PC. En cas d’erreur, récupère d’abord le montage.';
        if (state.mode === 'web') await renderFiles();
        else {
            $('entries').replaceChildren(); const row = document.createElement('tr'), cell = document.createElement('td');
            cell.colSpan = 4; cell.textContent = 'Fichiers accessibles uniquement en mode Web.'; row.append(cell); $('entries').append(row);
            $('breadcrumbs').replaceChildren(); $('usage').hidden = true;
            $('space').textContent = 'Espace disponible en mode Web';
        }
        controls();
    }
    for (const action of ['mkdir', 'create-file']) $(action).addEventListener('click', () => run(async () => {
        const name = prompt(action === 'mkdir' ? 'Nom du dossier :' : 'Nom du fichier vide :');
        if (name) await api(action, {parent: folder, name});
    }));
    $('usb').addEventListener('click', () => run(async () => { await api('mode/usb', {}); $('ejected').checked = false; }));
    $('web').addEventListener('click', () => run(async () => { await api('mode/web', {ejected: $('ejected').checked}); folder = ''; }));
    $('recover').addEventListener('click', () => run(async () => {
        if (confirm('Démonter le volume Web et libérer la réservation SHARE ? Les imports en attente seront annulés.')) await api('recover', {});
    }));
    $('ejected').addEventListener('change', controls);
    $('refresh').addEventListener('click', () => run(async () => {}));
    $('upload').addEventListener('click', () => $('file-input').click());
    $('cancel').addEventListener('click', () => { cancelled = true; $('transfer-text').textContent = 'Annulation après le bloc en cours…'; });
    $('file-input').addEventListener('change', async event => {
        if (uploading || busy) return;
        const files = Array.from(event.target.files); event.target.value = '';
        if (!files.length) return;
        uploading = true; cancelled = false; $('error').hidden = true; $('transfer').hidden = false; controls();
        try {
            for (const file of files) {
                if (cancelled) break;
                const upload = await api('upload/begin', {parent: folder, name: file.name, size: file.size});
                let finished = false;
                try {
                    let offset = 0;
                    while (offset < file.size && !cancelled) {
                        $('transfer-text').textContent = `Import de ${file.name} · ${sizes(offset)} / ${sizes(file.size)}`;
                        const chunk = file.slice(offset, offset + 1024 ** 2);
                        const result = await api('upload/chunk', chunk, '?' + new URLSearchParams({id: upload.id, offset}));
                        offset = result.offset; $('progress').value = file.size ? offset / file.size * 100 : 100;
                    }
                    if (!cancelled) { await api('upload/finish', {id: upload.id}); finished = true; }
                } finally {
                    if (!finished) await api('upload/cancel', {id: upload.id}).catch(showError);
                }
            }
        } catch (error) { showError(error); }
        finally { uploading = false; $('transfer').hidden = true; await refresh().catch(showError); controls(); }
    });
    window.addEventListener('beforeunload', event => { if (uploading) { event.preventDefault(); event.returnValue = ''; } });
    setInterval(() => { if (!busy && !uploading) refresh().catch(showError); }, 7000);
    refresh().catch(error => { state = null; controls(); showError(error); });
})();
