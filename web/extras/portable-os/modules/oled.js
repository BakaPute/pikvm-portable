import {el, button, hint, notify} from '../core/ui.js';

export function unpackPixels(encoded) {
    const bits = atob(encoded);
    if (bits.length !== 1024) throw new Error('Framebuffer OLED incompatible.');
    const pixels = new Uint8ClampedArray(128 * 64 * 4);
    for (let index = 0; index < 8192; index++) {
        const on = bits.charCodeAt(index >> 3) & (128 >> (index & 7));
        const offset = index * 4;
        pixels[offset] = on ? 212 : 5; pixels[offset + 1] = on ? 247 : 10;
        pixels[offset + 2] = on ? 230 : 9; pixels[offset + 3] = 255;
    }
    return pixels;
}

export function openOled(context) {
    const host = document.getElementById('dialogs');
    if (host.childElementCount) { notify('Fermer la fenêtre actuelle avant d’ouvrir l’OLED.', true); return; }
    const previous = document.activeElement;
    let closed = false, busy = false, reading = false, frame, timer, controller;
    let initialWaiting = context.store.data.session !== 'ready';
    const state = el('p', {role: 'status', 'aria-live': 'polite'}, context.store.data.session === 'expired' ?
        'Session PiKVM expirée. Reconnectez-vous pour utiliser l’OLED.' : 'Connexion au framebuffer OLED…');
    const details = el('p', {class: 'muted oled-detail'});
    const canvas = el('canvas', {width: 128, height: 64, 'aria-hidden': 'true'});
    const screen = button('', press, 'oled-screen', {'aria-label': 'Appui court sur le bouton OLED', disabled: true});
    screen.append(canvas);
    const close = () => {
        closed = true; clearTimeout(timer); controller?.abort(); unsubscribe();
        document.removeEventListener('visibilitychange', visibility);
        window.removeEventListener('pagehide', close);
        node.close(); node.remove(); previous?.focus();
    };
    const node = el('dialog', {class: 'oled-window', 'aria-labelledby': 'oled-title',
        oncancel: event => { event.preventDefault(); close(); }},
        el('div', {class: 'row'}, el('h2', {id: 'oled-title'}, 'OLED · Pi Zero 2 W'), button('Fermer', close, 'quiet')),
        screen, state, details, hint('Un clic, un toucher ou Entrée : appui court. Les appuis longs restent physiques.'));
    const unsubscribe = context.store.subscribe(data => {
        if (data.session === 'expired') {
            clearTimeout(timer); controller?.abort(); screen.disabled = true;
            state.textContent = 'Session PiKVM expirée. Reconnectez-vous pour utiliser l’OLED.';
        }
        if (data.session === 'ready' && initialWaiting) { initialWaiting = false; refresh(); }
    });
    const visibility = () => {
        clearTimeout(timer);
        if (document.hidden) { screen.disabled = true; controller?.abort(); }
        else refresh();
    };
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('pagehide', close);
    host.append(node); node.showModal(); refresh();

    async function refresh() {
        clearTimeout(timer);
        if (closed || busy || reading || document.hidden || context.store.data.session !== 'ready') return;
        reading = true;
        controller = new AbortController();
        try {
            const {result} = await context.api.request('/extras/portable-os/api/oled', {signal: controller.signal, timeout: 4000});
            if (closed || context.store.data.session !== 'ready') return;
            if (result.width !== 128 || result.height !== 64 || result.format !== '1bpp-msb') throw new Error('Format OLED incompatible.');
            canvas.getContext('2d').putImageData(new ImageData(unpackPixels(result.pixels), 128, 64), 0, 0);
            frame = result;
            screen.disabled = !result.button_available || busy;
            state.textContent = result.button_available ? 'Synchronisé · toucher l’écran pour un appui court.' :
                'Affichage synchronisé · gestionnaire du bouton indisponible.';
            details.textContent = `${result.source === 'menu' ? 'Menu physique' : 'Affichage normal'} · ${
                result.physical === 'connected' ? 'OLED physique connecté' : 'Mode virtuel'} · actualisation 1 s`;
        } catch (error) {
            if (!closed && !busy && !document.hidden && context.store.data.session !== 'expired') {
                screen.disabled = true; frame = null;
                state.textContent = 'Hors ligne : ' + error.message;
                details.textContent = 'Dernière image conservée ; les appuis sont bloqués.';
            }
        } finally {
            reading = false; controller = null;
            if (!closed && !busy && !document.hidden && context.store.data.session === 'ready') timer = setTimeout(refresh, 1000);
        }
    }

    async function press() {
        if (busy || !frame || screen.disabled || context.store.data.session !== 'ready') return;
        busy = true; screen.disabled = true; clearTimeout(timer); controller?.abort();
        try {
            await context.action(async () => {
                try {
                    await context.api.request('/extras/portable-os/api/oled/short', {method: 'POST',
                        body: {action: 'short', frame_id: frame.id}, timeout: 4000});
                    if (!closed) state.textContent = 'Appui court transmis au gestionnaire du bouton.';
                } catch (error) {
                    if (!closed) state.textContent = 'Appui refusé : ' + error.message;
                    throw error;
                }
            });
        } finally {
            busy = false;
            // Read the result; never retry a potentially consumed input automatically.
            if (!closed) timer = setTimeout(refresh, 400);
        }
    }
}
