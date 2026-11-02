import {el, button, badge, card, row, hint, table, empty, dialog, notify} from '../core/ui.js';
import {bytes, shareModes, relativePath, visibleImages, usbEvidence} from '../core/state.js';

export function storageModule(shareMode) {
    return {id: shareMode ? 'share' : 'images', title: shareMode ? 'PIKVM-SHARE' : 'Images & Drive 0',
        subtitle: shareMode ? 'Drive 1 · Fichiers de la clé USB virtuelle' : 'Bibliothèque ISO / IMG / RAW · Lecteur natif',
        icon: shareMode ? 'usb' : 'storage', group: 'STOCKAGE & USB', mount(outlet, ctx) {
        const {api, store, action} = ctx;
        let folder = '', live = true, currentItems = [], uploadCancel = false, activeXhr = null;
        const state = el('div', {class: 'device-state'}), space = el('span', {class: 'muted'}),
            crumbs = el('nav', {class: 'crumbs', 'aria-label': 'Dossier actuel'}), list = el('div');
        const transferLabel = el('span'), progress = el('progress', {max: 100, value: 0});
        const transfer = el('div', {class: 'transfer', hidden: true}, transferLabel, progress,
            button('Annuler', () => { uploadCancel = true; activeXhr?.abort(); }, 'quiet'));
        function status() {
            state.replaceChildren();
            if (shareMode) {
                const share = store.get('share');
                state.append(badge(shareModes[share?.mode] || 'État indisponible', share?.mode === 'web' ? 'green' : ''),
                    hint(share?.message || usbEvidence(store.get('usb'))));
            } else {
                const msd = store.get('msd');
                state.append(badge(msd?.drive?.connected ? 'Connecté au PC' : 'Détaché'),
                    hint(msd?.drive?.image?.name || 'Aucune image sélectionnée'));
            }
        }
        function breadcrumbs() {
            crumbs.replaceChildren(button('/', () => action(async () => { folder = ''; await load(); })));
            let prefix = '';
            for (const name of folder.split('/').filter(Boolean)) {
                prefix = relativePath(prefix, name); const target = prefix;
                crumbs.append(el('span', {}, '/'), button(name, () => action(async () => { folder = target; await load(); })));
            }
        }
        const canEdit = () => shareMode ? store.get('share')?.mode === 'web' : !store.get('msd')?.drive?.connected;
        async function refreshStatus() {
            store.resource(shareMode ? 'share' : 'msd', shareMode ? await api.share('status') : await api.native('msd'));
            if (shareMode) {
                try { store.resource('usb', await api.system('usb')); }
                catch (error) { store.resource('usb', null, error.message); }
            }
            status();
        }
        async function create(kind) {
            if (!canEdit()) throw new Error('Détache le lecteur ou passe en gestion Web avant de modifier les fichiers.');
            const values = await dialog({title: kind === 'mkdir' ? 'Nouveau dossier' : 'Nouveau fichier',
                message: 'Le nom doit être compatible avec le système de fichiers.', fields: [{name: 'name', label: 'Nom'}]});
            if (!values) return;
            if (shareMode) await api.share(kind, {...values, parent: folder});
            else await api.folders('mkdir', {...values, parent: folder});
            await load();
        }
        async function rename(entry) {
            const values = await dialog({title: 'Renommer', fields: [{name: 'name', label: 'Nouveau nom', value: entry.name}]});
            if (!values || values.name === entry.name) return;
            if (shareMode) await api.share('rename', {path: entry.path, name: values.name});
            else await api.folders(entry.directory ? 'rename_dir' : 'rename_file',
                entry.directory ? {path: entry.path, name: values.name} : {source: entry.path, name: values.name});
            await load();
        }
        async function remove(entry) {
            if (!await dialog({title: 'Supprimer « ' + entry.name + ' » ?',
                message: entry.directory ? 'Le dossier doit être vide. Cette action est irréversible.' : 'Cette action est irréversible.',
                confirm: 'Supprimer', danger: true})) return;
            if (shareMode) await api.share('delete', {path: entry.path});
            else if (entry.directory) await api.folders('rmdir', {path: entry.path});
            else await api.native('msd/remove', {image: entry.path}, 'POST');
            await load();
        }
        async function select(entry) {
            if (!canEdit()) throw new Error('Déconnecte le Drive 0 avant de sélectionner une image.');
            await api.native('msd/set_params', {image: entry.path, cdrom: /\.iso$/i.test(entry.name) ? 1 : 0, rw: 0}, 'POST');
            await refreshStatus(); notify('Image sélectionnée dans le Drive 0.');
        }
        async function move(entry) {
            const folders = await api.folders('list');
            const values = await dialog({title: 'Déplacer l’image', fields: [{name: 'folder', type: 'select',
                label: 'Dossier de destination', options: ['', ...folders.folders], required: false}]});
            if (values) { await api.folders('move_file', {source: entry.path, folder: values.folder}); await load(); }
        }
        function render() {
            if (!live) return;
            breadcrumbs();
            if (!currentItems.length) { list.replaceChildren(empty('Ce dossier est vide.')); return; }
            list.replaceChildren(table(['Nom', 'Taille', 'Actions'], currentItems.map(entry => {
                const name = entry.directory ? button(entry.name, () => action(async () => { folder = entry.path; await load(); }), 'file-name') : el('span', {}, entry.name);
                const operations = [];
                if (!entry.directory) {
                    operations.push(el('a', {class: 'button quiet', download: entry.name,
                        href: (shareMode ? '/extras/pikvm-share/api/download?' : '/api/msd/read?') +
                            new URLSearchParams(shareMode ? {path: entry.path} : {image: entry.path})}, 'Télécharger'));
                    if (!shareMode) operations.push(button('Sélectionner', () => action(() => select(entry)), 'quiet'),
                        button('Déplacer', () => action(() => move(entry)), 'quiet'));
                }
                operations.push(button('Renommer', () => action(() => rename(entry)), 'quiet', {disabled: !canEdit(), 'aria-label': 'Renommer ' + entry.name}),
                    button('Supprimer', () => action(() => remove(entry)), 'quiet', {disabled: !canEdit(), 'aria-label': 'Supprimer ' + entry.name}));
                return [row(el('span', {class: 'file-icon', 'aria-hidden': 'true'}, entry.directory ? '▰' : '▱'), name),
                    entry.directory ? 'Dossier' : bytes(entry.size), row(...operations)];
            })));
        }
        async function load() {
            await refreshStatus();
            if (shareMode) {
                if (store.get('share')?.mode !== 'web') {
                    if (live) { list.replaceChildren(empty('Éjecte proprement le lecteur côté PC, puis passe en gestion Web.')); crumbs.replaceChildren(); space.textContent = 'Espace exFAT disponible en mode Web'; }
                    return;
                }
                const data = await api.share('files', undefined, {path: folder});
                currentItems = data.items.map(entry => ({...entry, path: relativePath(folder, entry.name)}));
                if (live) space.textContent = data.space ? `${bytes(data.space.used)} utilisés · ${bytes(data.space.free)} disponibles` : 'Espace indisponible';
            } else {
                const msd = store.get('msd'), folders = await api.folders('list');
                const prefix = folder ? folder + '/' : '';
                currentItems = visibleImages(msd).filter(([name]) => name.startsWith(prefix) && !name.slice(prefix.length).includes('/'))
                    .map(([path, item]) => ({name: path.slice(prefix.length), path, directory: false, size: item.size}));
                currentItems.unshift(...folders.folders.filter(path => path.startsWith(prefix) && !path.slice(prefix.length).includes('/'))
                    .map(path => ({name: path.slice(prefix.length), path, directory: true})));
                const part = msd?.storage?.parts?.[''];
                if (live) space.textContent = part ? `${bytes(part.free)} disponibles / ${bytes(part.size)}` : 'Stockage natif indisponible';
            }
            render();
        }
        async function uploadShare(file) {
            const upload = await api.share('upload/begin', {parent: folder, name: file.name, size: file.size});
            let finished = false, failure;
            try {
                let offset = 0;
                while (offset < file.size && !uploadCancel) {
                    const result = await api.share('upload/chunk', file.slice(offset, offset + 1024 ** 2), {id: upload.id, offset});
                    offset = result.offset; progress.value = file.size ? offset / file.size * 100 : 100;
                }
                if (!uploadCancel) { await api.share('upload/finish', {id: upload.id}); finished = true; }
            } catch (error) { failure = error; throw error; }
            finally {
                if (!finished) {
                    try { await api.share('upload/cancel', {id: upload.id}); }
                    catch (error) {
                        if (!failure) throw error;
                        notify('Nettoyage de l’import non confirmé ; utiliser Récupérer si nécessaire.', true);
                    }
                }
            }
        }
        function uploadImage(file) {
            if (!/\.(iso|img|raw)$/i.test(file.name)) throw new Error('Formats autorisés : ISO, IMG et RAW.');
            return new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest(); activeXhr = xhr;
                xhr.open('POST', '/api/msd/write?' + new URLSearchParams({image: file.name, prefix: folder, remove_incomplete: 1}));
                xhr.withCredentials = true; xhr.setRequestHeader('Content-Type', 'application/octet-stream');
                xhr.setRequestHeader('X-Pikvm-Portable', '1');
                xhr.upload.onprogress = event => { if (event.lengthComputable) progress.value = event.loaded / event.total * 100; };
                xhr.onload = () => {
                    try { const data = JSON.parse(xhr.responseText); if (xhr.status !== 200 || !data.ok) throw new Error(data.error || 'Import refusé.'); resolve(); }
                    catch (error) { reject(error); }
                };
                xhr.onerror = () => reject(new Error('Liaison interrompue ; vérifie les images incomplètes.'));
                xhr.timeout = 30 * 60 * 1000;
                xhr.ontimeout = () => reject(new Error('Délai d’import dépassé ; vérifie les images incomplètes.'));
                xhr.onabort = () => reject(new Error('Import annulé ; un fichier incomplet peut rester dans le stockage natif.'));
                xhr.onloadend = () => { activeXhr = null; }; xhr.send(file);
            });
        }
        const fileInput = el('input', {type: 'file', multiple: true, hidden: true, onchange: () => action(async () => {
            const files = [...fileInput.files]; fileInput.value = '';
            if (!canEdit()) throw new Error('Lecteur connecté ou mode Web indisponible.');
            uploadCancel = false; transfer.hidden = false; store.update({transfer: 'Import en cours'});
            try { for (const file of files) { if (uploadCancel) break; transferLabel.textContent = file.name; progress.value = 0; await (shareMode ? uploadShare(file) : uploadImage(file)); } }
            finally {
                store.update({transfer: null}); transfer.hidden = true;
                try { await load(); } catch (error) { notify('Actualisation après transfert : ' + error.message, true); }
            }
        })});
        const modes = shareMode ? row(
            button('Gestion Web', () => action(async () => {
                const values = await dialog({title: 'Passer en gestion Web', message: 'Éjecte proprement PIKVM-SHARE dans le système du PC. Débrancher le câble ne suffit pas.',
                    fields: [{name: 'ejected', type: 'checkbox', label: 'J’ai éjecté proprement le lecteur côté PC.'}], confirm: 'Monter pour le Web'});
                if (values) { await api.share('mode/web', values); folder = ''; await load(); }
            }), 'primary'),
            button('Connecter en USB', () => action(async () => {
                if (await dialog({title: 'Connecter PIKVM-SHARE au PC', message: 'Le volume Web sera démonté avant la connexion USB. Le montage dans Windows n’est pas garanti par cet état.', confirm: 'Connecter'})) {
                    await api.share('mode/usb', {}); await load();
                }
            })), button('Démonter / récupérer', () => action(async () => {
                if (await dialog({title: 'Récupérer le volume', message: 'Le lecteur doit être éjecté côté PC. Les imports partiels seront annulés ; aucune éjection USB ne sera forcée.'})) {
                    await api.share('recover', {}); await load();
                }
            }), 'quiet')) : row(
            button('Connecter l’image', () => action(async () => {
                await api.native('msd/set_connected', {connected: 1}, 'POST'); await load();
            }), 'primary'), button('Déconnecter le Drive 0', () => action(async () => {
                if (await dialog({title: 'Déconnecter le Drive 0', message: 'Si le lecteur était utilisé en écriture, éjecte-le d’abord proprement côté PC.'})) {
                    await api.native('msd/set_connected', {connected: 0}, 'POST'); await load();
                }
            }), 'quiet'));
        outlet.append(card(shareMode ? 'Clé USB · Drive 1' : 'Lecteur virtuel · Drive 0', state, modes),
            card('Explorateur', row(space, button('Actualiser', () => action(load), 'quiet')), crumbs,
                row(button('Nouveau dossier', () => action(() => create('mkdir'))),
                    shareMode ? button('Fichier vide', () => action(() => create('create-file'))) : null,
                    button('Importer', () => fileInput.click(), 'primary'), fileInput), transfer, list));
        const unsubscribe = store.subscribe(status); status(); action(load);
        return () => { live = false; unsubscribe(); };
    }};
}
