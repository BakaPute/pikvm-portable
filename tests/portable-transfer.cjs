// Isolated real DOM and mocked API. No user images or PiKVM endpoints.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');

(async () => {
    const base = new URL(process.env.PORTABLE_TEST_URL || 'http://127.0.0.1:8765/');
    if (!['127.0.0.1', 'localhost'].includes(base.hostname)) throw new Error('localhost only');
    const browser = await chromium.launch({headless: true, ...(process.platform === 'win32' ? {channel: 'msedge'} : {})});
    try {
        const page = await browser.newPage();
        let image = '', state = 'ready', unknown = false, failure = false, delayed = false;
        let activeReads = 0, maxReads = 0, nativeWrites = 0;
        const actions = [], errors = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('dialog', dialog => dialog.accept());
        await page.route('**/__test/transfer-fixture', route => route.fulfill({contentType:'text/html',
            body:'<meta charset="utf-8"><div id="msd-menu"><div class="buttons buttons-row"><button>Native</button></div></div><script src="/share/js/usb-transfer.js"></script>'}));
        const handleRoute = async route => {
            const request = route.request(), url = new URL(request.url());
            const fulfill = (body, status = 200) => route.fulfill({status, contentType:'application/json', body:JSON.stringify(body)});
            if (url.pathname === '/api/msd') return fulfill({ok:true, result:{drive:{connected:Boolean(image)}}});
            if (url.pathname.startsWith('/api/msd/')) { nativeWrites++; return fulfill({ok:true}); }
            if (url.pathname.endsWith('/folders')) return fulfill({ok:true, result:{folders:[]}});
            if (url.pathname.endsWith('/usb-transfer/status')) {
                activeReads++; maxReads = Math.max(maxReads, activeReads);
                if (delayed) await new Promise(resolve => setTimeout(resolve, 2200));
                activeReads--;
                if (failure) return fulfill({ok:false, error:'Diagnostic USB indisponible'}, 503);
                return fulfill({ok:true, transfer:{state, exists:true, message:state === 'ready' ? 'Source conservée' : 'État ' + state,
                    drive:{known:!unknown, image, transfer_active:image === 'transfer'}}});
            }
            const action = url.pathname.split('/').pop();
            actions.push({action, body:request.postDataJSON(), header:request.headers()['x-pikvm-share']});
            if (action === 'start') { image = 'transfer'; state = 'connected'; }
            if (action === 'stop' && image) return fulfill({ok:false, error:'Éjecter proprement côté PC'}, 409);
            if (action === 'stop') state = 'ready';
            if (action === 'import') state = 'importing';
            return fulfill({ok:true, transfer:{state, message:'Source conservée'}, message:'Import demandé'});
        };
        await page.route('**/api/**', handleRoute);
        await page.goto(new URL('/__test/transfer-fixture', base).href);
        const start = page.locator('#pk-usb-transfer-start'), finish = page.locator('#pk-usb-transfer-finish');
        const importer = page.locator('#pk-usb-transfer-import'), status = page.locator('#pk-usb-transfer-status');
        await start.waitFor();
        await page.waitForFunction(() => !document.querySelector('#pk-usb-transfer-finish').disabled);
        const stopped = page.waitForResponse(response => response.url().endsWith('/usb-transfer/stop'));
        await finish.click();
        await stopped;
        await page.waitForFunction(() => document.querySelector('#pk-usb-transfer-status').textContent.includes('Source conservée'));
        assert.deepEqual(actions.map(a => a.action), ['stop'], 'Finish must not import or reset');
        await start.click();
        await page.waitForFunction(() => document.querySelector('#pk-usb-transfer-start').disabled);
        assert.deepEqual(actions.at(-1), {action:'start', body:{allow_usb_reset:true}, header:'1'});
        image = ''; state = 'ready'; // Controlled simulated Windows eject, no native POST.
        await page.waitForFunction(() => !document.querySelector('#pk-usb-transfer-import').disabled);
        await importer.click();
        await page.waitForFunction(() => document.querySelector('#pk-usb-transfer-import').disabled);
        assert.equal(actions.at(-1).action, 'import');
        assert.equal(actions.at(-1).header, '1');
        state = 'done';
        await page.waitForFunction(() => document.querySelector('#pk-usb-transfer-status').textContent.includes('Import terminé'));
        assert.equal(nativeWrites, 0, 'Polling done must never mutate native Drive 0');
        unknown = true; state = 'unknown';
        await page.waitForFunction(() => document.querySelector('#pk-usb-transfer-start').disabled && document.querySelector('#pk-usb-transfer-import').disabled);
        assert.match(await status.innerText(), /unknown/);
        unknown = false; failure = true;
        await page.waitForFunction(() => document.querySelector('#pk-usb-transfer-status').textContent.includes('indisponible'));
        assert.equal(await start.isDisabled(), true);
        assert.equal(await finish.isDisabled(), true);
        assert.equal(await importer.isDisabled(), true);
        failure = false; delayed = true;
        await page.waitForTimeout(4800);
        assert.equal(maxReads, 1, 'Slow polls must never accumulate');
        delayed = false;
        await page.close();
        state = 'ready'; image = ''; unknown = failure = false;
        const legacy = await browser.newPage();
        legacy.on('dialog', dialog => dialog.accept());
        legacy.on('pageerror', error => errors.push(error.message));
        await legacy.route('**/api/**', handleRoute);
        await legacy.goto(new URL('/extras/image-manager/', base).href);
        await legacy.waitForFunction(() => !document.querySelector('#usbFinish').disabled);
        const legacyStop = legacy.waitForResponse(response => response.url().endsWith('/usb-transfer/stop'));
        await legacy.locator('#usbFinish').click(); await legacyStop;
        assert.equal(actions.at(-1).action, 'stop');
        assert.equal(actions.at(-1).header, '1', 'Legacy management must retain CSRF authentication headers');
        const legacyImport = legacy.waitForResponse(response => response.url().endsWith('/usb-transfer/import'));
        await legacy.locator('#usbImport').click(); await legacyImport;
        assert.equal(actions.at(-1).action, 'import');
        assert.equal(actions.at(-1).header, '1');
        assert.deepEqual(errors, []);
        assert.equal(nativeWrites, 0);
        console.log('USB lifecycle browser: separate stop/import, explicit USB reset, unknown/error gates, no polling mutations, one pending poll: passed');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
