const {closeBrowser}=require('./browser-cleanup.cjs');
// Real browser + upstream KVMD 4.213 DOM/controllers. All APIs/media are synthetic.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');

(async()=>{
    const url=process.env.PORTABLE_TEST_URL||'http://127.0.0.1:8765/extras/portable-os/';
    const origin=new URL(url).origin;
    if(!['127.0.0.1','localhost'].includes(new URL(url).hostname))throw Error('Local synthetic server required');
    const fixture=path.join(__dirname,'fixtures/kvmd-4.213');
    const provenance=JSON.parse(fs.readFileSync(path.join(fixture,'SHA256.json'),'utf8'));
    for(const [file,digest]of Object.entries(provenance))assert.equal(crypto.createHash('sha256').update(fs.readFileSync(path.join(fixture,file))).digest('hex'),digest,file);
    const names=['Windows/Win10/Windows 10 test.iso','Windows/Win11/Windows 11 test.iso','Windows/Win11/Windows 11 PE.iso',
        'Linux/Debian/Debian test.iso','Linux/Debian/Debian live.iso','Linux/Ubuntu/Ubuntu test.iso','Linux/Ubuntu/Ubuntu live.iso'];
    const image=name=>({name,size:1048576,mtime:100,mod_ts:100,complete:true,in_storage:true,removable:true});
    const state={enabled:true,online:true,busy:false,drive:{connected:false,cdrom:true,rw:false,image:null},
        storage:{images:Object.fromEntries([...names,'.USB-TRANSFER.img'].map(name=>[name,image(name)])),
            parts:{'':{size:8*1024**3,free:7*1024**3,writable:true}},uploading:null,downloading:false}};
    let share={mode:'usb',attached:true,uploads:0},shareError=0,msdError=0,transferBusy=false,msdReadError=false;
    const posts=[],alerts=[],errors=[],requests=[];
    const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});
    try{
        const page=await browser.newPage({viewport:{width:1440,height:1060}});
        page.setDefaultTimeout(10000);
        page.on('pageerror',error=>{errors.push(error.message);console.error('Browser error:',error.stack);});
        page.on('dialog',async dialog=>{alerts.push(dialog.message());await dialog.accept();});
        await page.route('**/*',async route=>{
            const request=route.request(),u=new URL(request.url()),p=u.pathname;
            if(u.origin!==origin)return route.abort(); // No external service or real Pi.
            requests.push([request.method(),p]);
            const json=(result,status=200)=>route.fulfill({status,json:{ok:status===200,...(status===200?{result}:{error:result})}});
            if(p==='/kvm/'){
                const html=fs.readFileSync(path.join(fixture,'web/kvm/index.html'),'utf8')
                    .replace(/<script type="module">[\s\S]*?<\/script>/,'<script type="module" src="/__test/native-kvm-4213.js"></script>');
                return route.fulfill({contentType:'text/html',body:html});
            }
            if(p==='/__test/native-kvm-4213.js')return route.fulfill({contentType:'application/javascript',body:fs.readFileSync(path.join(__dirname,'fixtures/native-kvm-4213.js'))});
            const relative=p.startsWith('/__test/kvmd-4.213/')?p.slice('/__test/kvmd-4.213/'.length):p.startsWith('/share/css/')?'web'+p:null;
            if(relative){
                const file=path.resolve(fixture,relative);
                assert.ok(file.startsWith(fixture+path.sep));
                return route.fulfill({contentType:file.endsWith('.css')?'text/css':'application/javascript',body:fs.existsSync(file)?fs.readFileSync(file):''});
            }
            if(p==='/api/msd')return msdReadError?json('Lecture MSD synthétique indisponible',503):json(state);
            if(p.startsWith('/api/msd/')&&request.method()==='POST'){
                posts.push([p,Object.fromEntries(u.searchParams)]);
                if(msdError)return json('Refus KVMD synthétique',msdError);
                assert.equal(state.busy,false);assert.ok(['/api/msd/set_params','/api/msd/set_connected'].includes(p),'No reset/delete/format');
                if(p.endsWith('set_params')){
                    assert.equal(state.drive.connected,false);
                    if(u.searchParams.has('image')){
                        const name=u.searchParams.get('image');assert.ok(!name||names.includes(name));
                        state.drive.image=name?image(name):null;
                    }
                    for(const key of ['cdrom','rw'])if(u.searchParams.has(key))state.drive[key]=['1','true'].includes(u.searchParams.get(key));
                }else state.drive.connected=['1','true'].includes(u.searchParams.get('connected'));
                return json({});
            }
            if(p==='/extras/wifi-wizard/api/usb-transfer/status')return route.fulfill({json:{ok:true,transfer:{drive:{known:true,transfer_active:transferBusy},busy:transferBusy,state:'ready'}}});
            if(p==='/extras/pikvm-share/api/status')return shareError?json('Drive 1 occupé synthétique',shareError):json(share);
            if(request.method()!=='GET'&&p.includes('/api/')){
                posts.push([p,request.postData()]);throw Error('Unexpected mutation: '+p);
            }
            return route.continue();
        });
        await page.goto(url+'#kvm');
        const kvm=page.locator('.kvm-console'),controls=kvm.locator('.kvm-controls'),panel=kvm.locator('.kvm-subpanel');
        await controls.waitFor();
        const iframe=page.frameLocator('iframe[src="/kvm/"]');
        const frame=()=>page.frames().find(frame=>new URL(frame.url()).pathname==='/kvm/');
        await page.waitForFunction(()=>!!document.querySelector('iframe[src="/kvm/"]')?.contentWindow.native4213);
        const push=()=>frame().evaluate(()=>window.native4213.refresh());
        const proxy=id=>panel.locator(`[data-native-id="${id}"]`);
        const iso=controls.getByRole('button',{name:'Lecteur ISO',exact:true}),usb=controls.getByRole('button',{name:'Clé USB',exact:true});
        assert.equal(await iso.evaluate(node=>node.nextElementSibling.textContent),'Clé USB');
        const beforeVideo=await kvm.locator('iframe').elementHandle();
        async function hid(){
            await controls.getByRole('button',{name:/^(Activer|Désactiver) clavier/}).evaluate(node=>{if(node.getAttribute('aria-pressed')!=='true')node.click();});
            await kvm.locator('iframe').scrollIntoViewIfNeeded();
            assert.equal(await page.locator('dialog[open]').count(),0);
            const start=await frame().evaluate(()=>window.native4213.hidEvents.length);
            await iframe.locator('#stream-window').focus();await page.keyboard.press('a');
            await iframe.locator('#stream-box').click();
            const events=await frame().evaluate(n=>window.native4213.hidEvents.slice(n),start);
            assert.ok(events.some(e=>e.event_type==='key'&&e.event.state),'Native keyboard press');
            assert.ok(events.some(e=>e.event_type==='key'&&!e.event.state),'Native keyboard release');
            assert.ok(events.some(e=>e.event_type==='mouse_button'&&e.event.state),'Native mouse press');
            assert.ok(events.some(e=>e.event_type==='mouse_button'&&!e.event.state),'Native mouse release');
        }
        await hid();
        await iso.click();
        const chooser=page.getByRole('dialog',{name:'Choisir une image ISO',exact:true});
        const open=async()=>{await proxy('pkdf-launch').click();await chooser.waitFor();};
        const entries=()=>chooser.locator('[data-native-id="pkdf-items"]');
        const entry=name=>entries().getByRole('button',{name:new RegExp(name)});
        await open();
        assert.equal(await frame().evaluate(()=>getComputedStyle(document.getElementById('pkdf-overlay')).display),'none','Reproduce hidden native overlay root cause');
        await entry('Windows').click();await entry('Win10').click();
        await entry('Windows 10 test.iso').waitFor();
        assert.equal(await entries().getByRole('button',{name:/Windows 10 test.iso/}).count(),1);
        await entry('Windows 10 test.iso').click();await chooser.waitFor({state:'hidden'});await push();
        assert.equal(state.drive.image.name,names[0]);
        assert.deepEqual(posts.at(-1),['/api/msd/set_params',{image:names[0],cdrom:'1',rw:'0'}]);
        await proxy('msd-connect-button').click();await push();
        assert.equal(state.drive.connected,true);await proxy('msd-status').filter({hasText:'Connected to the host'}).waitFor();
        assert.equal(await proxy('msd-mode-radio-0').isDisabled(),true);
        await open();await entry('Windows 10 test.iso').waitFor();assert.equal(await entry('Windows 10 test.iso').isDisabled(),true);
        const before=posts.length;await chooser.getByRole('button',{name:'Fermer le sélecteur'}).click();await chooser.waitFor({state:'hidden'});assert.equal(posts.length,before);
        await proxy('msd-disconnect-button').click();await push();assert.equal(state.drive.connected,false);
        await open();await chooser.getByRole('button',{name:'Stockage',exact:true}).click();
        await entry('Linux').click();await entry('Debian').click();await entry('Dossier parent').click();await entry('Ubuntu').click();
        await entry('Ubuntu test.iso').click();await chooser.waitFor({state:'hidden'});await push();assert.equal(state.drive.image.name,names[5]);
        const change=async id=>{
            await page.waitForFunction(id=>{
                const source=document.querySelector('iframe[src="/kvm/"]').contentDocument.getElementById(id);
                const target=document.querySelector(`[data-native-id="${id}"]`);
                return target&&!target.disabled&&target.checked===source.checked&&!source.checked;
            },id);
            const response=page.waitForResponse(r=>r.url().includes('/api/msd/set_params?cdrom='));
            await proxy(id).check();await response;await push();
        };
        await change('msd-mode-radio-0');assert.equal(state.drive.cdrom,false,'Native Flash mode');
        await change('msd-mode-radio-1');assert.equal(state.drive.cdrom,true,'Native CD/DVD mode');
        await proxy('msd-connect-button').click();await push();await proxy('msd-disconnect-button').click();await push();
        // Search traverses all folders, hides transfer containers, and handles spaces.
        await open();await chooser.locator('[data-native-id="pkdf-search"]').fill('Windows 11');
        await entry('Windows 11 test.iso').waitFor();assert.equal(await entries().getByText('.USB-TRANSFER.img').count(),0);
        msdReadError=true;await entry('Windows 11 test.iso').click();await page.waitForTimeout(200);
        assert.match(alerts.at(-1),/Lecture MSD synthétique/);msdReadError=false;
        transferBusy=true;let n=posts.length;await entry('Windows 11 test.iso').click();
        await page.waitForFunction(()=>!document.querySelector('iframe[src="/kvm/"]').contentDocument.getElementById('pkdf-panel').hidden);
        await page.waitForTimeout(200);assert.equal(posts.length,n);assert.match(alerts.at(-1),/transfert actif/);transferBusy=false;
        msdError=409;await entry('Windows 11 test.iso').click();await page.waitForTimeout(200);assert.match(alerts.at(-1),/Refus KVMD/);msdError=0;
        await page.keyboard.press('Escape');await chooser.waitFor({state:'hidden'});
        await open();await chooser.locator('[data-native-id="pkdf-search"]').fill('');await chooser.getByRole('button',{name:'Stockage',exact:true}).click();
        state.busy=true;await push();await chooser.getByRole('button',{name:'Fermer le sélecteur'}).click();await chooser.waitFor({state:'hidden'});await open();
        await chooser.getByText('Drive occupé : sélection indisponible pour le moment.').waitFor();
        state.busy=false;await push();await page.keyboard.press('Escape');await chooser.waitFor({state:'hidden'});
        // Real KVMD modal error is also projected, without changing native logic.
        msdError=409;await proxy('msd-connect-button').click();
        const modal=page.getByRole('dialog',{name:'Confirmation KVMD'});await modal.waitFor();
        await modal.getByText(/Refus KVMD/).waitFor();await modal.getByRole('button',{name:'OK',exact:true}).click();await modal.waitFor({state:'hidden'});msdError=0;
        await hid();
        n=posts.length;await usb.click();await panel.getByText('Drive 1 · USB attaché',{exact:true}).waitFor();
        await panel.getByText(/Éjecte proprement/).waitFor();assert.equal(posts.length,n,'Opening is GET only');
        share={mode:'web',attached:false,uploads:1};await panel.getByRole('button',{name:'Actualiser'}).click();await panel.getByText(/transfert occupé/).waitFor();
        assert.equal(posts.length,n);shareError=423;await panel.getByRole('button',{name:'Actualiser'}).click();await panel.getByText(/État Drive 1 indisponible : Drive 1 occupé/).waitFor();
        assert.equal(posts.length,n);shareError=0;share={mode:'web',attached:false,uploads:0};
        await panel.getByRole('button',{name:'Actualiser'}).click();await panel.getByText('Drive 1 · Gestion Web',{exact:true}).waitFor();
        await panel.getByRole('link',{name:'Gérer PIKVM-SHARE'}).click();await page.getByRole('heading',{name:'PIKVM-SHARE',exact:true}).waitFor();
        await page.locator('[data-route="kvm"]').click();await controls.waitFor();await hid();
        assert.equal(await beforeVideo.evaluate(node=>node===document.querySelector('.kvm-console iframe')),true,'No engine reload');
        await iso.click();await open();await page.locator('[data-route="dashboard"]').evaluate(node=>node.click());await chooser.waitFor({state:'hidden'});
        await page.locator('[data-route="kvm"]').click();assert.equal(await chooser.count(),0,'No stale selector on return');
        await iso.click();await open();
        const searchHidStart=await frame().evaluate(()=>window.native4213.hidEvents.length);
        await chooser.locator('[data-native-id="pkdf-search"]').pressSequentially('Ubuntu');await entry('Ubuntu live.iso').waitFor();
        assert.equal(await frame().evaluate(n=>window.native4213.hidEvents.slice(n).filter(e=>e.event_type==='key'&&e.event.state).length,searchHidStart),0,'Search keys never go to remote host');
        fs.mkdirSync(path.resolve('private'),{recursive:true});
        await page.screenshot({path:path.resolve('private/portable-os-rc10.2-native-selector.png')});
        await page.setViewportSize({width:390,height:844});
        assert.ok(await chooser.evaluate(node=>{const r=node.getBoundingClientRect();return r.width<=innerWidth&&r.top>=0&&r.bottom<=innerHeight;}),'Responsive selector fits the viewport');
        await page.screenshot({path:path.resolve('private/portable-os-rc10.2-native-selector-mobile.png')});
        await page.keyboard.press('Escape');await chooser.waitFor({state:'hidden'});await page.setViewportSize({width:1440,height:1060});
        await usb.click();shareError=401;await panel.getByRole('button',{name:'Actualiser'}).click();
        await page.locator('#session-alert').waitFor();assert.equal(await panel.isVisible(),false,'Expiry suspends the entire adapter');
        assert.equal(await controls.getByRole('button',{name:'Activer clavier / souris',exact:true}).isDisabled(),true);
        assert.deepEqual(errors,[]);
        assert.ok(posts.every(([p])=>p.startsWith('/api/msd/')),'No SHARE mutation, GPIO, power, reset or file deletion');
        console.log('PASS KVMD 4.213 native DOM/MSD/window manager/keyboard/mouse + synthetic API: selector, nested folders, modes, connect/eject, errors, SHARE, HID, lifecycle, auth');
    }finally{await closeBrowser(browser);}
})().catch(error=>{console.error(error);process.exitCode=1;});
