const {closeBrowser}=require('./browser-cleanup.cjs');
// RC12.1: real settings validator + renderer, temporary preferences, localhost only.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
    const url=process.env.PORTABLE_TEST_URL||'http://127.0.0.1:8765/extras/portable-os/';
    if(!['localhost','127.0.0.1'].includes(new URL(url).hostname))throw Error('Local synthetic fixture required');
    const origin=new URL(url).origin;
    const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});
    let page,originalValues;
    try{
        page=await browser.newPage({viewport:{width:1440,height:1060}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
        const get=async()=>await(await page.request.get(origin+'/extras/portable-os/api/settings')).json();
        let state=(await get()).result;
        originalValues=state.values;
        const old=JSON.parse(fs.readFileSync('tests/fixtures/rc12-settings.json','utf8'));
        const imported=await page.request.post(origin+'/extras/portable-os/api/settings/import',{headers:{'X-Pikvm-Share':'1'},data:{expected_revision:state.revision,confirmed:true,config:{format:'pikvm-portable-settings',schema_version:2,values:old.values}}});
        assert.equal(imported.status(),200);state=(await get()).result;
        assert.equal(state.schema_version,3);assert.equal(state.values.oled_style,'compact');assert.equal(state.values.theme,'light');
        assert.deepEqual(state.values.oled_pages.slice(0,6),old.values.oled_pages);
        assert.deepEqual(Object.keys(state.fields.oled_style.choices),['readable','compact']);
        await page.goto(url+'#settings');
        const nav=page.getByRole('navigation',{name:'Catégories des paramètres'});
        await nav.getByRole('button',{name:'OLED et écrans',exact:true}).click();
        const selector=page.getByLabel('Page OLED à prévisualiser');await selector.selectOption('system');
        await page.getByText(/Même moteur natif.*données d’exemple/).waitFor();
        const canvas=page.getByLabel('Aperçu OLED du brouillon');const before=await canvas.evaluate(n=>n.toDataURL());
        await page.locator('[data-setting="oled_style"]').selectOption('readable');
        await page.waitForFunction(before=>document.querySelector('canvas[aria-label="Aperçu OLED du brouillon"]').toDataURL()!==before,before);
        await page.getByRole('checkbox',{name:'Activer Mémoire et durée',exact:true}).check();
        await page.getByLabel('Durée Mémoire et durée',{exact:true}).fill('7');
        await page.getByRole('checkbox',{name:'Activer Connexion et signal',exact:true}).check();
        await page.getByLabel('Durée Connexion et signal',{exact:true}).fill('11');
        await page.locator('[data-setting="oled_animations"]').uncheck();
        await selector.selectOption('system_details');await page.getByText(/Même moteur natif.*données d’exemple/).waitFor();
        await page.getByRole('button',{name:'Appliquer',exact:true}).click();
        await page.waitForFunction(async()=>{const r=await(await fetch('/extras/portable-os/api/settings')).json();return r.result.values.oled_style==='readable'&&r.result.values.oled_pages.find(p=>p.id==='system_details').seconds===7;});
        await page.getByText('Préférences validées et enregistrées.',{exact:true}).waitFor();
        await page.reload();await nav.getByRole('button',{name:'OLED et écrans',exact:true}).click();
        assert.equal(await page.locator('[data-setting="oled_style"]').inputValue(),'readable');
        assert.equal(await page.getByLabel('Durée Mémoire et durée',{exact:true}).inputValue(),'7');
        assert.equal(await page.getByLabel('Durée Connexion et signal',{exact:true}).inputValue(),'11');
        assert.equal(await page.locator('[data-setting="oled_animations"]').isChecked(),false);
        await selector.selectOption('menu-power-confirm');
        await page.getByText('Menu natif avec données d’exemple ; aucune action exécutée.',{exact:true}).waitFor();
        fs.mkdirSync('private',{recursive:true});await page.screenshot({path:'private/portable-os-rc121-readability.png',fullPage:true});
        assert.deepEqual(errors,[]);
        console.log('RC12.1 passed: RC12 import/preservation, 2 profiles, larger native preview, secondary pages/durations, animations off, persistence and confirmations.');
    }finally{
        if(page&&originalValues){
            const current=(await(await page.request.get(origin+'/extras/portable-os/api/settings')).json()).result;
            const restored=await page.request.post(origin+'/extras/portable-os/api/settings/apply',{headers:{'X-Pikvm-Share':'1'},data:{expected_revision:current.revision,confirmed:true,values:originalValues}});
            assert.equal(restored.status(),200,'Restore isolated fixture preferences');
        }
        await closeBrowser(browser);
    }
})().catch(error=>{console.error(error);process.exitCode=1;});
