import {el,button,card,hint,row,field,dialog,notify,table} from '../core/ui.js';
import {saveTheme,getTheme} from '../core/preferences.js';
import {unpackPixels} from './oled.js';

const pageNames={main:'Accueil / réseau',battery:'Batterie',system:'Système / USB / HDMI',network:'Réseau',usb:'USB et lecteurs',transfer:'Transfert USB (conditionnel)'};
const commandNames={'msd-dropdown':'Lecteur ISO',share:'Clé USB','atx-dropdown':'ATX','shortcuts-dropdown':'Raccourcis','macro-dropdown':'Macros','text-dropdown':'Texte','system-dropdown':'Vidéo & HID'};
const clone=value=>structuredClone(value);

export const settings={id:'settings',title:'Paramètres',subtitle:'Configuration partagée, diagnostics et sauvegarde des préférences.',icon:'settings',group:'SYSTÈME',
    mount(outlet,context){
        const {api,store,action}=context;
        let live=true,documentConfig,draft,selected=0,dirty=false,loading=false,frameTimer,frameController,diagnosticTimer,draftTimer,draftController,previewEpoch=0,draftBusy=false,draftQueued=false;
        const error=el('p',{role:'alert',class:'alert',hidden:true}),state=el('p',{role:'status'}),categories=el('nav',{'aria-label':'Catégories des paramètres',class:'settings-categories'});
        const content=el('div',{class:'settings-content'}),search=el('input',{type:'search',placeholder:'Rechercher un paramètre…','aria-label':'Rechercher dans les paramètres'});
        const apply=button('Appliquer',()=>action(()=>save()),'primary'),cancel=button('Annuler',()=>{draft=clone(documentConfig.values);dirty=false;render();},'quiet');
        const restore=button('Restaurer les valeurs par défaut',()=>action(async()=>{
            if(!await dialog({title:'Restaurer les préférences ?',message:'Les préférences applicatives seront rétablies. Les images, le réseau, les GPIO et les services d’alimentation ne sont pas modifiés.',confirm:'Restaurer',danger:true}))return;
            await api.system('settings/reset',{expected_revision:documentConfig.revision,confirmed:true});await load();
        }),'quiet');
        outlet.append(error,card('Centre de configuration',search,state,row(apply,cancel,restore)),el('div',{class:'settings-layout'},categories,content));
        function message(text){state.textContent=text;}
        function changed(){dirty=true;message('Modifications non enregistrées. Appliquer valide et enregistre ; Annuler rétablit les valeurs chargées.');apply.disabled=store.data.session!=='ready';cancel.disabled=false;
            if(selected===3){clearTimeout(draftTimer);draftTimer=setTimeout(refreshDraft,500);}}
        function stopPreview(){previewEpoch++;clearTimeout(frameTimer);clearTimeout(draftTimer);frameController?.abort();frameController=null;draftQueued=false;}
        const preview=el('canvas',{width:128,height:64,class:'settings-oled','aria-label':'Aperçu OLED natif synchronisé'}),previewStatus=hint('');
        const draftPreview=el('canvas',{width:128,height:64,class:'settings-oled','aria-label':'Aperçu OLED du brouillon'}),draftStatus=hint('');
        const previewPage=el('select',{'aria-label':'Page OLED à prévisualiser',onchange:()=>refreshDraft()},
            ...Object.entries({...pageNames,'menu-menu':'Menu principal','menu-power':'Menu alimentation','menu-wifi':'Menu Wi-Fi',
                'menu-network':'Menu secours','menu-iso-root':'Lecteur ISO','menu-iso':'Dossiers ISO','menu-iso-action':'Actions ISO','menu-iso-info':'Informations ISO',
                'menu-iso-connect-confirm':'Confirmation connexion','menu-iso-eject-confirm':'Confirmation éjection','menu-power-confirm':'Confirmation alimentation',
                'menu-network-confirm':'Confirmation hotspot','menu-working':'Opération en cours'}).map(([value,label])=>el('option',{value},label)));
        async function refreshDraft(){
            if(!live||selected!==3||search.value||document.hidden)return;
            // Cancelling fetch does not cancel the server's Pillow work. Drain
            // one request, discard stale results, then render only the latest draft.
            if(draftBusy){draftQueued=true;return;}
            draftBusy=true;draftQueued=false;
            const epoch=previewEpoch;draftController=new AbortController();
            try{
                const page=previewPage.value;
                const {result}=await api.request('/extras/portable-os/api/settings/preview',{method:'POST',body:{values:draft,page},signal:draftController.signal,timeout:4000});
                if(!live||epoch!==previewEpoch)return;
                draftPreview.getContext('2d').putImageData(new ImageData(unpackPixels(result.pixels),128,64),0,0);draftStatus.textContent=result.message;
            }catch(e){if(live&&epoch===previewEpoch)draftStatus.textContent='Brouillon non prévisualisable : '+e.message;}
            finally{draftBusy=false;draftController=null;if(draftQueued){draftQueued=false;queueMicrotask(refreshDraft);}}
        }
        async function refreshPreview(){
            if(!live||selected!==3||search.value||document.hidden)return;
            const epoch=previewEpoch;
            frameController=new AbortController();
            try{
                const {result}=await api.request('/extras/portable-os/api/oled',{signal:frameController.signal,timeout:2000});
                if(!live||selected!==3||epoch!==previewEpoch)return;
                preview.getContext('2d').putImageData(new ImageData(unpackPixels(result.pixels),128,64),0,0);
                previewStatus.textContent=(result.physical==='connected'?'OLED physique connecté':'Mode virtuel')+' · framebuffer réellement publié. Les brouillons ne sont pas appliqués au matériel.';
            }catch(e){if(live&&selected===3)previewStatus.textContent='Aperçu indisponible : '+e.message;}
            finally{if(epoch===previewEpoch){frameController=null;if(live&&selected===3)frameTimer=setTimeout(refreshPreview,1000);}}
        }
        function reorder(list,index,delta){const to=index+delta;if(to<0||to>=list.length)return;[list[index],list[to]]=[list[to],list[index]];changed();render();}
        function oledPages(){
            const host=el('div',{'aria-label':'Organisation des pages OLED'});
            draft.oled_pages.forEach((page,index)=>{
                const enabled=el('input',{type:'checkbox',checked:page.enabled,'aria-label':'Activer '+pageNames[page.id],onchange:e=>{page.enabled=e.target.checked;changed();}});
                const duration=el('input',{type:'number',min:2,max:300,value:page.seconds,'aria-label':'Durée '+pageNames[page.id],oninput:e=>{page.seconds=Number(e.target.value);changed();}});
                const item=el('div',{class:'settings-page',draggable:true,'data-page':page.id,ondragstart:e=>e.dataTransfer.setData('text/plain',String(index)),ondragover:e=>e.preventDefault(),ondrop:e=>{
                    e.preventDefault();const from=Number(e.dataTransfer.getData('text/plain'));
                    if(Number.isInteger(from)&&from>=0&&from<draft.oled_pages.length){const [moved]=draft.oled_pages.splice(from,1);draft.oled_pages.splice(index,0,moved);changed();render();}
                }},field(pageNames[page.id],enabled),field('Durée (secondes)',duration),row(
                    button('Monter',()=>reorder(draft.oled_pages,index,-1),'quiet',{'aria-label':'Monter '+pageNames[page.id],disabled:index===0}),
                    button('Descendre',()=>reorder(draft.oled_pages,index,1),'quiet',{'aria-label':'Descendre '+pageNames[page.id],disabled:index===draft.oled_pages.length-1})));
                host.append(item);
            });
            return card('Pages existantes · ordre et durées',hint('Glisser-déposer ou Monter / Descendre. Les alertes critiques restent visibles même si une page informative est désactivée.'),host);
        }
        function kvmCommands(){
            return card('Commandes KVM',hint('La capture, sa libération et le plein écran restent toujours accessibles. Aucun bouton ne connecte un lecteur à l’ouverture.'),
                ...draft.kvm_order.map((id,index)=>el('div',{class:'settings-page'},field(commandNames[id],el('input',{type:'checkbox',checked:!draft.kvm_hidden.includes(id),'aria-label':'Afficher '+commandNames[id],onchange:e=>{
                    draft.kvm_hidden=draft.kvm_hidden.filter(n=>n!==id);if(!e.target.checked)draft.kvm_hidden.push(id);changed();
                }})),row(button('Monter',()=>reorder(draft.kvm_order,index,-1),'quiet',{'aria-label':'Monter '+commandNames[id],disabled:index===0}),
                    button('Descendre',()=>reorder(draft.kvm_order,index,1),'quiet',{'aria-label':'Descendre '+commandNames[id],disabled:index===draft.kvm_order.length-1})))));
        }
        const idle=el('pre',{class:'logs','aria-label':'Diagnostic d’inactivité'});
        const idleText=data=>draft.advanced_diagnostics?JSON.stringify(data,null,2):
            `État : ${data.state}\nDernière activité : ${data.source}\nÉcoulé : ${data.elapsed} s · Restant : ${data.remaining} s\nAvertissement : ${data.warning?'Oui':'Non'}\nInhibiteurs : ${(data.inhibitors||[]).join(' ; ')||'Aucun dans ce scénario'}\nArrêt réel : toujours refusé\n${data.reason}`;
        async function refreshIdle(){
            clearTimeout(diagnosticTimer);
            if(!live||![1,8,9].includes(selected)||document.hidden)return;
            try{const data=await api.system('idle');if(live)idle.textContent=idleText(data);}catch(e){if(live)idle.textContent='Diagnostic indisponible : '+e.message;}
            if(live&&[1,8,9].includes(selected))diagnosticTimer=setTimeout(refreshIdle,5000);
        }
        function download(data,name){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)+'\n'],{type:'application/json'}));const link=el('a',{href:url,download:name});link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
        function render(){
            if(!documentConfig)return;
            stopPreview();clearTimeout(diagnosticTimer);content.replaceChildren();categories.replaceChildren();
            apply.disabled=!dirty||loading||store.data.session!=='ready';cancel.disabled=!dirty||loading;restore.disabled=loading||store.data.session!=='ready';
            documentConfig.categories.forEach((name,index)=>categories.append(button(name,()=>{selected=index;search.value='';render();},'quiet',{'aria-current':selected===index?'page':'false'})));
            const q=search.value.trim().toLocaleLowerCase('fr');
            const selectedFields=Object.entries(documentConfig.fields).filter(([key,spec])=>q?`${spec.label} ${spec.description} ${documentConfig.categories[spec.category]}`.toLocaleLowerCase('fr').includes(q):spec.category===selected);
            if(!q)content.append(el('h2',{},documentConfig.categories[selected]));
            for(const [key,spec]of selectedFields){
                let input;
                if(spec.type==='select'){
                    input=el('select',{'data-setting':key},...Object.entries(spec.choices).map(([value,text])=>el('option',{value},text)));input.value=draft[key];
                }else input=el('input',{'data-setting':key,type:spec.type==='boolean'?'checkbox':spec.type==='number'?'number':'text',
                    ...(spec.type==='boolean'?{checked:draft[key]}:{value:draft[key]}),min:spec.minimum,max:spec.maximum});
                input.setAttribute('aria-label',spec.label);
                input.addEventListener(spec.type==='text'||spec.type==='number'?'input':'change',()=>{draft[key]=spec.type==='boolean'?input.checked:spec.type==='number'?Number(input.value):input.value;changed();});
                content.append(card(spec.label,field(spec.label,input),hint(spec.description),hint(`Valeur enregistrée : ${format(documentConfig.values[key],spec)} · Défaut : ${format(spec.default,spec)} · ${spec.application}${spec.sensitive?' · Sensible : confirmation requise':''}`)));
            }
            if(q){if(!selectedFields.length)content.append(hint('Aucun paramètre correspondant.'));return;}
            const limits=documentConfig.limitations;
            if(selected===1){content.append(card('Diagnostic en direct · aucune extinction réelle',idle,button('Simuler une échéance sans arrêter',()=>action(async()=>{
                const evidence=Object.fromEntries(['drive0','drive1','transfer','share','storage','install','ssh'].map(k=>[k,false]));
                const result=await api.system('idle/simulate',{elapsed:draft.idle_shutdown_seconds,evidence});
                idle.textContent='SIMULATION — observations synthétiques toutes libres\n'+idleText(result);
                clearTimeout(diagnosticTimer);
            }),'quiet'),hint(limits.power),hint(limits.presence)));refreshIdle();}
            if(selected===2)content.append(card('Mesures et limites',hint(limits.battery),el('a',{href:'#power',class:'button'},'Batterie et alimentation')));
            if(selected===3){content.append(oledPages(),card('Aperçu du brouillon · données d’exemple',field('Page de l’aperçu',previewPage),draftPreview,draftStatus),card('Miroir natif en direct',preview,previewStatus,hint(limits.oled)));refreshPreview();refreshDraft();}
            if(selected===4)content.append(card('Protections matérielles conservées',hint(limits.button),hint('GPIO18 : lecture optimisée RC8 inchangée. GPIO17 n’est jamais configurable.')));
            if(selected===5)content.append(kvmCommands(),hint(limits.kvm),el('a',{href:'#kvm',class:'button'},'Ouvrir la console KVM'));
            if(selected===6)content.append(card('Lecteurs et intégrité',hint(limits.storage),el('a',{href:'#images',class:'button'},'Images & Drive 0'),el('a',{href:'#share',class:'button'},'PIKVM-SHARE'),el('a',{href:'#tools',class:'button'},'Diagnostic USB')));
            if(selected===7)content.append(card('Connexion et récupération',hint('Les préférences ci-dessus ne modifient aucune interface réseau. Les changements Wi-Fi/hotspot conservent leurs confirmations dans la page Réseau.'),el('a',{href:'#network',class:'button'},'Ouvrir Réseau')));
            if(selected===8){const sys=store.get('system');content.append(card('Ressources observées',el('pre',{class:'logs'},JSON.stringify(sys?.resources||{message:'Diagnostic de ressources indisponible sur cette API.'},null,2)),hint('Charge système : différente du pourcentage CPU. Aucune donnée manquante n’est remplacée par zéro.'),el('a',{href:'#tools',class:'button'},'Services et journaux')));}
            if(selected===9){const output=el('pre',{class:'logs'});content.append(card('Version et maintenance',hint('Version : '+documentConfig.release),hint('Dernière installation : '+(documentConfig.installed_at?new Date(documentConfig.installed_at*1000).toLocaleString('fr-FR'):'Date indisponible')),hint(documentConfig.persistence),hint(limits.security),row(
                button('Vérifier l’intégrité applicative',()=>action(async()=>{const result=await api.system('integrity');if(live)output.textContent=JSON.stringify(result,null,2);}), 'quiet'),
                button('Exporter un rapport sans secrets',()=>action(async()=>download(await api.system('report'),'pikvm-portable-report.json')),'quiet')),output));}
            if(selected===10){
                const file=el('input',{type:'file',accept:'.json,application/json','aria-label':'Importer une configuration'});
                file.onchange=()=>action(async()=>{
                    const source=file.files?.[0];if(!source)return;
                    if(source.size>8192)throw Error('Configuration trop volumineuse (8 Kio maximum).');
                    let config;try{config=JSON.parse(await source.text());}catch{throw Error('Fichier JSON invalide.');}
                    if(!await dialog({title:'Importer les préférences ?',message:'Le serveur validera format, version, champs et bornes avant toute écriture. Aucun shell ou secret ne peut être importé.',confirm:'Importer',danger:true}))return;
                    await api.system('settings/import',{expected_revision:documentConfig.revision,confirmed:true,config});await load();
                });
                content.append(card('Export et import',button('Exporter les préférences',()=>action(async()=>download(await api.system('settings/export'),'pikvm-portable-settings.json')),'quiet'),field('Importer une configuration validée',file),
                    hint('L’import remplace les préférences après confirmation. Les ISO et conteneurs de transfert sont exclus. Le rollback applicatif reste une opération de maintenance documentée.')),
                    card('Historique limité',table(['Date','Champs modifiés'],documentConfig.history.map(item=>[new Date(item.at*1000).toLocaleString('fr-FR'),item.keys.join(', ')]))));
            }
            if(selected===11)content.append(card('Limites de sécurité',hint(limits.security),hint('Tous les réglages exposés sont appliqués à chaud. Aucun redémarrage de service d’alimentation n’est proposé. Les réglages matériels non validés sont indisponibles.')));
        }
        function format(value,spec){return typeof value==='boolean'?(value?'Activé':'Désactivé'):spec.choices?.[value]??String(value||'Racine /');}
        async function save(){
            if(!dirty||loading)return;
            const sensitive=Object.entries(documentConfig.fields).some(([key,spec])=>spec.sensitive&&draft[key]!==documentConfig.values[key]);
            if(sensitive&&!await dialog({title:'Appliquer les réglages sensibles ?',message:'Les inhibiteurs stockage et états inconnus restent obligatoires. Aucun arrêt réel ni changement GPIO ne sera activé.',confirm:'Appliquer',danger:true}))return;
            loading=true;apply.disabled=true;
            try{await api.system('settings/apply',{expected_revision:documentConfig.revision,confirmed:sensitive,values:draft});await load();notify('Préférences validées et enregistrées.');}
            finally{loading=false;if(live)render();}
        }
        async function load(){
            try{
                const result=await api.system('settings');if(!live)return;
                documentConfig=result;draft=clone(result.values);dirty=false;
                if(result.revision===0&&getTheme()==='light'){draft.theme='light';dirty=true;}
                store.resource('settings',result);
                if(result.revision>0){saveTheme(result.values.theme);document.documentElement.dataset.theme=result.values.theme;}
                error.hidden=result.healthy;error.textContent=result.error||'';message('Révision '+result.revision+' · valeurs chargées. Aucun service à redémarrer.');render();
            }catch(e){if(live){error.hidden=false;error.textContent='Configuration indisponible : '+e.message;apply.disabled=cancel.disabled=restore.disabled=true;}}
        }
        search.oninput=render;
        const visibility=()=>{if(document.hidden){stopPreview();clearTimeout(diagnosticTimer);}else if(documentConfig)render();};
        document.addEventListener('visibilitychange',visibility);
        const beforeUnload=event=>{if(dirty){event.preventDefault();event.returnValue='';}};window.addEventListener('beforeunload',beforeUnload);
        const unsub=store.subscribe(data=>{if(data.session!=='ready'){apply.disabled=restore.disabled=true;stopPreview();clearTimeout(diagnosticTimer);}});
        load();return()=>{live=false;stopPreview();clearTimeout(diagnosticTimer);unsub();document.removeEventListener('visibilitychange',visibility);window.removeEventListener('beforeunload',beforeUnload);};
    }};
