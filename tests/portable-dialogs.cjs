// Native DOM regression and isolated ISO move API mocks. No disk images touched.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');

(async()=>{
    const url=process.env.PORTABLE_TEST_URL||'http://127.0.0.1:8765/extras/portable-os/';
    if(!['localhost','127.0.0.1'].includes(new URL(url).hostname))throw Error('Local simulated fixture required');
    const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});
    try{
        const page=await browser.newPage();const errors=[];
        page.on('pageerror',error=>errors.push(error.message));
        await page.goto(url);
        await page.getByRole('heading',{name:'Vue d’ensemble',exact:true}).waitFor();
        const nativeError=await page.evaluate(()=>{
            'use strict';
            try{document.createElement('select').type='select';return null;}
            catch(error){return {name:error.name,message:error.message};}
        });
        assert.equal(nativeError.name,'TypeError');
        assert.match(nativeError.message,/type.*(getter|read.?only)|Cannot set property type/i);
        async function open(fields){
            await page.evaluate(fields=>{
                window.formResult=undefined;
                import('/extras/portable-os/core/ui.js').then(({dialog})=>
                    dialog({title:'Formulaire de test',fields}).then(result=>window.formResult=result));
            },fields);
            await page.getByRole('dialog',{name:'Formulaire de test'}).waitFor();
        }
        await open([{name:'folder',type:'select',label:'Destination',options:['','Outils','Outils/Linux images'],value:'Outils/Linux images'},
            {name:'name',label:'Nom',value:'Image ISO avec espaces.iso'},
            {name:'password',type:'password',label:'Mot de passe de test',value:'example-only'},
            {name:'enabled',type:'checkbox',label:'Activé',required:false,value:true}]);
        const modal=page.getByRole('dialog');
        assert.equal(await modal.getByLabel('Destination').getAttribute('type'),null);
        assert.equal(await modal.getByLabel('Destination').inputValue(),'Outils/Linux images');
        assert.equal(await modal.getByLabel('Mot de passe de test').getAttribute('type'),'password');
        assert.equal(await modal.getByLabel('Mot de passe de test').getAttribute('autocomplete'),'new-password');
        assert.equal(await modal.getByLabel('Nom').getAttribute('type'),'text');
        await modal.getByLabel('Activé').uncheck();
        await modal.getByLabel('Nom').fill('');await modal.getByRole('button',{name:'Confirmer',exact:true}).click();
        assert.equal(await modal.isVisible(),true,'Required text validation must still block submission');
        await modal.getByLabel('Nom').fill('Image ISO avec espaces.iso');
        await modal.getByRole('button',{name:'Confirmer',exact:true}).click();
        await page.waitForFunction(()=>window.formResult!==undefined);
        assert.deepEqual(await page.evaluate(()=>window.formResult),{folder:'Outils/Linux images',name:'Image ISO avec espaces.iso',password:'example-only',enabled:false});
        await open([{name:'folder',type:'select',label:'Destination',options:['Outils',''],value:'',required:false},
            {name:'enabled',type:'checkbox',label:'Activé',required:false,value:false}]);
        assert.equal(await modal.getByLabel('Destination').inputValue(),'');
        await modal.getByLabel('Activé').check();await modal.getByRole('button',{name:'Confirmer',exact:true}).click();
        await page.waitForFunction(()=>window.formResult!==undefined);
        assert.deepEqual(await page.evaluate(()=>window.formResult),{folder:'',enabled:true});
        await open([{name:'folder',type:'select',label:'Destination',options:['Premier','Second']}]);
        assert.equal(await modal.getByLabel('Destination').inputValue(),'Premier');
        await modal.getByRole('button',{name:'Annuler',exact:true}).click();
        await page.waitForFunction(()=>window.formResult===null);

        const name='Ubuntu Desktop avec espaces.iso',nested='Outils et secours/Linux images';
        let image=name,failMove=false,failList=false;const calls=[];
        await page.route('**/api/msd',route=>route.fulfill({json:{ok:true,result:{drive:{connected:false,image:null},
            storage:{images:{[image]:{size:123456}},parts:{'':{size:999999,free:888888}}}}}}));
        await page.route('**/extras/image-manager/api/image-manager/folders',route=>route.fulfill(failList?
            {status:503,json:{ok:false,error:'Liste des dossiers indisponible (simulation).'}}:
            {json:{ok:true,result:{folders:['Outils et secours',nested,'Autre dossier']}}}));
        await page.route('**/extras/image-manager/api/image-manager/folders/action',route=>{
            const data=route.request().postDataJSON();calls.push(data);
            assert.equal(route.request().method(),'POST');assert.equal(route.request().headers()['x-pikvm-portable'],'1');
            assert.equal(data.action,'move_file');assert.equal(data.source,image);
            if(failMove)return route.fulfill({status:409,json:{ok:false,error:'Déplacement refusé : image utilisée (simulation).'}});
            image=(data.folder?data.folder+'/':'')+name;
            return route.fulfill({json:{ok:true,result:{path:image}}});
        });
        await page.locator('[data-route="images"]').click();
        const imageRow=()=>page.getByRole('row').filter({has:page.getByText(name,{exact:true})});
        await imageRow().waitFor();
        await imageRow().getByRole('button',{name:'Déplacer',exact:true}).click();
        await modal.waitFor();assert.equal(await modal.getByLabel('Dossier de destination').inputValue(),'');
        assert.equal(await modal.getByRole('option',{name:'/',exact:true}).getAttribute('value'),'');
        await modal.getByLabel('Dossier de destination').selectOption(nested);
        await modal.getByRole('button',{name:'Confirmer',exact:true}).click();
        await imageRow().waitFor({state:'detached'});
        assert.deepEqual(calls[0],{action:'move_file',source:name,folder:nested});
        await page.getByRole('button',{name:'Outils et secours',exact:true}).click();
        await page.getByRole('button',{name:'Linux images',exact:true}).click();await imageRow().waitFor();
        await imageRow().getByRole('button',{name:'Déplacer',exact:true}).click();
        await modal.getByLabel('Dossier de destination').selectOption('');
        await modal.getByRole('button',{name:'Confirmer',exact:true}).click();
        await imageRow().waitFor({state:'detached'});
        assert.deepEqual(calls[1],{action:'move_file',source:nested+'/'+name,folder:''});
        await page.getByRole('navigation',{name:'Dossier actuel'}).getByRole('button',{name:'/',exact:true}).click();
        await imageRow().waitFor();assert.equal(image,name);
        failMove=true;
        await imageRow().getByRole('button',{name:'Déplacer',exact:true}).click();
        await modal.getByLabel('Dossier de destination').selectOption('Autre dossier');
        await modal.getByRole('button',{name:'Confirmer',exact:true}).click();
        await page.getByText('Déplacement refusé : image utilisée (simulation).',{exact:true}).waitFor();
        assert.equal(image,name);assert.deepEqual(calls[2],{action:'move_file',source:name,folder:'Autre dossier'});
        await imageRow().getByRole('button',{name:'Déplacer',exact:true}).click();
        await modal.getByRole('button',{name:'Annuler',exact:true}).click();
        assert.equal(calls.length,3);
        failList=true;
        await imageRow().getByRole('button',{name:'Déplacer',exact:true}).click();
        await page.getByText('Liste des dossiers indisponible (simulation).',{exact:true}).waitFor();
        assert.equal(await page.getByRole('dialog').count(),0);assert.equal(calls.length,3);
        assert.deepEqual(errors,[]);
        process.stdout.write('Dialog regression passed: native select getter, initial values, text/password/checkbox, ISO move to nested folder and root, API errors and cancellation.\n');
    }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
