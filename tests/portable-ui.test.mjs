import test from 'node:test';
import assert from 'node:assert/strict';
import {Store, visibleImages, usbEvidence, powerSafe, bytes} from '../web/extras/portable-os/core/state.js';
import {Client, ApiError, Poller} from '../web/extras/portable-os/core/api.js';
import {nativeRoute, releaseNativeInput} from '../web/extras/portable-os/core/native-bridge.js';
import {getTheme, saveTheme} from '../web/extras/portable-os/core/preferences.js';
import {createModules} from '../web/extras/portable-os/modules/index.js';
import {routes, extensionLink} from '../web/legacy/routes.js';
import {nativeMenus} from '../web/extras/portable-os/core/kvm-adapter.js';

test('navigation contract keeps fallback independent and extension URLs local', () => {
    assert.equal(routes.legacy, '/legacy/');
    assert.equal(routes.kvm, '/kvm/');
    assert.equal(extensionLink('extras/future', 'https://pikvm'), '/extras/future/?legacy=1');
    assert.equal(extensionLink('//evil.example/tool', 'https://pikvm'), null);
    assert.equal(extensionLink('https://evil.example/tool', 'https://pikvm'), null);
    assert.equal(extensionLink(undefined, 'https://pikvm'), null);
    assert.equal(extensionLink('/extras/future/?x=1', 'https://pikvm'), '/extras/future/?x=1&legacy=1');
    assert.deepEqual(Object.keys(nativeMenus), ['msd-dropdown','atx-dropdown','shortcuts-dropdown',
        'macro-dropdown','text-dropdown','system-dropdown']);
});

test('store preserves last known state and marks an unavailable source stale', () => {
    const store = new Store(); let calls = 0;
    const remove = store.subscribe(() => calls++);
    store.resource('share', {mode: 'web'}); store.resource('share', null, 'Unavailable'); remove();
    assert.equal(store.get('share').mode, 'web'); assert.equal(store.data.resources.share.stale, true); assert.equal(calls, 2);
});
test('image listing never publishes technical or hidden SHARE images', () => {
    const images = visibleImages({storage: {images: {'rescue.iso': {}, '.PIKVM-SHARE.img': {},
        'folder/test.img': {}, 'folder/.hidden.img': {}, 'readme.txt': {}}}});
    assert.deepEqual(images.map(([name]) => name), ['rescue.iso', 'folder/test.img']);
});
test('USB evidence never equates host configuration with Windows mounting', () => {
    const value = usbEvidence({udc: 'a', host_configured: true, drives: {'1': {present: true, configurations: ['c.1'], attached: true}}});
    assert.match(value, /Montage Windows non observable/);
    assert.match(usbEvidence({drives: {'1': {present: true, configurations: [], attached: true}}}), /non lié/);
});
test('poweroff requires confirmed detached states, not missing telemetry', () => {
    assert.equal(powerSafe({}, {mode: 'detached'}), false);
    assert.equal(powerSafe({drive: {connected: false}}, {mode: 'web'}), false);
    assert.equal(powerSafe({drive: {connected: false}}, {mode: 'detached'}, 'upload'), false);
    assert.equal(powerSafe({drive: {connected: false}}, {mode: 'detached', uploads: 0}, null), true);
});
test('client preserves session, URI prefix and non-simple CSRF header', async () => {
    const calls = [], store = new Store();
    const client = new Client(store, async (url, options) => { calls.push([url, options]); return Response.json({ok: true, result: {mode: 'web'}}); });
    assert.deepEqual(await client.share('mode/web', {ejected: true}), {mode: 'web'});
    assert.equal(calls[0][0], '/extras/pikvm-share/api/mode/web');
    assert.equal(calls[0][1].credentials, 'same-origin');
    assert.equal(calls[0][1].headers['X-Pikvm-Share'], '1');
    assert.equal(calls[0][1].redirect, 'error');
});
test('expired authentication is centralized', async () => {
    const store = new Store(), client = new Client(store, async () => new Response('', {status: 401}));
    await assert.rejects(client.native('msd'), ApiError); assert.equal(store.data.session, 'expired');
});
test('403 permission/CSRF errors do not force a valid session to log out', async () => {
    const store = new Store(); store.update({session: 'ready'});
    const client = new Client(store, async url => new Response('', {status: url === '/api/auth/check' ? 200 : 403}));
    await assert.rejects(client.system('hotspot', {}), ApiError);
    assert.equal(store.data.session, 'ready');
});
test('native expired-token 403 is confirmed and expires the shared session', async () => {
    const store = new Store(); store.update({session: 'ready'});
    const client = new Client(store, async () => new Response('', {status: 403}));
    await assert.rejects(client.native('msd'), /expirée/);
    assert.equal(store.data.session, 'expired');
});
test('legacy native navigation maps into the shell but preserves explicit fallback and shortcuts', () => {
    assert.equal(nativeRoute(new URL('https://pikvm/extras/image-manager/'), 'https://pikvm'), 'images');
    assert.equal(nativeRoute(new URL('https://pikvm/extras/pikvm-share/?legacy=1'), 'https://pikvm'), null);
    assert.equal(nativeRoute(new URL('https://external/'), 'https://pikvm'), null);
    assert.equal(nativeRoute(new URL('https://pikvm/kvm/#keyboard'), 'https://pikvm'), null);
});
test('leaving a native frame releases pointer lock and uses the native blur hook', () => {
    const events = [];
    releaseNativeInput({contentDocument: {pointerLockElement: {}, exitPointerLock: () => events.push('unlock')},
        contentWindow: {Event, dispatchEvent: event => events.push(event.type)}});
    assert.deepEqual(events, ['unlock', 'blur']);
});
test('backend conflicts remain errors and are never optimistic successes', async () => {
    const store = new Store(), client = new Client(store, async () => Response.json({ok: false, error: 'Éjection requise'}, {status: 409}));
    await assert.rejects(client.share('mode/web', {ejected: true}), /Éjection requise/);
});
test('polling has one in-flight batch and preserves individual failure states', async () => {
    const store = new Store(); let nativeCalls = 0;
    const client = {native: async () => { nativeCalls++; return {drive: {connected: false}}; },
        share: async () => { throw new Error('Share unavailable'); }, wifi: async () => ({status: {}, battery: {percent: 80}}), system: async () => ({})};
    const poller = new Poller(client, store);
    await Promise.all([poller.refresh(), poller.refresh()]);
    assert.equal(nativeCalls, 1); assert.equal(store.data.resources.share.stale, true);
    assert.equal(store.get('battery').percent, 80);
});
test('sizes handle empty and unknown values', () => { assert.equal(bytes(0), '0 o'); assert.equal(bytes(undefined), 'Indisponible'); });
test('blocked browser storage cannot prevent application startup', () => {
    const storage = {getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); }};
    assert.equal(getTheme(storage), 'dark'); assert.equal(saveTheme('light', storage), false);
});
test('module registry has unique routes and includes all supported tools', () => {
    const modules = createModules();
    assert.equal(new Set(modules.map(module => module.id)).size, modules.length);
    assert.deepEqual(modules.map(module => module.id), ['dashboard','kvm','images','share','network','terminal','tools','power','settings']);
});
test('stopping an in-flight polling batch does not restart its timer', async () => {
    let release;
    const wait = new Promise(resolve => { release = resolve; });
    const store = new Store(), read = async () => { await wait; return {}; };
    const poller = new Poller({native: read, share: read, wifi: read, system: read}, store);
    poller.start(); poller.stop(); release();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(poller.running, false); assert.equal(poller.timer, null);
});
