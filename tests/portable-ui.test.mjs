import test from 'node:test';
import assert from 'node:assert/strict';
import {Store, visibleImages, usbEvidence, powerSafe, bytes} from '../web/extras/portable-os/core/state.js';
import {Client, ApiError, Poller} from '../web/extras/portable-os/core/api.js';
import {nativeRoute, releaseNativeInput} from '../web/extras/portable-os/core/native-bridge.js';
import {getTheme, saveTheme} from '../web/extras/portable-os/core/preferences.js';
import {createModules} from '../web/extras/portable-os/modules/index.js';
import {routes, extensionLink} from '../web/legacy/routes.js';
import {nativeMenus} from '../web/extras/portable-os/core/kvm-adapter.js';
import {unpackPixels} from '../web/extras/portable-os/modules/oled.js';
import {OledInput} from '../web/extras/portable-os/core/oled-input.js';
import {streamSize} from '../web/extras/portable-os/core/stream-size.js';

test('stream ratio follows decoded media and native status, never panel geometry',()=>{
    const nodes={};const doc={getElementById:id=>nodes[id],querySelector:()=>({textContent:'MJPEG - 1920x1080 / 30 FPS'})};
    const media=attrs=>({hidden:false,classList:{contains:()=>false},style:{},getAttribute:()=>'',hasAttribute:()=>false,...attrs});
    nodes['stream-image']=media({naturalWidth:640,naturalHeight:480});
    assert.deepEqual(streamSize(doc),{width:640,height:480});
    nodes['stream-video']=media({videoWidth:1280,videoHeight:720});
    assert.deepEqual(streamSize(doc),{width:1280,height:720});
    nodes['stream-video'].hidden=true;nodes['stream-image'].getAttribute=()=>'/blank-stream.webp';
    assert.deepEqual(streamSize(doc),{width:1920,height:1080});
    doc.querySelector=()=>null;assert.equal(streamSize(doc),null);
    nodes['stream-canvas']=media({width:1440,height:1080,hasAttribute:()=>true});
    assert.deepEqual(streamSize(doc),{width:1440,height:1080});
});

test('OLED release is sent before the delayed start response, without a late keep',async()=>{
    let resolveStart;const actions=[];
    const input=new OledInput(data=>{actions.push(data.action);return data.action==='start'?new Promise(resolve=>resolveStart=resolve):Promise.resolve();},()=>{}, {nonce:()=> 'a'.repeat(32)});
    input.start('b'.repeat(64));input.end();
    assert.deepEqual(actions,['start','stop']);resolveStart();await new Promise(resolve=>setImmediate(resolve));
    assert.deepEqual(actions,['start','stop']);assert.equal(input.active,null);
});
test('OLED keep cadence does not add request latency and never extends server leases',async()=>{
    let now=0,scheduled;const input=new OledInput(async data=>{if(data.action==='keep')now+=350;},()=>{},
        {clock:()=>now,timer:(fn,delay)=>{scheduled=delay;return 1;},clear:()=>{},nonce:()=> 'a'.repeat(32)});
    input.start('b'.repeat(64));await new Promise(resolve=>setImmediate(resolve));
    assert.equal(scheduled,0);assert.equal(input.metrics.last_keep_ms,350);input.end(true);
});
test('a real control channel failure cancels the held input',async()=>{
    const actions=[];const input=new OledInput(async data=>{actions.push(data.action);if(data.action==='keep')throw new Error('network lost');},()=>{}, {nonce:()=> 'a'.repeat(32)});
    input.start('b'.repeat(64));await new Promise(resolve=>setImmediate(resolve));
    assert.equal(input.active,null);assert.deepEqual(actions,['start','keep','cancel']);
});

test('OLED decodes the exact 128×64 monochrome MSB framebuffer, without a second renderer', () => {
    const raw = Buffer.alloc(1024); raw[0] = 128; raw[1023] = 1;
    const pixels = unpackPixels(raw.toString('base64'));
    assert.equal(pixels.length, 128 * 64 * 4);
    assert.deepEqual([...pixels.slice(0, 4)], [212,247,230,255]);
    assert.deepEqual([...pixels.slice(4, 8)], [5,10,9,255]);
    assert.deepEqual([...pixels.slice(-4)], [212,247,230,255]);
    assert.throws(() => unpackPixels(''), /incompatible/);
});

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

test('visibility stop/start during a pending batch never creates two polling timers',async()=>{
    let release;const wait=new Promise(resolve=>release=resolve),timers=[];
    const store=new Store(),read=async()=>{await wait;return {};};
    const poller=new Poller({native:read,share:read,wifi:read,system:read},store);
    const oldTimer=globalThis.setTimeout,oldDocument=globalThis.document;
    globalThis.document={hidden:false};globalThis.setTimeout=fn=>{timers.push(fn);return 1;};
    try {
        poller.start();poller.stop();poller.start();release();
        await new Promise(resolve=>setImmediate(resolve));
        assert.equal(timers.length,1);
    } finally {poller.stop();globalThis.setTimeout=oldTimer;globalThis.document=oldDocument;}
});
