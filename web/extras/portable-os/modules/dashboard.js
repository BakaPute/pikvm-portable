import {el, badge, card, row, hint, icon} from '../core/ui.js';
import {bytes, shareModes, usbEvidence} from '../core/state.js';
export const dashboard = {id: 'dashboard', title: 'Vue d’ensemble', subtitle: 'Votre PiKVM, prêt à intervenir.', icon: 'dashboard', group: 'ESPACE DE TRAVAIL',
    mount(outlet, {store}) {
        const stats = el('div', {class: 'stats'}), services = el('div'), devices = el('div');
        const preview = el('div', {class: 'preview'}, el('div', {class: 'preview-grid'}),
            el('div', {class: 'preview-caption'}, icon('monitor'), el('strong', {}, 'Console distante'), hint('Vidéo et contrôle natifs PiKVM'),
                el('a', {href: '#kvm', class: 'button primary'}, 'Ouvrir la console', icon('arrow'))));
        const image = el('img', {alt: 'Dernier aperçu vidéo du PC distant', hidden: true,
            onload: () => { image.hidden = false; }, onerror: () => { image.hidden = true; }});
        preview.prepend(image);
        outlet.append(stats, el('div', {class: 'dashboard-grid'}, card('KVM en direct', preview),
            el('div', {class: 'stack'}, card('Périphériques & stockage', devices), card('Services', services))));
        function update() {
            const battery = store.get('battery'), network = store.get('network'), system = store.get('system'), share = store.get('share'), msd = store.get('msd');
            const metrics = [
                ['battery', 'BATTERIE', battery ? `${battery.percent} %` : '—', battery?.voltage ? `${battery.voltage} V · MAX17048` : 'Mesure indisponible'],
                ['wifi', 'RÉSEAU', network?.ssid || '—', store.get('settings')?.values?.dashboard_ip===false?'Adresse IP masquée':network?.ip || 'Connexion non confirmée'],
                ['usb', 'PIKVM-SHARE', shareModes[share?.mode] || '—', usbEvidence(store.get('usb'))],
                ['activity', 'SYSTÈME', system?.system?.temperature != null ? `${system.system.temperature.toFixed(1)} °C` : '—', system?.system?.hostname || 'Informations indisponibles']];
            stats.replaceChildren(...metrics.map(([symbol, label, value, detail]) => el('section', {class: 'metric'},
                row(icon(symbol), el('span', {class: 'eyebrow'}, label)), el('strong', {}, value), el('small', {}, detail))));
            const part = msd?.storage?.parts?.[''];
            devices.replaceChildren(row(icon('storage'), el('div', {}, el('strong', {}, 'Drive 0'),
                hint(msd?.drive?.image?.name || 'Bibliothèque ISO / IMG')), badge(msd?.drive?.connected ? 'Connecté' : 'Détaché')),
                row(icon('usb'), el('div', {}, el('strong', {}, 'Drive 1 · PIKVM-SHARE'), hint(shareModes[share?.mode] || 'Indisponible'))),
                hint(part ? `${bytes(part.free)} disponibles sur le stockage natif` : 'Stockage natif non confirmé'),
                el('a', {href: '#share', class: 'text-link'}, 'Gérer les fichiers →'));
            const items = system?.services?.items || {};
            services.replaceChildren(...['kvmd.service', 'kvmd-nginx.service', 'pikvm-share-api.service'].map(name =>
                row(el('span', {}, name.replace('.service', '')), badge(items[name]?.ActiveState || 'Inconnu', items[name]?.ActiveState === 'active' ? 'green' : ''))),
                hint('Arrêt automatique : gestion manuelle, aucun démarrage automatique.'));
        }
        function snapshot() { if (!document.hidden) image.src = '/api/streamer/snapshot?allow_offline=0&t=' + Date.now(); }
        update(); snapshot(); const timer = setInterval(snapshot, 20000), unsubscribe = store.subscribe(update);
        return () => { clearInterval(timer); image.removeAttribute('src'); unsubscribe(); };
    }};
