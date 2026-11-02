export function getTheme(storage) {
    try { return (storage || globalThis.localStorage).getItem('portable-theme') === 'light' ? 'light' : 'dark'; }
    catch { return 'dark'; }
}
export function saveTheme(value, storage) {
    const theme = value === 'light' ? 'light' : 'dark';
    try { (storage || globalThis.localStorage).setItem('portable-theme', theme); return true; }
    catch { return false; }
}
