const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
const {closeBrowser}=require('./browser-cleanup.cjs');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1040}});page.setDefaultTimeout(12000);
  await page.goto('http://127.0.0.1:8765/extras/portable-os/#settings');
  await page.getByRole('button',{name:'Utilisateurs et permissions',exact:true}).click();
  const dialog=page.getByRole('dialog');
  if(await page.getByRole('button',{name:'Préparer la sécurité Portable',exact:true}).count()){
   await page.getByRole('button',{name:'Préparer la sécurité Portable',exact:true}).click();
   await dialog.locator('[name=name]').fill('owner');await dialog.locator('[name=display]').fill('Owner');await dialog.locator('[name=password]').fill('Synthetic-Browser-2026!');await dialog.getByRole('button',{name:'Créer',exact:true}).click();
  }
  if(!await page.getByRole('button',{name:'Modifier spare',exact:true}).count()){
   await page.getByRole('button',{name:'Ajouter un utilisateur',exact:true}).click();
   await dialog.locator('[name=name]').fill('spare');await dialog.locator('[name=display]').fill('Spare');await dialog.locator('[name=password]').fill('Synthetic-Spare-2026!');await dialog.locator('[name=role]').selectOption('administrator');await dialog.getByRole('button',{name:'Créer',exact:true}).click();
   await page.getByRole('button',{name:'Modifier spare',exact:true}).waitFor();
  }
  await page.getByRole('button',{name:'Permissions owner',exact:true}).click();
  fs.mkdirSync('docs/images/rc132',{recursive:true});
  if(process.env.RC132_CAPTURE_BEFORE==='1'){
   await page.screenshot({path:'docs/images/rc132/permissions-before-desktop.png'});
   await page.setViewportSize({width:390,height:844});await page.screenshot({path:'docs/images/rc132/permissions-before-mobile.png'});return;
  }
  const modal=page.getByRole('dialog',{name:'Permissions de owner'});
  assert.ok((await modal.boundingBox()).width>=900);
  assert.ok((await modal.boundingBox()).height<=1040*.9+2);
  await page.screenshot({path:'docs/images/rc132/permissions-after-desktop.png'});
  await modal.getByLabel('Rechercher une permission').fill('iso.mount');
  await modal.getByLabel('iso.mount',{exact:true}).selectOption('deny');
  await modal.getByText('Modifications non enregistrées',{exact:true}).waitFor();
  await modal.getByLabel('iso.mount',{exact:true}).locator('..').getByText('Refusé',{exact:true}).waitFor();
  await modal.getByRole('button',{name:'Annuler',exact:true}).click();
  await page.getByRole('dialog').getByRole('button',{name:'Continuer la modification',exact:true}).click();
  let oldButton=await page.getByRole('button',{name:'Permissions owner',exact:true}).elementHandle();
  await modal.getByRole('button',{name:'Enregistrer les permissions',exact:true}).click();
  await oldButton.waitForElementState('hidden');
  await page.getByRole('button',{name:'Permissions owner',exact:true}).click();
  assert.equal(await modal.getByLabel('iso.mount',{exact:true}).inputValue(),'deny');
  await modal.getByRole('button',{name:'Tout refuser',exact:true}).click();
  await page.getByRole('dialog').last().getByRole('button',{name:'Annuler',exact:true}).click();
  assert.equal(await modal.getByLabel('iso.mount',{exact:true}).inputValue(),'deny');
  await modal.getByRole('button',{name:'Réinitialiser à l’héritage',exact:true}).click();
  await page.getByRole('dialog').last().getByRole('button',{name:'Confirmer',exact:true}).click();
  assert.equal(await modal.getByLabel('iso.mount',{exact:true}).inputValue(),'inherit');
  oldButton=await page.getByRole('button',{name:'Permissions owner',exact:true}).elementHandle();
  await modal.getByRole('button',{name:'Enregistrer les permissions',exact:true}).click();
  await oldButton.waitForElementState('hidden');
  await page.getByRole('button',{name:'Permissions owner',exact:true}).click();
  await page.setViewportSize({width:390,height:844});
  assert.ok((await modal.boundingBox()).width<=390);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await modal.getByLabel('Rechercher une permission').fill('ssh');
  await modal.getByLabel('ssh.manage',{exact:true}).selectOption('inherit');
  await page.screenshot({path:'docs/images/rc132/permissions-after-mobile.png'});
  await modal.getByRole('button',{name:'Annuler',exact:true}).click();
  const state=(await(await page.request.get('http://127.0.0.1:8765/extras/portable-os/api/security/users')).json()).result;
  await page.route('**/api/security/session',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,result:{user:'owner',native:false,permissions:Object.keys(state.permissions)}})}));
  await page.setViewportSize({width:1440,height:1040});await page.reload();await page.getByRole('button',{name:'Utilisateurs et permissions',exact:true}).click();await page.getByRole('button',{name:'Permissions owner',exact:true}).click();
  await modal.getByLabel('Rechercher une permission').fill('iso.mount');await modal.getByLabel('iso.mount',{exact:true}).selectOption('deny');
  await modal.getByRole('button',{name:'Enregistrer les permissions',exact:true}).click();
  await page.getByRole('dialog',{name:'Confirmer votre identité'}).getByRole('button',{name:'Annuler',exact:true}).click();
  assert.equal(await modal.getByLabel('iso.mount',{exact:true}).inputValue(),'deny');
  let sent;
  await page.route('**/api/security/mutate',route=>{sent=route.request().postDataJSON();return route.fulfill({status:403,contentType:'application/json',body:JSON.stringify({ok:false,error:'Synthetic denial'})});});
  await modal.getByRole('button',{name:'Enregistrer les permissions',exact:true}).click();
  const reauth=page.getByRole('dialog',{name:'Confirmer votre identité'});await reauth.locator('[name=password]').fill('');await reauth.getByRole('button',{name:'Confirmer',exact:true}).click();
  await modal.getByRole('alert').waitFor();assert.equal(sent.admin_password,'');assert.equal(await modal.getByLabel('iso.mount',{exact:true}).inputValue(),'deny');
  await modal.getByRole('button',{name:'Annuler',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'Abandonner les modifications',exact:true}).click();
  console.log('RC13.2 permissions: desktop/mobile, search, effective rights, dirty guard, save and bulk confirmation passed');
 }finally{await closeBrowser(browser);}
})().catch(error=>{console.error(error);process.exitCode=1;});
