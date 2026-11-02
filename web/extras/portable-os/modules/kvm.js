import {el, button, hint, notify} from '../core/ui.js';
import {releaseNativeInput, bridgeNavigation} from '../core/native-bridge.js';
export function nativeFrameModule({id, title, subtitle, icon, source}) {
    let wrapper, frame, unbridge;
    return {id, title, subtitle, icon, group: id === 'kvm' ? 'ESPACE DE TRAVAIL' : 'SYSTÈME', mount(outlet) {
        const dock = document.getElementById('native-dock');
        if (!wrapper) {
            frame = el('iframe', {title, src: source, allow: 'fullscreen; autoplay; clipboard-read; clipboard-write', allowFullscreen: true,
                onload: () => {
                    try {
                        const doc = frame.contentDocument;
                        if (doc.querySelector('input[type=password]') || /\/login\/?/.test(frame.contentWindow.location.pathname)) {
                            notify('La session native nécessite une reconnexion PiKVM.', true); return;
                        }
                        if (!doc.getElementById('portable-native-style')) doc.head.append(el('link', {id: 'portable-native-style',
                            rel: 'stylesheet', href: '/extras/portable-os/native.css'}));
                        unbridge?.();
                        unbridge = bridgeNavigation(frame, route => { location.hash = '#' + route; });
                    } catch { notify('Le moteur natif ne peut pas être intégré. Utilise l’interface de secours.', true); }
                }});
            wrapper = el('section', {class: 'native-panel'}, frame); dock.append(wrapper);
        }
        wrapper.hidden = false; dock.hidden = false;
        outlet.append(el('div', {class: 'native-toolbar'}, hint(id === 'kvm' ?
            'Vidéo, HID, raccourcis, macros et qualité : moteur PiKVM natif conservé.' : 'Terminal PiKVM natif · session authentifiée'),
            button(id === 'kvm' ? 'Activer clavier / souris' : 'Activer le terminal', () => {
                frame.contentWindow.focus();
                frame.contentDocument?.getElementById('stream-window')?.focus();
            }, 'quiet'),
            button('Plein écran', () => wrapper.requestFullscreen().catch(error => notify(error.message, true)), 'quiet')));
        return () => { releaseNativeInput(frame); wrapper.hidden = true; dock.hidden = true; };
    }};
}
