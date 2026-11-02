import {routes} from '../../legacy/routes.js';
import {openOled} from './modules/oled.js';
import {Store} from './core/state.js';
import {Client, Poller} from './core/api.js';
import {el, icon, notify, guarded} from './core/ui.js';
import {Router} from './core/router.js';
import {createModules} from './modules/index.js';
import {getTheme} from './core/preferences.js';

document.getElementById('fallback-link').href = routes.legacy;
const store = new Store(), api = new Client(store), poller = new Poller(api, store);
document.documentElement.dataset.theme = getTheme();
const modules = createModules();
const context = {api, store, poller, notify, action: async work => {
    if (store.data.session !== 'ready') { notify('Une session PiKVM valide est requise.', true); return; }
    if (store.data.operation) { notify('Une opération est déjà en cours.', true); return; }
    store.update({operation: true});
    try { return await guarded(work); } finally { store.update({operation: false}); }
}};
const nav = document.getElementById('navigation');
document.getElementById('device-oled').onclick = () => openOled(context);
let group;
for (const module of modules) {
    if (module.group !== group) { group = module.group; nav.append(el('div', {class: 'nav-label'}, group)); }
    nav.append(el('a', {href: '#' + module.id, 'data-route': module.id}, icon(module.icon), el('span', {}, module.title),
        module.id === 'share' ? el('span', {class: 'nav-tag'}, 'D1') : null));
}
document.getElementById('menu-toggle').onclick = () => {
    const open = document.body.classList.toggle('nav-open');
    document.getElementById('menu-toggle').setAttribute('aria-expanded', String(open));
};
document.addEventListener('keydown', event => {
    if (event.key === 'Escape') { document.body.classList.remove('nav-open'); document.getElementById('menu-toggle').setAttribute('aria-expanded', 'false'); }
});
document.getElementById('refresh-all').onclick = () => guarded(() => poller.refresh());
store.subscribe(data => {
    const net = store.get('network'), battery = store.get('battery');
    document.getElementById('network-label').textContent = net?.ip || 'Réseau non confirmé';
    document.getElementById('battery-label').textContent = battery ? `${battery.percent} %` : 'Batterie —';
    const errors = Object.values(data.resources).filter(resource => resource.stale).length;
    const stale = document.getElementById('resource-alert');
    stale.hidden = !errors; stale.textContent = `${errors} source(s) indisponible(s). Les dernières valeurs connues peuvent être anciennes. `;
    for (const [name, resource] of Object.entries(data.resources)) if (resource.stale)
        stale.append(el('span', {}, `${name} : ${resource.error} `));
    document.getElementById('session-alert').hidden = data.session !== 'expired';
    document.getElementById('test-alert').hidden = store.get('system')?.test_mode !== true;
    document.getElementById('activity-label').textContent = data.transfer || (data.operation ? 'Opération en cours…' : 'Session PiKVM');
    if (data.session === 'expired') poller.stop();
    document.body.setAttribute('aria-busy', String(data.operation || false));
});
window.addEventListener('beforeunload', event => { if (store.data.transfer) { event.preventDefault(); event.returnValue = ''; } });
window.addEventListener('pagehide', () => poller.stop());
document.addEventListener('visibilitychange',()=>{
    if(document.hidden)poller.stop();
    else if(store.data.session==='ready')poller.start();
});
window.addEventListener('pageshow', event => { if (event.persisted && !document.hidden && store.data.session === 'ready') poller.start(); });
document.getElementById('logout').onclick = () => context.action(async () => {
    if (store.data.transfer) throw new Error('Termine ou annule le transfert avant la déconnexion.');
    await api.native('auth/logout', undefined, 'POST'); location.assign('/login/');
});
async function start() {
    try { await api.native('auth/check'); store.update({session: 'ready'}); }
    catch (error) { store.update({session: 'expired'}); notify(error.message, true); return; }
    const router = new Router(modules, document.getElementById('view'), context);
    router.start(); if(!document.hidden)poller.start();
}
start();
