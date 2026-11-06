const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
const {closeBrowser}=require('./browser-cleanup.cjs');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});
 try{
  const root='http://127.0.0.1:8766',page=await browser.newPage({viewport:{width:1440,height:1040},colorScheme:'dark'});
  // Isolate login/ACL integration from hardware dashboards, tested separately.
  await page.route(root+'/extras/portable-os/',route=>route.fulfill({contentType:'text/html',body:'<p>Authenticated fixture landing</p>'}));
  fs.mkdirSync('docs/images/rc132',{recursive:true});
  for(const role of ['administrator','operator','user','readonly','maintenance','empty']){
   await page.goto(root+'/login/');await page.getByLabel('Identifiant Portable',{exact:true}).fill(role);
   await page.getByLabel('Mot de passe',{exact:true}).fill(role==='empty'?'':'Synthetic-Portal-2026!');
   if(role==='administrator')await page.screenshot({path:'docs/images/rc132/portal-desktop.png'});
   await page.getByRole('button',{name:'Se connecter',exact:true}).click();await page.waitForURL(root+'/extras/portable-os/');
   const identity=(await(await page.request.get(root+'/api/auth/check')).json()).result;assert.equal(identity.user,role);assert.equal(identity.native,false);
   for(const path of ['/legacy/','/extras/webterm/ws','/redfish/v1','/vnc'])assert.equal((await page.request.get(root+path)).status(),403);
   const key=await page.request.post(root+'/api/hid/events/send_key?key=KeyA&state=true',{headers:{Origin:root},data:{}});assert.equal(key.status(),['administrator','operator'].includes(role)?200:403);
   const logout=await page.request.post(root+'/api/auth/logout',{headers:{Origin:root},data:{}});assert.equal(logout.status(),200);assert.equal((await page.request.get(root+'/api/auth/check')).status(),401);
  }
  await page.goto(root+'/login/');await page.getByLabel('Identifiant Portable',{exact:true}).fill('admin');await page.getByLabel('Mot de passe',{exact:true}).fill('Synthetic-Portal-2026!');await page.getByRole('button',{name:'Se connecter',exact:true}).click();await page.getByRole('alert').getByText(/Portable incorrect/).waitFor();
  await page.setViewportSize({width:390,height:844});await page.emulateMedia({colorScheme:'light'});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:'docs/images/rc132/portal-mobile.png'});
  // The same HTML on an origin without the gateway probe must never submit
  // Portable credentials to a native KVMD login endpoint.
  let wrongEntryPosts=0;
  page.on('request',request=>{if(request.method()==='POST'&&request.url()===root+'/api/auth/login')wrongEntryPosts++;});
  await page.route(root+'/api/portable-entry',route=>route.fulfill({status:404,body:'not a Portable gateway'}));
  await page.goto(root+'/login/');await page.getByRole('alert').getByText(/aucun mot de passe n’a été envoyé/).waitFor();
  assert.equal(await page.getByRole('button',{name:'Se connecter',exact:true}).isDisabled(),true);
  await page.getByLabel('Identifiant Portable',{exact:true}).fill('synthetic');await page.getByLabel('Mot de passe',{exact:true}).fill('Synthetic-only');
  await page.locator('form').evaluate(form=>form.requestSubmit());await page.getByRole('alert').getByText(/Entrée Portable non vérifiée/).waitFor();assert.equal(wrongEntryPosts,0);
  console.log('RC13.2 real login portal passed: five roles, explicit empty secret, native identity denial, direct ACLs and logout; synthetic hardware upstream only');
 }finally{await closeBrowser(browser);}
})().catch(error=>{console.error(error);process.exitCode=1;});
