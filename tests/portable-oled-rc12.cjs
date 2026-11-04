// Actual logical transport + Python RC12 navigation/rendering; synthetic ISO only.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
    const url=process.env.PORTABLE_TEST_URL||'http://127.0.0.1:8765/extras/portable-os/';
    const origin=new URL(url).origin;
    if(!['127.0.0.1','localhost'].includes(new URL(url).hostname))throw Error('Local fixture required');
    const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});
    try{
        const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];const posts=[];
        page.on('pageerror',e=>errors.push(e.message));
        page.on('request',r=>{if(r.method()==='POST')posts.push(new URL(r.url()).pathname);});
        await page.request.post(origin+'/__test/reset',{headers:{'X-Portable-Test':'1'}});
        await page.request.post(origin+'/__test/oled-rc12',{headers:{'X-Portable-Test':'1'}});
        const state=async()=>await(await page.request.get(origin+'/__test/oled-rc12')).json();
        const frame=async()=>await(await page.request.get(origin+'/extras/portable-os/api/oled')).json();
        await page.goto(url);await page.locator('#test-alert').waitFor({state:'visible'});
        await page.locator('#device-oled').click();
        const screen=page.locator('#oled-sidebar .oled-screen');await screen.waitFor();
        await page.locator('#oled-sidebar .oled-status').filter({hasText:'1 avancer'}).waitFor();
        async function sync(){const f=(await frame()).result;await page.waitForFunction(p=>{
            const bytes=atob(p);const rgba=document.querySelector('#oled-sidebar canvas').getContext('2d').getImageData(0,0,128,64).data;
            for(let i=0;i<8192;i++)if((rgba[i*4]===212)!==!!(bytes.charCodeAt(i>>3)&(128>>(i&7))))return false;
            return true;
        },f.pixels);}
        async function waitScreen(name){await page.waitForFunction(async name=>{
            const r=await fetch('/__test/oled-rc12');return (await r.json()).screen===name;
        },name);await sync();await page.waitForTimeout(250);}
        async function next(){await screen.click({delay:60});await page.waitForTimeout(650);await sync();}
        async function open(){await screen.dblclick({delay:75});await page.waitForTimeout(300);}
        async function select(id){
            // Advance by actual UI clicks, never set navigation state through test APIs.
            const order={menu:['power','wifi','network','iso','home'],'iso-root':['browse','favorites','recent','eject','refresh','back'],
                iso:['back','item'],'iso-action':['back','cdrom','flash','favorite','info'],power:['back','restart','shutdown']};
            for(let n=0;n<8;n++){
                const f=(await frame()).result,c=f.context;if(order[c.screen]?.[c.selection]===id){await open();return;}
                await next();
            }throw Error('Selection not reached: '+id);
        }
        await open();await waitScreen('menu');assert.deepEqual((await state()).calls,[]);
        await select('iso');await waitScreen('iso-root');assert.ok((await state()).calls.every(c=>c[0]==='library'));
        await select('browse');await waitScreen('iso');await select('item');await waitScreen('iso');
        await select('item');await waitScreen('iso');await select('item');await waitScreen('iso-action');
        await select('cdrom');await waitScreen('iso-connect-confirm');
        assert.ok(!(await state()).calls.some(c=>c[0]==='connect'));await open();await waitScreen('iso-root');
        assert.ok((await state()).calls.some(c=>c[0]==='connect'&&c[1]==='Linux/Debian/Synthetic test.iso'&&c[2]===true));
        await select('eject');await waitScreen('iso-eject-confirm');await open();await waitScreen('iso-root');
        assert.ok((await state()).calls.some(c=>c[0]==='eject'&&c[1]===true));
        await screen.hover();await page.mouse.down();await page.waitForTimeout(1350);await page.mouse.up();await waitScreen('menu');
        await select('power');await waitScreen('power');await select('shutdown');await waitScreen('power-confirm');
        const arm=page.locator('#oled-sidebar .oled-arm');await arm.waitFor({state:'visible'});
        assert.equal(await arm.locator('input').isChecked(),false);
        await screen.click({delay:60});await waitScreen('power');
        assert.equal((await state()).error,null);
        await page.locator('[data-route="settings"]').evaluate(n=>n.click());
        await page.getByRole('navigation',{name:'Catégories des paramètres'}).getByRole('button',{name:'OLED et écrans',exact:true}).click();
        const preview=page.getByLabel('Page OLED à prévisualiser');await preview.selectOption('menu-iso-info');
        await page.getByText('Menu natif avec données d’exemple ; aucune action exécutée.',{exact:true}).waitFor();
        await page.locator('[data-setting="oled_style"]').selectOption('detailed');
        await page.getByRole('button',{name:'Appliquer',exact:true}).click();await page.reload();
        await page.getByRole('navigation',{name:'Catégories des paramètres'}).getByRole('button',{name:'OLED et écrans',exact:true}).click();
        assert.equal(await page.locator('[data-setting="oled_style"]').inputValue(),'detailed');
        fs.mkdirSync('private',{recursive:true});await page.screenshot({path:'private/portable-os-rc12-oled-settings.png',fullPage:true});
        assert.deepEqual(errors,[]);assert.ok(!posts.some(p=>p.includes('/api/msd/')||p.includes('/api/hid/')||p.includes('mode/usb')));
        console.log('RC12 OLED browser passed: exact pixels, single/double/back, nested synthetic ISO, readonly mount/eject confirmation, power cancellation, preview and persistence.');
    }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
