import {el, button, hint, notify} from '../core/ui.js';
import {releaseNativeInput, bridgeNavigation} from '../core/native-bridge.js';
import {adaptKvm} from '../core/kvm-adapter.js';
import {routes} from '../../../legacy/routes.js';
export function nativeFrameModule({id, title, subtitle, icon, source}) {
    let wrapper, frame, unbridge, adapter, mounted = false, watcher;
    return {id, title, subtitle, icon, group: id === 'kvm' ? 'ESPACE DE TRAVAIL' : 'SYSTÈME', mount(outlet, context) {
        mounted = true;
        const dock = document.getElementById('native-dock');
        const fullscreen = () => (document.fullscreenElement ? document.exitFullscreen() : wrapper.requestFullscreen())
            .catch(error => notify(error.message, true));
        if (!wrapper) {
            frame = el('iframe', {title, src: source, allow: 'fullscreen; autoplay; clipboard-read; clipboard-write', allowFullscreen: true,
                onload: async () => {
                    adapter?.destroy(); adapter = null; unbridge?.();
                    wrapper.querySelector('.native-error')?.remove();
                    try {
                        const doc = frame.contentDocument;
                        if (doc.querySelector('input[type=password]') || /\/login\/?/.test(frame.contentWindow.location.pathname)) {
                            frame.style.display = 'none';
                            wrapper.append(el('p', {class: 'native-error alert'},
                                el('a', {href: routes.login}, 'Session expirée : se reconnecter à PiKVM')));
                            notify('La session native nécessite une reconnexion PiKVM.', true); return;
                        }
                        for (const name of ['native', ...(id === 'kvm' ? ['kvm'] : [])])
                            if (!doc.getElementById('portable-' + name + '-style')) await new Promise((resolve, reject) => {
                                const timeout = setTimeout(() => reject(new Error('Style KVM indisponible.')), 5000);
                                const done = callback => { clearTimeout(timeout); callback(); };
                                doc.head.append(el('link', {id: 'portable-' + name + '-style', rel: 'stylesheet',
                                    href: '/extras/portable-os/' + name + '.css', onload: () => done(resolve),
                                    onerror: () => done(() => reject(new Error('Style KVM indisponible.')))}));
                            });
                        if (frame.contentDocument !== doc) return;
                        if (id === 'kvm') {
                            adapter = adaptKvm(frame, fullscreen);
                            frame.before(adapter.controls,adapter.panel);
                            watcher?.disconnect();watcher=new ResizeObserver(resize);
                            watcher.observe(adapter.controls);watcher.observe(adapter.panel);
                        }
                        frame.style.visibility = 'visible'; frame.style.display = 'block';
                        if (!mounted || context?.store.data.session !== 'ready') adapter?.suspend();
                        unbridge = bridgeNavigation(frame, route => { location.hash = '#' + route; });
                    } catch (error) {
                        releaseNativeInput(frame); frame.style.display = 'none';
                        wrapper.append(el('p', {class: 'native-error alert', role: 'alert'}, error.message, ' ',
                            el('a', {href: source, target: '_blank', rel: 'noopener'}, 'Ouvrir le moteur natif de secours')));
                        notify(error.message, true);
                    }
                }});
            if (id === 'kvm') frame.style.visibility = 'hidden';
            wrapper = el('section', {class: 'native-panel'}, frame); dock.append(wrapper);
        }
        wrapper.hidden = false; dock.hidden = false;
        const resize = () => wrapper.style.setProperty('--native-height',
            Math.max(280, innerHeight - (frame.getBoundingClientRect().top + scrollY) - 24) + 'px');
        const layout = requestAnimationFrame(resize);
        window.addEventListener('resize', resize);
        if (context?.store.data.session === 'ready') adapter?.resume();
        if(id==='kvm'){
            outlet.append(hint('Moteur KVMD natif · commandes et panneaux dans Portable OS · Ctrl+Maj+Échap libère la capture.'));
            if(adapter){watcher?.disconnect();watcher=new ResizeObserver(resize);watcher.observe(adapter.controls);watcher.observe(adapter.panel);}
        }else outlet.append(el('div', {class: 'native-toolbar'}, hint('Terminal PiKVM natif · session authentifiée'),
            button('Activer le terminal', () => {
                if (context?.store.data.session !== 'ready') return notify('Session PiKVM requise.', true);
                if (id === 'kvm') adapter?.enable(); else frame.contentWindow.focus();
            }, 'quiet'), button('Plein écran', fullscreen, 'quiet')));
        const unsubscribe = context?.store.subscribe(data => {
            if (data.session === 'expired') { adapter?.suspend(); releaseNativeInput(frame); }
        });
        return () => { mounted = false; cancelAnimationFrame(layout); window.removeEventListener('resize', resize);
            watcher?.disconnect();unsubscribe?.(); adapter?.suspend(); releaseNativeInput(frame); wrapper.hidden = true; dock.hidden = true; };
    }};
}
