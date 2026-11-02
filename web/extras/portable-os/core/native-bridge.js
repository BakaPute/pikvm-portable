const routes = new Map([['/', 'dashboard'], ['/kvm/', 'kvm'],
    ['/extras/image-manager/', 'images'], ['/extras/pikvm-share/', 'share'],
    ['/extras/wifi-wizard/', 'network'], ['/power-terminal/', 'terminal']]);
export function nativeRoute(url, origin) {
    if (url.origin !== origin || url.searchParams.get('legacy') === '1' || url.hash) return null;
    const path = url.pathname.replace(/index\.html$/, '');
    return routes.get(path.endsWith('/') ? path : path + '/') || null;
}
export function releaseNativeInput(frame) {
    try {
        const doc = frame.contentDocument;
        if (doc.pointerLockElement) doc.exitPointerLock();
        // KVMD 4.213's Hid registers window.blur -> Keyboard/Mouse.releaseAll.
        // Use that existing lifecycle hook, never recreate its HID protocol.
        frame.contentWindow.dispatchEvent(new frame.contentWindow.Event('blur'));
    } catch { /* Cross-origin/login/error document: do not access native state. */ }
}
export function bridgeNavigation(frame, navigate) {
    const doc = frame.contentDocument;
    const listener = event => {
        const anchor = event.target.closest?.('a[href]');
        if (!anchor || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
        const route = nativeRoute(new URL(anchor.href, frame.contentWindow.location.href), location.origin);
        if (route) {
            event.preventDefault(); event.stopImmediatePropagation();
            releaseNativeInput(frame); navigate(route);
        }
    };
    doc.addEventListener('click', listener, true);
    return () => doc.removeEventListener('click', listener, true);
}
