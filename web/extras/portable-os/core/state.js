export class Store {
    constructor() { this.data = {session: 'checking', resources: {}, transfer: null}; this.listeners = new Set(); }
    update(patch) { this.data = {...this.data, ...patch}; for (const callback of this.listeners) callback(this.data); }
    resource(name, data, error = null) {
        const previous = this.data.resources[name];
        this.update({resources: {...this.data.resources, [name]: {data: error ? previous?.data : data,
            error, stale: !!error, at: error ? previous?.at : Date.now()}}});
    }
    subscribe(callback) { this.listeners.add(callback); return () => this.listeners.delete(callback); }
    get(name) { return this.data.resources[name]?.data; }
}

export const shareModes = {usb: 'USB attaché', detached: 'Détaché', web: 'Gestion Web', error: 'Récupération requise',
    mounting: 'Montage en cours', unmounting: 'Démontage en cours', waiting_eject: 'Éjection attendue'};
export function bytes(value) {
    if (!Number.isFinite(Number(value))) return 'Indisponible';
    const n = Math.max(0, Number(value)), index = n ? Math.min(4, Math.floor(Math.log(n) / Math.log(1024))) : 0;
    return `${(n / 1024 ** index).toLocaleString('fr-FR', {maximumFractionDigits: 1})} ${['o', 'Kio', 'Mio', 'Gio', 'Tio'][index]}`;
}
export function relativePath(parent, name) { return parent ? `${parent}/${name}` : name; }
export function visibleImages(msd) {
    return Object.entries(msd?.storage?.images || {}).filter(([name]) =>
        !name.split('/').some(part => part.startsWith('.')) && /\.(iso|img|raw)$/i.test(name));
}
export function usbEvidence(usb) {
    const drive = usb?.drives?.['1'];
    if (!usb) return 'Diagnostic USB indisponible.';
    if (!drive?.present) return 'Fonction USB du Drive 1 absente.';
    if (!drive.configurations?.length) return 'Drive 1 présent mais non lié à une configuration USB.';
    if (!drive.attached) return 'Lecteur présent, sans média : aucune image attachée au Drive 1 (Windows : No Media, capacité 0).';
    if (!usb.udc) return 'Image attachée ; contrôleur USB non lié.';
    if (!usb.host_configured) return `Image attachée ; USB ${usb.state || 'non confirmé'}.`;
    return 'Image attachée ; gadget USB configuré par l’hôte. Montage Windows non observable.';
}
export function powerSafe(msd, share, transfer) {
    return msd?.drive?.connected === false && !!share && share.mode === 'detached' && !share.uploads && !transfer;
}
