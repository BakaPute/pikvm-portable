import {routes} from '../../../legacy/routes.js';
import {dashboard} from './dashboard.js';
import {storageModule} from './storage.js';
import {nativeFrameModule} from './kvm.js';
import {network} from './network.js';
import {tools, power} from './system.js';
import {settings} from './settings.js';

// Module registry: add a descriptor here, without changing shell/router/session.
export function createModules() {
    return [dashboard, nativeFrameModule({id: 'kvm', title: 'Console KVM',
        subtitle: 'Le contrôle distant, intégré à votre espace de travail.', icon: 'monitor', source: routes.kvm}),
        storageModule(false), storageModule(true), network,
        nativeFrameModule({id: 'terminal', title: 'Terminal', subtitle: 'Terminal natif authentifié PiKVM.',
            icon: 'terminal', source: routes.terminal}), tools, power, settings];
}
