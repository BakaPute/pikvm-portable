import {el,button,card,hint,row,field,dialog,table as uiTable,guarded,notify} from '../core/ui.js';

function table(headers,rows){
    const node=uiTable(headers,rows);
    node.classList.add('security-table');
    if(headers.length===5)node.classList.add('security-table-wide');
    node.tabIndex=0;node.setAttribute('role','region');node.setAttribute('aria-label',headers.join(' · '));
    return node;
}

export function mountUsers(outlet,{api,store}){
    let live=true,state,actor;
    const alert=el('p',{role:'alert',hidden:true}),body=el('div'),status=el('p',{role:'status'});
    outlet.append(el('h2',{},'Utilisateurs et permissions'),alert,status,body);
    const request=(route,data)=>api.system('security/'+route,data);
    async function load(){
        try{
            [state,actor]=await Promise.all([request('users'),request('session')]);
            if(!live)return;alert.hidden=true;render();
        }catch(error){if(live){alert.hidden=false;alert.textContent=error.message;}}
    }
    const run=work=>guarded(async()=>{
        if(store.data.session!=='ready')throw Error('Session requise.');
        const reload=await work();if(live&&reload!==false)await load();
    });
    async function mutate(data){
        let admin_password;
        if(!actor.native){
            const credentials=await dialog({title:'Confirmer votre identité',message:'Mot de passe du compte Portable actuel. Il ne sera ni enregistré ni affiché.',fields:[{name:'password',type:'password',label:'Votre mot de passe'}]});
            if(!credentials)return;admin_password=credentials.password;
        }
        await request('mutate',{...data,expected_revision:state.revision,confirmed:true,...(admin_password?{admin_password}:{})});
        notify('Modification enregistrée ; les sessions affectées sont révoquées.');
    }
    async function create(initialize=false){
        const data=await dialog({title:initialize?'Préparer le premier administrateur Portable':'Ajouter un utilisateur',
            message:'Compte Web distinct de KVMD et de Linux. Aucun SSH ni sudo implicite. Mot de passe robuste de 14 caractères minimum.',
            fields:[{name:'name',label:'Identifiant'},{name:'display',label:'Nom affiché'},
                {name:'password',type:'password',label:'Nouveau mot de passe'},
                ...(initialize?[]:[{name:'role',type:'select',label:'Rôle',value:'readonly',options:Object.keys(state.roles)}])],confirm:'Créer'});
        if(!data)return;
        if(initialize)await request('initialize',{name:data.name,password:data.password,confirmed:true});
        else await mutate({action:'create',...data});
    }
    async function edit(user){
        const data=await dialog({title:'Modifier '+user.name,message:'Un changement de droits révoque ses sessions Web. Les accès Linux provisionnés consultent l’activation et les clés Web à chaque nouvelle connexion.',
            fields:[{name:'display',label:'Nom affiché',value:user.display},{name:'role',type:'select',label:'Rôle',options:Object.keys(state.roles),value:user.role},{name:'enabled',type:'checkbox',label:'Compte activé',value:user.enabled}]});
        if(data)await mutate({action:'edit',name:user.name,changes:data});
    }
    async function permissions(user){
        const form=el('form'),host=el('dialog',{'aria-label':'Permissions de '+user.name}),selectors={};
        form.append(el('h2',{},'Permissions de '+user.name),hint('Rôle hérité, autorisation ou refus explicite. Refus prioritaire. La console native exige clavier, macros et souris ensemble ; sinon vidéo sans WebSocket natif. Les permissions HID partielles restent utilisables par les API HTTP autorisées. Les voies non filtrables restent interdites.'));
        const rows=Object.entries(state.permissions).map(([key,title])=>{
            const select=el('select',{'aria-label':key});
            for(const [value,text] of [['inherit','Hériter'],['allow','Autoriser'],['deny','Refuser']])select.append(el('option',{value},text));
            select.value=user.deny.includes(key)?'deny':user.allow.includes(key)?'allow':'inherit';selectors[key]=select;
            return [title+' · '+key,select,user.effective.includes(key)?'Autorisé':'Refusé'];
        });
        form.append(table(['Permission','Choix','Droit effectif actuel'],rows),row(button('Annuler',()=>{host.close();host.remove();},'quiet'),el('button',{type:'submit',class:'primary'},'Enregistrer les permissions')));
        form.onsubmit=event=>{
            event.preventDefault();const allow=[],deny=[];
            for(const [key,select] of Object.entries(selectors)){if(select.value==='allow')allow.push(key);if(select.value==='deny')deny.push(key);}
            host.close();host.remove();run(()=>mutate({action:'edit',name:user.name,changes:{allow,deny}}));
        };
        host.oncancel=()=>host.remove();host.append(form);document.getElementById('dialogs').append(host);host.showModal();
    }
    async function keys(user){
        const pane=el('section',{},el('h3',{},'SSH · '+user.name),hint('Le provisionnement Linux initial exige une opération root distincte et vérifiée. Aucun sudo. Une fois provisionné : clés/activation vérifiées à chaque connexion, commande de diagnostic forcée, aucun shell ni tunnel.'));
        const refresh=()=>{pane.remove();run(()=>load());};
        pane.append(table(['Empreinte publique','Action'],user.keys.map(key=>[key.fingerprint,button('Révoquer cette clé',()=>run(async()=>{
            if(await dialog({title:'Révoquer cette clé ?',message:key.fingerprint,confirm:'Révoquer',danger:true}))await mutate({action:'key_remove',name:user.name,fingerprint:key.fingerprint});
        }),'quiet')])));
        pane.append(row(button('Ajouter une clé publique',()=>run(async()=>{
            const data=await dialog({title:'Importer une clé publique',message:'ssh-ed25519 uniquement. Ne collez jamais de clé privée ni d’options authorized_keys.',fields:[{name:'public_key',label:'Clé publique'}]});
            if(data)await mutate({action:'key_add',name:user.name,...data});
        }),'quiet'),button(user.ssh==='disabled'?'Préparer SSH diagnostic':'Interdire SSH',()=>run(async()=>{
            if(await dialog({title:'Modifier l’autorisation SSH ?',message:'Aucun accès root ou sudo. Le premier provisionnement reste manuel.',confirm:'Confirmer'}))await mutate({action:'ssh',name:user.name,mode:user.ssh==='disabled'?'diagnostics':'disabled'});
        }),'quiet'),button('Afficher le plan Linux',()=>guarded(async()=>{
            const plan=await request('ssh-plan',{name:user.name});status.textContent='Plan uniquement, non appliqué. SHA256 : '+plan.sha256;
            pane.append(el('pre',{class:'logs'},JSON.stringify(plan,null,2)));
        }),'quiet'),button('Fermer la fiche SSH',refresh,'quiet')));body.append(pane);
    }
    async function duplicateRole(){
        const base=await dialog({title:'Dupliquer un rôle',message:'Les rôles prédéfinis restent immuables. Les permissions de la copie peuvent être ajustées.',fields:[{name:'source',label:'Rôle source',type:'select',options:Object.keys(state.roles)},{name:'name',label:'Identifiant custom_…',value:'custom_equipe'},{name:'display',label:'Nom affiché'}]});
        if(base)await mutate({action:'role',name:base.name,display:base.display,permissions:state.roles[base.source].permissions});
    }
    async function editRole(name){
        const role=state.roles[name],checks={},form=el('form'),host=el('dialog',{'aria-label':'Modifier le rôle '+name});
        form.append(el('h2',{},role.label));
        for(const [key,title] of Object.entries(state.permissions)){const check=el('input',{type:'checkbox',checked:role.permissions.includes(key),'aria-label':key});checks[key]=check;form.append(field(title,check));}
        form.append(row(button('Annuler',()=>host.remove(),'quiet'),el('button',{type:'submit',class:'primary'},'Enregistrer le rôle')));
        form.onsubmit=event=>{event.preventDefault();host.remove();run(()=>mutate({action:'role',name,display:role.label,permissions:Object.keys(checks).filter(k=>checks[k].checked)}));};
        host.oncancel=()=>host.remove();host.append(form);document.getElementById('dialogs').append(host);host.showModal();
    }
    function render(){
        body.replaceChildren();status.textContent='Révision '+state.revision+' · comptes restreints : passerelle dédiée, activation de production distincte.';
        body.append(hint(state.notice||'Les comptes techniques natifs restent protégés.'));
        if(!state.initialized){body.append(card('Initialisation séparée',hint('Les accès KVMD actuels restent intacts. Choisir un nom distinct des comptes natifs.'),button('Préparer la sécurité Portable',()=>run(()=>create(true)),'primary')));return;}
        body.append(row(button('Ajouter un utilisateur',()=>run(()=>create()),'primary'),button('Dupliquer un rôle',()=>run(duplicateRole),'quiet'),button('Préparer le compte Codex',()=>run(async()=>{
            if(state.users.some(u=>u.name==='codex')){await keys(state.users.find(u=>u.name==='codex'));return false;}
            const data=await dialog({title:'Préparer Codex',message:'Compte Web Maintenance et plan SSH diagnostic. Aucune création Linux ni clé privée générée sur le Pi.',fields:[{name:'password',type:'password',label:'Mot de passe Web distinct'}]});
            if(data)await mutate({action:'create',name:'codex',display:'Codex maintenance',role:'maintenance',...data});
        }),'quiet')));
        body.append(table(['Identité','Type / état','Rôle / droits effectifs','Dernière connexion disponible','Actions'],[
            ...state.native_users.map(user=>[user.name,'KVMD protégé','Administrateur natif','Journaux KVMD natifs','Gestion native distincte']),
            ...state.users.map(user=>[user.display+' ('+user.name+')','Web · '+(user.enabled?'Actif':'Désactivé')+' · '+(user.linux_applied?'Linux '+user.linux_user+' · UID '+user.linux_uid:'Linux non provisionné'),state.roles[user.role].label+' · '+user.effective.length+' droits',user.last_login?new Date(user.last_login*1000).toLocaleString():'Aucune trace disponible',row(
                button('Modifier',()=>run(()=>edit(user)),'quiet',{'aria-label':'Modifier '+user.name}),
                button('Permissions',()=>permissions(user),'quiet',{'aria-label':'Permissions '+user.name}),
                button('Mot de passe',()=>run(async()=>{const data=await dialog({title:'Nouveau mot de passe · '+user.name,message:'Les sessions existantes seront révoquées.',fields:[{name:'password',type:'password',label:'Nouveau mot de passe'}]});if(data)await mutate({action:'password',name:user.name,...data});}),'quiet'),
                button('SSH / clés',()=>keys(user),'quiet',{'aria-label':'SSH '+user.name}),
                button('Révoquer les sessions',()=>run(async()=>{if(await dialog({title:'Révoquer les sessions ?',message:user.name,confirm:'Révoquer'}))await mutate({action:'revoke',name:user.name});}),'quiet'),
                button('Supprimer',()=>run(async()=>{if(await dialog({title:'Supprimer ce compte Web ?',message:'Les connexions SSH gérées seront refusées ; aucun compte Linux, répertoire ni donnée ISO ne sera effacé.',confirm:'Supprimer',danger:true}))await mutate({action:'delete',name:user.name});}),'quiet',{'aria-label':'Supprimer '+user.name}))])
        ]));
        body.append(card('Rôles personnalisés',...Object.keys(state.roles).filter(n=>n.startsWith('custom_')).map(name=>row(state.roles[name].label,button('Modifier le rôle',()=>editRole(name),'quiet')))));
        if(state.linux_accounts?.length)body.append(el('details',{},el('summary',{},'Identités Linux · lecture seule'),
            table(['Identité','UID','Protection'],state.linux_accounts.map(user=>[user.name,String(user.uid),user.protected?'Système / non géré · protégé':'Identité SSH gérée séparément']))));
        body.append(card('Historique des changements',table(['Date','Acteur','Action','Compte / rôle'],state.history.slice(-30).reverse().map(e=>[new Date(e.at*1000).toLocaleString(),e.actor,e.action,e.target])),
            button('Connexions et refus disponibles',()=>guarded(async()=>{const data=await request('audit');body.append(card('Journal d’audit',hint(data.retention),table(['Date','Identité','Événement','Résultat'],data.entries.slice().reverse().map(e=>[new Date(e.at*1000).toLocaleString(),e.actor,e.event,e.allowed?'Autorisé':'Refusé']))));}),'quiet')));
    }
    load();return()=>{live=false;};
}
