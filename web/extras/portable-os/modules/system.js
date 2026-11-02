import {routes} from '../../../legacy/routes.js';
import {el, button, badge, card, row, hint, field, table, dialog, notify} from '../core/ui.js';
import {powerSafe, usbEvidence} from '../core/state.js';
import {getTheme, saveTheme} from '../core/preferences.js';
export const tools = {id: 'tools', title: 'Outils & diagnostics', subtitle: 'Observations du PiKVM, sans modification matérielle.', icon: 'activity', group: 'SYSTÈME',
    mount(outlet, {api, store, action}) {
        let live = true;
        const services = el('div'), systemInfo = el('div'), usb = el('div'), logs = el('pre', {class: 'logs', tabindex: 0}, 'Choisis un service pour consulter ses journaux.');
        const units = ['kvmd.service', 'kvmd-nginx.service', 'pikvm-share-api.service', 'wifi-wizard-api.service', 'pikvm-portable-api.service'];
        const select = el('select', {'aria-label': 'Service des journaux'}, ...units.map(unit => el('option', {value: unit}, unit)));
        function update() {
            const items = store.get('system')?.services?.items || {};
            const sys = store.get('system')?.system || {};
            systemInfo.replaceChildren(table(['Information', 'Valeur'], [
                ['Hôte', sys.hostname || 'Indisponible'], ['Noyau', sys.kernel || 'Indisponible'],
                ['Python', sys.python || 'Indisponible'],
                ['Uptime', sys.uptime == null ? 'Indisponible' : `${Math.floor(sys.uptime / 60)} min`]]));
            services.replaceChildren(table(['Service', 'État', 'Démarrage'], Object.entries(items).map(([name, item]) =>
                [name, badge(item.ActiveState || 'Inconnu', item.ActiveState === 'active' ? 'green' : ''), item.UnitFileState || 'Indisponible'])));
            const info = store.get('usb'), drive = info?.drives?.['1'];
            usb.replaceChildren(hint(usbEvidence(info)), table(['Observation', 'Valeur'], [
                ['Image Drive 1', drive?.attributes?.file || 'Aucune'], ['CD-ROM', drive?.attributes?.cdrom ?? 'Inconnu'],
                ['Lecture seule', drive?.attributes?.ro ?? 'Inconnu'], ['Support amovible', drive?.attributes?.removable ?? 'Inconnu'],
                ['UDC', info?.udc || 'Non lié'], ['État USB', info?.state || 'Inconnu'],
                ['Détection / montage / lettre Windows', 'Non observables depuis PiKVM']]),
                hint('Si le gadget est configuré mais que le volume n’apparaît pas : vérifier Get-Disk, Get-Partition et Get-Volume côté PC. Aucune réinitialisation USB globale n’est proposée.'));
        }
        outlet.append(card('Informations système', systemInfo), card('Services', services), card('Diagnostic USB · Drive 1', usb),
            card('Journaux récents', row(select, button('Lire les journaux', () => action(async () => {
                const data = await api.system('logs', undefined, {unit: select.value});
                if (live) logs.textContent = data.entries.map(entry => entry.message).join('\n') || 'Aucune entrée.';
            }), 'quiet')), logs));
        update(); const unsub = store.subscribe(update); return () => { live = false; unsub(); };
    }};
export const power = {id: 'power', title: 'Batterie & alimentation', subtitle: 'Mesures disponibles et commandes explicites.', icon: 'battery', group: 'SYSTÈME',
    mount(outlet, {api, store, action}) {
        const measurements = el('div'), policy = el('div');
        function update() {
            const battery = store.get('battery'), system = store.get('system');
            measurements.replaceChildren(el('div', {class: 'large-value'}, battery ? `${battery.percent} %` : '—'),
                hint(battery ? `${battery.voltage} V · ${battery.charging ? 'En charge' : 'Sur batterie'} · ${battery.state}` : 'Mesure MAX17048 indisponible.'));
            const auto = system?.services?.items?.['pikvm-auto-shutdown.service'];
            policy.replaceChildren(badge(auto?.ActiveState || 'État non confirmé'),
                hint(`Démarrage : ${auto?.UnitFileState || 'non confirmé'}. Portable OS ne démarre et n’active jamais ce service automatiquement.`),
                hint('GPIO17, GPIO18 et le maintien physique d’alimentation ne sont pas reconfigurés par cette application.'));
        }
        outlet.append(card('Batterie · MAX17048', measurements), card('Arrêt automatique', policy), card('Arrêt du système',
            hint('Éjecte les lecteurs côté PC, démonte SHARE et termine les transferts avant d’arrêter le PiKVM.'),
            button('Arrêter le PiKVM…', () => action(async () => {
                const [msd, share] = await Promise.all([api.native('msd'), api.share('status')]);
                if (!powerSafe(msd, share, store.data.transfer)) throw new Error('Lecteur attaché, mode Web actif ou état non confirmé. Détache les lecteurs et récupère SHARE avant l’arrêt.');
                if (await dialog({title: 'Arrêter le PiKVM ?', message: 'La session sera interrompue. L’arrêt utilise le mécanisme d’alimentation existant.', confirm: 'Arrêter', danger: true})) {
                    const [freshMsd, freshShare] = await Promise.all([api.native('msd'), api.share('status')]);
                    if (!powerSafe(freshMsd, freshShare, store.data.transfer)) throw new Error('L’état des lecteurs a changé. Arrêt annulé.');
                    await api.wifi('pikvm-poweroff', {}); notify('Arrêt propre demandé.');
                }
            }), 'danger')));
        update(); const unsub = store.subscribe(update); return unsub;
    }};
export const settings = {id: 'settings', title: 'Paramètres', subtitle: 'Préférences de cette interface et compatibilité.', icon: 'settings', group: 'SYSTÈME',
    mount(outlet, {store}) {
        const theme = el('select', {value: getTheme(), onchange: () => {
            if (!saveTheme(theme.value)) notify('Préférence appliquée pour cette session ; stockage navigateur indisponible.');
            document.documentElement.dataset.theme = theme.value;
        }}, el('option', {value: 'dark'}, 'Sombre'), el('option', {value: 'light'}, 'Clair'));
        theme.value = getTheme();
        outlet.append(card('Apparence', field('Thème', theme), hint('Préférence locale au navigateur, sans changement système.')),
            card('Authentification & permissions', hint('Session PiKVM existante. Les opérations restent contrôlées par les API natives et SHARE.'),
                hint('KVMD 4.213 n’expose pas de rôles distincts pour cette interface : aucun rôle administrateur artificiel n’est déduit côté navigateur.')),
            card('Compatibilité', hint('Cible : KVMD 4.213 · Python 3.14.7 · Raspberry Pi Zero 2 W.'),
                hint('L’interface historique et les moteurs vidéo/HID ne sont pas remplacés. Une API absente est signalée ; aucune configuration matérielle n’est migrée silencieusement.'),
                el('a', {href: routes.legacy, target: '_blank', rel: 'noopener', class: 'button quiet'}, 'Interface PiKVM de secours')));
    }};
