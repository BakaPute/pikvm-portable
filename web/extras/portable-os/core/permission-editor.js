import {el,button,hint} from './ui.js';

const groups=[['kvm.','Console KVM'],['iso.','Images ISO'],['share.','PIKVM-SHARE'],['atx.','Alimentation'],['oled.','OLED et bouton'],['system.','Système et réseau'],['accounts.|roles.|permissions.|audit.|sessions.','Utilisateurs et sécurité'],['ssh.','SSH']];
const notes={
 kvm:'Contrôles KVMD natifs. La console interactive exige clavier, macros et souris ensemble ; sinon vidéo seule sans WebSocket HID.',
 iso:'Les API natives et leurs protections restent obligatoires. Aucun montage, effacement ou déplacement lors de la modification de droits.',
 share:'Exclusivité Web/USB et éjection propre du PC conservées. Donner un droit ne connecte pas le lecteur.',
 atx:'Les actions sensibles exigent leur confirmation et une configuration matérielle reconnue hors GPIO17/18.',
 oled:'Consultation du framebuffer commun. Les gestes capables de piloter des menus sensibles exigent les droits correspondants.',
 system:'Aucun exécuteur root de mise à jour ni arrêt direct implicite. Les voies non prises en charge restent refusées.',
 accounts:'Pas de délégation au-delà des droits détenus, pas de modification d’un compte supérieur ; dernier administrateur protégé.',
 ssh:'Préparation des accès et clés publiques uniquement. Linux, UID, commandes forcées et approbation root restent séparés du rôle Web.'
};
const descriptions={
 'kvm.video':'Voir le flux vidéo, sans accorder de contrôle clavier ou souris.',
 'kvm.keyboard':'Envoyer des touches. Le protocole exige aussi le droit macros.',
 'kvm.mouse':'Déplacer la souris et utiliser ses boutons via les voies autorisées.',
 'kvm.macros':'Envoyer des séquences de touches ; indissociable du droit clavier pour le flux natif.',
 'kvm.text':'Envoyer du texte au PC ; les droits clavier et macros restent requis.',
 'kvm.hid':'Modifier les réglages HID pris en charge par le moteur natif.',
 'iso.view':'Consulter la bibliothèque d’images ISO et ses dossiers.',
 'iso.upload':'Ajouter une ISO ; les contrôles de nom, espace et stockage restent actifs.',
 'iso.mkdir':'Créer un dossier dans la bibliothèque ISO.',
 'iso.rename':'Renommer une image ou un dossier autorisé.',
 'iso.move':'Déplacer une image entre dossiers, y compris la racine.',
 'iso.delete':'Supprimer une ISO autorisée, sous les confirmations et verrouillages existants.',
 'iso.mount':'Choisir et connecter une ISO au lecteur natif, en CD/DVD ou Flash.',
 'iso.eject':'Déconnecter explicitement l’image du lecteur ISO.',
 'iso.info':'Consulter les informations et gérer les préférences/favoris ISO autorisés.',
 'share.status':'Lire l’état réel du Drive 1 ; aucun attachement automatique.',
 'share.web':'Utiliser les opérations de fichiers Web lorsque le mode Web exclusif est acquis.',
 'share.start':'Démarrer la procédure de transfert autorisée ; protections des lecteurs conservées.',
 'share.stop':'Terminer le transfert selon son cycle normal, sans reset implicite.',
 'share.import':'Importer les ISO via le contrôleur de stockage et ses vérifications.',
 'share.usb':'Présenter SHARE au PC ; le montage Web simultané reste interdit.',
 'atx.view':'Consulter les indicateurs ATX du PC relié.',
 'atx.on':'Demander le démarrage du PC avec confirmation indépendante.',
 'atx.off':'Demander l’arrêt normal du PC ; aucune coupure du PiKVM.',
 'atx.restart':'Demander le redémarrage ATX du PC sous confirmation.',
 'atx.sensitive':'Autoriser les actions ATX forcées, avec confirmation et garde matérielle.',
 'oled.view':'Lire le framebuffer partagé ; les écrans QR sensibles exigent aussi le droit réseau.',
 'oled.pages':'Modifier les pages, leur visibilité et leur présentation.',
 'oled.durations':'Modifier les durées de rotation et d’affichage autorisées.',
 'oled.gestures':'Modifier les gestes logiques ; aucune reconfiguration électrique de GPIO18.',
 'oled.notifications':'Régler les notifications et priorités d’affichage autorisées.',
 'system.diagnostics':'Consulter les diagnostics non sensibles disponibles.',
 'system.logs':'Lire les journaux autorisés et filtrés, sans accès arbitraire aux fichiers.',
 'system.settings':'Modifier les préférences générales prises en charge.',
 'system.network':'Consulter ou modifier les réglages réseau autorisés, dont Wi-Fi.',
 'system.update':'Droit réservé à la préparation ; aucun exécuteur de mise à jour root disponible.',
 'system.export':'Exporter les préférences ; les identités et secrets sont exclus.',
 'system.restore':'Importer/réinitialiser les préférences selon leurs confirmations ; aucune restauration root arbitraire.',
 'system.shutdown':'Permission requise pour les menus d’alimentation ; pas d’arrêt direct exposé.',
 'accounts.view':'Consulter les comptes Web et les métadonnées d’identités liées.',
 'accounts.create':'Créer un compte Portable distinct de KVMD et Linux.',
 'accounts.edit':'Modifier un compte ou son mot de passe dans la limite des droits détenus.',
 'accounts.delete':'Supprimer un compte Web ; ni compte Linux ni donnée ISO effacés.',
 'roles.manage':'Dupliquer et modifier les rôles personnalisés ; rôles prédéfinis protégés.',
 'permissions.manage':'Modifier les exceptions de permissions et la politique autorisée, sans élévation de privilèges.',
 'audit.view':'Lire les traces disponibles d’activité et de refus.',
 'sessions.revoke':'Révoquer les sessions du compte ciblé sans dépasser son niveau d’autorité.',
 'ssh.manage':'Consulter/préparer les accès et gérer les clés publiques. Le provisionnement Linux et toute élévation restent distincts.'
};
function confirmChoice(title,message,discard=false){
 return new Promise(resolve=>{
  const finish=value=>{modal.close();modal.remove();resolve(value);};
  const modal=el('dialog',{'aria-label':title},el('h2',{},title),hint(message),el('div',{class:'dialog-actions'},
   button(discard?'Continuer la modification':'Annuler',()=>finish(false),'quiet'),
   button(discard?'Abandonner les modifications':'Confirmer',()=>finish(true),'primary')));
  modal.oncancel=event=>{event.preventDefault();finish(false);};document.body.append(modal);modal.showModal();
 });
}

export function editPermissions({user,roles,permissions,actor,onSave}){
 const originalHash=location.hash,previous=document.activeElement,selects={},items=[],sections=[];
 const canGrant=key=>actor.native||actor.permissions.includes(key);
 const readonly=!actor.native&&(!actor.permissions.includes('accounts.edit')||!actor.permissions.includes('permissions.manage')||user.effective.some(key=>!canGrant(key)));
 const initial=key=>user.deny.includes(key)?'deny':user.allow.includes(key)?'allow':'inherit';
 let dirty=false,asking=false;
 const status=el('span',{role:'status'}),counts=el('p',{class:'permission-counts','aria-live':'polite'}),error=el('p',{role:'alert',hidden:true});
 const search=el('input',{type:'search','aria-label':'Rechercher une permission',placeholder:'Rechercher un droit, une catégorie ou un identifiant…'});
 const content=el('div',{class:'permission-body'}),save=el('button',{type:'submit',class:'primary',disabled:true},'Enregistrer les permissions');
 const host=el('dialog',{class:'permission-dialog','aria-label':'Permissions de '+user.name});
 const form=el('form',{},el('header',{class:'permission-header'},el('div',{},el('h2',{},'Permissions de '+user.name),hint('Rôle : '+roles[user.role].label+' · Hériter, Autoriser ou Refuser. Le serveur vérifie chaque changement.')),counts),
  el('div',{class:'permission-tools'},error,search,el('div',{class:'row'},
   button('Tout autoriser',()=>bulk('allow'),'quiet',{disabled:readonly}),button('Tout refuser',()=>bulk('deny'),'quiet',{disabled:readonly}),
   button('Réinitialiser à l’héritage',()=>bulk('inherit'),'quiet',{disabled:readonly}))),content,
  el('footer',{class:'permission-footer'},status,el('div',{class:'row'},button('Annuler',()=>requestClose(),'quiet'),save)));
 if(readonly)content.append(hint('Consultation seule : vos droits ne permettent pas de modifier ce compte.'));
 for(const [prefix,title] of groups){
  const matches=key=>prefix.split('|').some(p=>key.startsWith(p));
  const summary=el('summary',{},title),detail=el('details',{open:true},summary),list=el('div',{class:'permission-list'});
  const note=notes[prefix.split('.')[0]]||notes.accounts;detail.append(hint(note),list);
  for(const [key,label] of Object.entries(permissions).filter(([key])=>matches(key))){
   const effective=el('span',{class:'permission-effective'}),select=el('select',{'aria-label':key,disabled:readonly});
   for(const [value,text] of [['inherit','Hériter'],['allow','Autoriser'],['deny','Refuser']])select.append(el('option',{value,disabled:value==='allow'&&!canGrant(key)},text));
   select.value=initial(key);selects[key]=select;select.onchange=refresh;
   const row=el('div',{class:'permission-item'},el('div',{},el('label',{htmlFor:'permission-'+key},label),el('p',{class:'permission-description'},descriptions[key]||'Fonction contrôlée côté serveur selon le rôle et les exceptions.'),el('code',{},key)),select,effective);
   select.id='permission-'+key;list.append(row);items.push({key,label,title,row,select,effective,detail});
  }
  sections.push({detail,summary,title});content.append(detail);
 }
 function refresh(){
  let allowed=0;
  for(const item of items){
   const yes=user.enabled&&item.select.value!=='deny'&&(item.select.value==='allow'||roles[user.role].permissions.includes(item.key));
   allowed+=yes?1:0;item.effective.textContent=yes?'Autorisé':'Refusé';item.effective.dataset.allowed=String(yes);
  }
  dirty=items.some(item=>item.select.value!==initial(item.key));
  counts.textContent=`${allowed} autorisés · ${items.length-allowed} refusés${user.enabled?'':' · compte désactivé'}`;
  status.textContent=dirty?'Modifications non enregistrées':'Aucune modification';save.disabled=!dirty||readonly;
 }
 const normalize=value=>value.normalize('NFD').replace(/\p{M}/gu,'').toLocaleLowerCase();
 search.oninput=()=>{
  const query=normalize(search.value.trim());
  for(const item of items)item.row.hidden=!normalize(item.key+' '+item.label+' '+item.title).includes(query);
  for(const {detail,summary,title} of sections){const visible=items.filter(i=>i.detail===detail&&!i.row.hidden).length;detail.hidden=!visible;summary.textContent=title+' · '+visible;if(query&&visible)detail.open=true;}
 };
 async function bulk(value){
  if(readonly||asking)return;asking=true;
  const ok=await confirmChoice('Modifier tous les droits ?','Cette modification concerne toutes les catégories, y compris les droits masqués par la recherche. Autoriser reste limité aux droits que vous détenez.');asking=false;
  if(ok){for(const item of items)item.select.value=value==='allow'&&!canGrant(item.key)?'deny':value;refresh();}
 }
 const unload=event=>{if(dirty){event.preventDefault();event.returnValue='';}};
 const navigate=event=>{
  if(location.hash===originalHash)return;
  if(!dirty){close();return;}
  const destination=location.hash;event.stopImmediatePropagation();history.replaceState(null,'',originalHash);
  requestClose().then(left=>{if(left)location.hash=destination;});
 };
 function close(){window.removeEventListener('beforeunload',unload);window.removeEventListener('hashchange',navigate,true);host.close();host.remove();previous?.focus();}
 async function requestClose(){if(asking)return false;asking=true;const leave=!dirty||await confirmChoice('Quitter sans enregistrer ?','Les changements de permissions seraient perdus.',true);asking=false;if(leave)close();return leave;}
 host.oncancel=event=>{event.preventDefault();requestClose();};
 form.onsubmit=async event=>{
  event.preventDefault();if(!dirty||readonly)return;
  const allow=[],deny=[];for(const [key,select] of Object.entries(selects)){if(select.value==='allow')allow.push(key);if(select.value==='deny')deny.push(key);}
  if(asking)return;asking=true;save.disabled=true;error.hidden=true;
  // Temporarily detach for the existing explicit password reauthentication
  // dialog; keep selections if the user cancels or the backend refuses.
  host.close();host.remove();
  try{
   if(await onSave({allow,deny})!==false){close();return;}
  }catch(problem){error.textContent=problem.message;error.hidden=false;}
  finally{asking=false;}
  document.getElementById('dialogs').append(host);host.showModal();refresh();
 };
 host.append(form);document.getElementById('dialogs').append(host);host.showModal();refresh();
 window.addEventListener('beforeunload',unload);window.addEventListener('hashchange',navigate,true);search.focus();
 return host;
}
