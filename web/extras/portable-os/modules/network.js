import {el, button, badge, card, row, hint, table, dialog, notify} from '../core/ui.js';
export const network = {id: 'network', title: 'Réseau', subtitle: 'Wi-Fi, accès de secours et connectivité.', icon: 'wifi', group: 'SYSTÈME',
    mount(outlet, {api, store, action}) {
        let live = true;
        const summary = el('div'), saved = el('div'), scanned = el('div');
        function update() {
            const net = store.get('network'), system = store.get('system');
            summary.replaceChildren(row(badge(net?.connected ? 'Wi-Fi connecté' : 'Connexion non confirmée', net?.connected ? 'green' : ''),
                badge(system?.hotspot ? 'Hotspot actif' : 'Hotspot inactif')),
                el('h3', {}, net?.ssid || 'Aucun réseau confirmé'), hint([net?.ip, net?.signal].filter(Boolean).join(' · ') || 'Adresse indisponible'));
        }
        async function edit(net = {}) {
            const values = await dialog({title: net.id ? 'Modifier le réseau' : 'Ajouter un réseau',
                message: 'La configuration Wi-Fi est sauvegardée par le service existant. Une reconnexion peut interrompre cette page.',
                fields: [{name: 'ssid', label: 'SSID', value: net.ssid},
                    {name: 'password', label: net.id ? 'Nouveau mot de passe (vide : conserver)' : 'Mot de passe Wi-Fi', type: 'password', required: !net.id},
                    {name: 'priority', label: 'Priorité', value: String(net.priority || 10)},
                    {name: 'hidden', type: 'checkbox', label: 'Réseau masqué', required: false, value: !!net.hidden}]});
            if (!values) return;
            await api.wifi(net.id ? 'update' : 'add', {...values, ...(net.id ? {id: net.id} : {})});
            notify('Configuration réseau transmise.'); await load();
        }
        async function load() {
            const data = await api.wifi('networks');
            // Existing Wi-Fi API can expose a stored password; never copy it into
            // the central store, forms, logs, localStorage or rendered DOM.
            const nets = (data.networks || []).map(({id, ssid, priority, hidden, forced}) => ({id, ssid, priority, hidden, forced}));
            if (!live) return;
            saved.replaceChildren(nets.length ? table(['Réseau', 'Priorité', 'Actions'], nets.map(net => [net.ssid,
                net.forced ? 'Prioritaire' : String(net.priority), row(
                    button('Connecter', () => action(async () => {
                        if (await dialog({title: 'Changer de réseau Wi-Fi', message: 'La connexion peut être interrompue. Confirme l’accès au nouveau réseau.'})) {
                            await api.wifi('force', {id: net.id}); notify('Changement demandé.');
                        }
                    }), 'quiet'), button('Modifier', () => action(() => edit(net)), 'quiet'),
                    button('Supprimer', () => action(async () => {
                        if (await dialog({title: 'Supprimer ce réseau ?', message: net.ssid, danger: true})) {
                            await api.wifi('delete', {id: net.id}); await load();
                        }
                    }), 'quiet'))])) : hint('Aucun réseau enregistré.'));
        }
        outlet.append(card('Connexion actuelle', summary, row(button('Actualiser', () => action(async () => {
            store.resource('network', (await api.wifi('status')).status); await load();
        }), 'quiet'), button('Ajouter un réseau', () => action(() => edit()), 'primary'))),
            card('Réseaux enregistrés', saved), card('Réseaux à proximité', button('Rechercher', () => action(async () => {
                const data = await api.wifi('scan');
                if (live) scanned.replaceChildren(table(['SSID', 'Signal', 'Sécurité', ''], (data.networks || []).map(net =>
                    [net.ssid, net.signal, net.security, button('Configurer', () => action(() => edit({ssid: net.ssid})), 'quiet')])));
            })), scanned), card('Point d’accès de secours',
                hint('La bascule utilise le mécanisme de secours existant et peut déconnecter ta session. Le mot de passe du hotspot n’est pas affiché ici.'),
                row(...[true, false].map(enabled => button(enabled ? 'Activer le hotspot' : 'Revenir au Wi-Fi', () => action(async () => {
                    if (await dialog({title: 'Basculer le réseau', message: 'Cette action peut couper la connexion. Prévois un accès local de secours.', danger: true})) {
                        await api.system('hotspot', {enabled, confirmed: true}); notify('Bascule demandée.');
                    }
                }))))));
        update(); action(load); const unsub = store.subscribe(update);
        return () => { live = false; unsub(); };
    }};
