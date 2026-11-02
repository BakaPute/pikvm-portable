import {dashboard} from './dashboard.js';
import {storageModule} from './storage.js';
import {nativeFrameModule} from './kvm.js';
import {network} from './network.js';
import {tools, power, settings} from './system.js';

// Module registry: add a descriptor here, without changing shell/router/session.
export function createModules() {
    return [dashboard, nativeFrameModule({id: 'kvm', title: 'Console KVM',
        subtitle: 'Le contrôle distant, intégré à votre espace de travail.', icon: 'monitor', source: '/kvm/'}),
        storageModule(false), storageModule(true), network,
        nativeFrameModule({id: 'terminal', title: 'Terminal', subtitle: 'Terminal natif authentifié PiKVM.',
            icon: 'terminal', source: '/extras/webterm/ttyd/'}), tools, power, settings];
}
