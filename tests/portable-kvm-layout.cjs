const {closeBrowser}=require('./browser-cleanup.cjs');
// RC9 layout validation against localhost fixture only; no PiKVM connection.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');

(async()=>{
    const url=process.env.PORTABLE_TEST_URL||'http://127.0.0.1:8765/extras/portable-os/';
    if(!['localhost','127.0.0.1'].includes(new URL(url).hostname))throw Error('Local fixture required');
    const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});
    const output=path.resolve('private');fs.mkdirSync(output,{recursive:true});
    try{
        for(const [name,width,height]of [['desktop',1920,1080],['laptop',1366,768],['tablet',820,1180],['mobile',390,844]]){
            const context=await browser.newContext({viewport:{width,height},hasTouch:name==='mobile'||name==='tablet'});
            const page=await context.newPage();const errors=[];let loads=0;
            page.on('pageerror',error=>errors.push(error.message));
            page.on('request',request=>{if(new URL(request.url()).pathname==='/kvm/')loads++;});
            await page.goto(url+'#kvm');
            const frame=page.locator('iframe[src="/kvm/"]'),kvm=page.locator('.kvm-console');
            await kvm.locator('.kvm-controls').waitFor();
            await page.waitForFunction(()=>document.querySelector('.kvm-console').style.getPropertyValue('--kvm-ratio')==='1600 / 900');
            const frameNode=await frame.elementHandle();
            const videoNode=await frame.evaluateHandle(node=>node.contentDocument.getElementById('stream-image'));
            const box=()=>frame.boundingBox();const first=await box();
            const assertSize=async(expected=first)=>{const current=await box();assert.ok(Math.abs(current.width-expected.width)<.5,`${name}: video width changed`);assert.ok(Math.abs(current.height-expected.height)<.5,`${name}: video height changed`);};
            const controls=await kvm.locator('.kvm-controls').boundingBox();
            assert.ok(controls.y>=first.y+first.height-1,'Controls must be below video');
            assert.ok(Math.abs(first.width/first.height-16/9)<.01,'Actual stream ratio must be preserved');
            assert.equal(await kvm.locator('.kvm-subpanel').isVisible(),false);
            const names=['Lecteur ISO','Clé USB','ATX','Raccourcis','Macros','Texte','Vidéo & HID'];
            for(let cycle=0;cycle<3;cycle++){
                for(const title of names){
                    const button=kvm.getByRole('button',{name:title,exact:true});
                    await button.click();await assertSize();
                    assert.equal(await button.getAttribute('aria-expanded'),'true');
                    assert.equal(await kvm.locator('.kvm-controls button[aria-expanded=true]').count(),1);
                    // Sample both rectangles in the same layout frame: async SHARE
                    // telemetry can change document height between protocol calls.
                    const {bar,panel}=await kvm.evaluate(node=>{
                        const rect=selector=>{const r=node.querySelector(selector).getBoundingClientRect();return {y:r.y,height:r.height};};
                        return {bar:rect('.kvm-controls'),panel:rect('.kvm-subpanel')};
                    });
                    assert.ok(panel.y>=bar.y+bar.height-1,`${name}/${title}: panel below controls ${JSON.stringify({bar,panel})}`);
                }
                await kvm.getByRole('button',{name:'Vidéo & HID',exact:true}).click();
                assert.equal(await kvm.locator('.kvm-subpanel').isVisible(),false);await assertSize();
            }
            const drive=kvm.getByRole('button',{name:'Lecteur ISO',exact:true});await drive.hover();
            const beforeScroll=await page.evaluate(()=>scrollY);await drive.click();
            assert.ok(Math.abs(await page.evaluate(()=>scrollY)-beforeScroll)<1,'Opening must not impose scrolling');
            assert.equal(await kvm.locator('.native-notice td[rowspan="2"]').count(),1,'Preserve native table spans');
            await frame.evaluate(node=>{
                const doc=node.contentDocument,group=doc.createElement('div');group.id='layout-long-fixture';
                group.innerHTML='<table class="kv"><tbody>'+Array.from({length:32},(_,i)=>`<tr><td>Paramètre ${i+1}</td><td><input value="Valeur ${i+1}"></td></tr>`).join('')+'</tbody></table><button id="layout-last-control">Dernière commande simulée</button>';
                group.querySelector('button').onclick=()=>node.contentWindow.lifecycle.lastControl=(node.contentWindow.lifecycle.lastControl||0)+1;
                doc.querySelector('#msd-dropdown .menu').append(group);
            });
            const last=kvm.locator('[data-native-id="layout-last-control"]');await last.waitFor();
            const panelState=await kvm.locator('.kvm-subpanel').evaluate(node=>({overflow:getComputedStyle(node).overflowY,max:getComputedStyle(node).maxHeight,height:node.clientHeight,scroll:node.scrollHeight}));
            assert.equal(panelState.max,'none');assert.equal(panelState.overflow,'visible');assert.ok(panelState.height>=panelState.scroll-1);
            await last.scrollIntoViewIfNeeded();await last.click();
            assert.equal(await frame.evaluate(node=>node.contentWindow.lifecycle.lastControl),1);
            assert.ok(await page.evaluate(()=>document.scrollingElement===document.documentElement&&scrollY>0),'The document must scroll to the final control');
            await assertSize();
            await frame.evaluate(node=>node.contentDocument.getElementById('layout-long-fixture').remove());
            await last.waitFor({state:'detached'});
            await page.evaluate(()=>scrollTo(0,0));
            assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No horizontal page overflow');
            await page.screenshot({path:path.join(output,`portable-os-rc9-${name}.png`),fullPage:true});
            assert.equal(await frameNode.evaluate(node=>node===document.querySelector('iframe[src="/kvm/"]')),true);
            assert.equal(await videoNode.evaluate(node=>node===node.ownerDocument.getElementById('stream-image')),true);
            assert.equal(loads,1,'Opening panels must never reload the native iframe');
            if(name==='desktop'){
                await kvm.getByRole('button',{name:'Fermer',exact:true}).click();
                await kvm.getByRole('button',{name:'Plein écran',exact:true}).click();
                await page.waitForFunction(()=>!!document.fullscreenElement);
                const full=await box();await drive.click();await assertSize(full);
                await kvm.getByRole('button',{name:'ATX',exact:true}).click();await assertSize(full);
                await page.evaluate(()=>document.exitFullscreen());
                await assertSize();
                await frame.evaluate(node=>{node.contentDocument.querySelector('.window-grab').textContent='MJPEG - 1024x768';node.contentDocument.getElementById('stream-image').classList.add('hidden');});
                await page.waitForFunction(()=>document.querySelector('.kvm-console').style.getPropertyValue('--kvm-ratio')==='1024 / 768');
                const changed=await box();assert.ok(Math.abs(changed.width/changed.height-4/3)<.01,'Resolution changes may update the ratio');
                await page.setViewportSize({width:1280,height:768});
                const narrower=await box();assert.ok(narrower.width<changed.width,'Viewport width changes must still resize video');
                assert.ok(Math.abs(narrower.width/narrower.height-4/3)<.01);
                await drive.click();await assertSize(narrower);
                assert.equal(loads,1);
            }
            assert.deepEqual(errors,[]);await context.close();
            process.stdout.write(`RC9 layout passed: ${name} ${width}x${height}.\n`);
        }
    }finally{await closeBrowser(browser);}
})().catch(error=>{console.error(error);process.exitCode=1;});
