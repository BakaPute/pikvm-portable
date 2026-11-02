export class Router {
    constructor(modules, outlet, context) { this.modules = modules; this.outlet = outlet; this.context = context; this.dispose = null; this.current = null; }
    async route() {
        if (this.context.store.data.transfer || this.context.store.data.operation) {
            if (location.hash !== '#' + this.current) {
                location.hash = '#' + this.current;
                this.context.notify(this.context.store.data.transfer ? 'Termine ou annule le transfert avant de changer de vue.' : 'Attends la fin de l’opération en cours.', true);
            }
            return;
        }
        const path = location.hash.slice(1) || 'dashboard';
        const module = this.modules.find(item => item.id === path) || this.modules[0];
        this.dispose?.(); this.current = module.id;
        document.querySelectorAll('[data-route]').forEach(link => {
            if (link.dataset.route === module.id) link.setAttribute('aria-current', 'page');
            else link.removeAttribute('aria-current');
        });
        document.getElementById('page-title').textContent = module.title;
        document.getElementById('page-subtitle').textContent = module.subtitle;
        this.outlet.replaceChildren();
        this.dispose = module.mount(this.outlet, this.context) || null;
        document.title = module.title + ' · Portable OS';
        document.body.classList.remove('nav-open');
        document.getElementById('menu-toggle').setAttribute('aria-expanded', 'false');
        this.outlet.focus({preventScroll: true});
    }
    start() { window.addEventListener('hashchange', () => this.route()); this.route(); }
}
