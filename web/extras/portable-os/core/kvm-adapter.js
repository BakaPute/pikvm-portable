import {el, button} from './ui.js';
import {releaseNativeInput} from './native-bridge.js';

// KVMD 4.213 DOM contract. Move live dropdowns with their listeners intact.
// No native files, video elements, websocket or HID implementations are replaced.
export const nativeMenus = Object.freeze({
    'msd-dropdown': 'Drive 0', 'atx-dropdown': 'ATX', 'shortcuts-dropdown': 'Raccourcis',
    'macro-dropdown': 'Macros', 'text-dropdown': 'Texte', 'system-dropdown': 'Vidéo & HID',
});
export function adaptKvm(frame, fullscreen) {
    const doc = frame.contentDocument, win = frame.contentWindow;
    const stream = doc.getElementById('stream-window');
    const required = ['navbar', 'stream-window', 'hid-mute-switch', ...Object.keys(nativeMenus)];
    if (required.some(id => !doc.getElementById(id)) ||
        !stream.querySelector('[data-wm-window-set-full-tab]') ||
        Object.keys(nativeMenus).some(id => !doc.getElementById(id)?.querySelector('.menu-button') ||
            !doc.getElementById(id)?.querySelector('.menu')))
        throw new Error('Structure KVM incompatible : adaptation interrompue. Ouvrir le KVM de secours.');
    let enabled = false, timer, active = true;
    const listeners = [];
    const on = (target, type, fn, options) => { target.addEventListener(type, fn, options);
        listeners.push(() => target.removeEventListener(type, fn, options)); };
    const toggle = button('Activer clavier / souris', () => setEnabled(!enabled));
    toggle.setAttribute('aria-pressed', 'false');
    const controls = el('ul', {id: 'portable-kvm-controls', 'aria-label': 'Commandes KVM'},
        el('li', {}, toggle), el('li', {}, button('Plein écran', fullscreen)));
    for (const [id, title] of Object.entries(nativeMenus)) {
        const menu = doc.getElementById(id), trigger = menu.querySelector('.menu-button');
        if (!trigger || !menu.querySelector('.menu')) throw new Error('Menu KVM incomplet : ' + id);
        trigger.setAttribute('role', 'button'); trigger.tabIndex = 0;
        trigger.setAttribute('aria-label', title);
        const label = trigger.querySelector('span'); if (label) label.textContent = title;
        // Native wm binds down, not click. Keyboard activation follows that path.
        on(trigger, 'keydown', event => {
            if (['Enter', ' '].includes(event.key)) {
                event.preventDefault();
                trigger.dispatchEvent(new win.MouseEvent('mousedown', {bubbles: true, button: 0}));
                trigger.dispatchEvent(new win.MouseEvent('mouseup', {bubbles: true, button: 0}));
            }
        });
        controls.append(menu);
    }
    const reveal = button('Commandes KVM', () => { show(); toggle.focus(); }, 'portable-kvm-reveal');
    reveal.setAttribute('aria-controls', controls.id);
    const hud = el('div', {id: 'portable-kvm-hud'}, controls);
    doc.body.append(hud, reveal);
    function show() {
        clearTimeout(timer); hud.classList.remove('portable-idle');
        if (active) timer = setTimeout(hide, 4000);
    }
    function hide() {
        if (!active) return;
        const openMenu = [...controls.querySelectorAll('.menu')].some(menu => !menu.classList.contains('hidden'));
        if (hud.matches(':hover') || hud.contains(doc.activeElement) || openMenu) { timer = setTimeout(hide, 1000); return; }
        hud.classList.add('portable-idle');
    }
    function setEnabled(value) {
        if (!value) {
            // Recorder playback sends native HID directly, outside the mute switch.
            const stop = doc.getElementById('hid-recorder-stop');
            if (stop && !stop.disabled) stop.click();
        }
        releaseNativeInput(frame);
        enabled = value && active;
        // Use native mute to disable keyboard/mouse, including shortcut buttons.
        const mute = doc.getElementById('hid-mute-switch');
        mute.checked = !enabled;
        doc.documentElement.classList.toggle('portable-hid-enabled', enabled);
        toggle.textContent = enabled ? 'Désactiver clavier / souris' : 'Activer clavier / souris';
        toggle.setAttribute('aria-pressed', String(enabled));
        show();
        if (enabled) { win.focus(); stream.focus(); }
    }
    // Native stream receives events only during an explicit active capture.
    const guard = event => {
        const target = event.target;
        const nativeInput = target.closest?.('#stream-window,#keyboard-window,#mouse-window,[data-keyboard-shortcut],#hid-recorder-play,#hid-recorder-record,#hid-pak-button');
        const windowManagement = target.closest?.('.window-header,[data-wm-window-close]');
        const pasteShortcut = target.closest?.('#hid-pak-text') && event.ctrlKey && event.key === 'Enter';
        if (!enabled && ((nativeInput && !windowManagement) || pasteShortcut)) {
            event.preventDefault(); event.stopImmediatePropagation();
        }
    };
    for (const type of ['click','keydown','keyup','mousedown','mouseup','mousemove','wheel','touchstart','touchmove','touchend','pointerdown'])
        on(doc, type, guard, {capture: true, passive: false});
    on(doc.getElementById('hid-mute-switch'), 'change', () => { if (!enabled) doc.getElementById('hid-mute-switch').checked = true; });
    on(doc, 'pointermove', event => { if (event.clientY < 80) show(); });
    on(hud, 'focusin', show); on(hud, 'pointerenter', show);
    on(doc, 'keydown', event => {
        if (event.code === 'Escape' && event.ctrlKey && event.shiftKey) {
            event.preventDefault(); event.stopImmediatePropagation(); setEnabled(false); reveal.focus();
        }
    }, true);
    stream.querySelector('[data-wm-window-set-full-tab]').click();
    // KVMD opens its touch mouse window automatically on mobile. Start with the
    // video; its native Show mouse/keyboard commands remain in Vidéo & HID.
    for (const id of ['mouse-window', 'keyboard-window']) {
        const nativeWindow = doc.getElementById(id);
        if (nativeWindow && !nativeWindow.classList.contains('hidden'))
            nativeWindow.querySelector('[data-wm-window-close]')?.click();
    }
    doc.documentElement.classList.add('portable-kvm');
    setEnabled(false);
    return {
        enable: () => setEnabled(true),
        suspend() { setEnabled(false); active = false; clearTimeout(timer); },
        resume() { active = true; show(); },
        destroy() { setEnabled(false); active = false; clearTimeout(timer); listeners.forEach(fn => fn()); },
    };
}
