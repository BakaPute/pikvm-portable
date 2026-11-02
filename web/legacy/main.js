import {routes, extensionLink, primaryAppPaths} from './routes.js';
for (const link of document.querySelectorAll('[data-link]')) link.href = routes[link.dataset.link];
const status = document.getElementById('status');
document.getElementById('logout').onclick = async () => {
    try {
        const response = await fetch(routes.logout, {method: 'POST', credentials: 'same-origin'});
        if (![200, 401, 403].includes(response.status)) throw new Error('Déconnexion impossible. Réessayer.');
        location.assign(routes.login);
    } catch (error) { status.textContent = error.message; }
};
try {
    const response = await fetch(routes.info, {credentials: 'same-origin', cache: 'no-store'});
    if ([401, 403].includes(response.status)) location.assign(routes.login);
    if (!response.ok) throw new Error('Liste des extensions indisponible. Les accès KVM et Terminal restent disponibles.');
    const {result} = await response.json();
    const extras = document.getElementById('extras'); extras.replaceChildren();
    if (result.extras === null) throw new Error('KVMD ne peut pas énumérer les extensions. Consulter ses journaux.');
    for (const app of Object.values(result.extras || {}).sort((a, b) => a.place - b.place)) {
        if (app.place < 0 || !(app.enabled || app.started)) continue;
        const href = extensionLink(app.path, location.origin);
        if (!href || primaryAppPaths.has(href.split('?')[0])) continue;
        const link = document.createElement('a'); link.href = href; link.textContent = app.name; extras.append(link);
    }
    if (!extras.childElementCount) extras.textContent = 'Aucune extension disponible.';
} catch (error) { status.textContent = error.message; }
