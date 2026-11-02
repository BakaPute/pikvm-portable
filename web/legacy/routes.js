// Shared navigation contract. This file has no dependency on Portable OS.
export const routes = Object.freeze({home: '/', portable: '/extras/portable-os/',
    legacy: '/legacy/', kvm: '/kvm/', terminal: '/extras/webterm/ttyd/',
    terminalIndex: '/extras/webterm/', terminalLegacy: '/power-terminal/', login: '/login/',
    info: '/api/info?legacy=0&fields=auth,node,extras', logout: '/api/auth/logout'});
export const toolRoutes = new Map([['/', 'dashboard'], ['/kvm/', 'kvm'],
    ['/extras/image-manager/', 'images'], ['/extras/pikvm-share/', 'share'],
    ['/extras/wifi-wizard/', 'network'], [routes.terminalLegacy, 'terminal']]);
export const primaryAppPaths = new Set([routes.kvm, routes.terminal, routes.terminalIndex,
    routes.terminalLegacy, routes.portable]);
export function extensionLink(path, origin) {
    if (typeof path !== 'string' || !path.trim()) return null;
    let url;
    try { url = new URL(path, origin + '/'); } catch { return null; }
    if (url.origin !== origin || !['http:', 'https:'].includes(url.protocol)) return null;
    if (!url.pathname.endsWith('/')) url.pathname += '/';
    url.searchParams.set('legacy', '1');
    return url.pathname + url.search;
}
