import {el, button, hint} from './ui.js';
import {shareModes, usbEvidence} from './state.js';

// Read-only summary. Mode transitions and files stay in the existing SHARE module,
// which owns the proper-ejection confirmation and the filesystem exclusion rules.
export function sharePanel(context) {
    const status=el('p',{role:'status'}),evidence=hint(''),actions=hint('');
    const link=el('a',{href:'#share',class:'button'},'Gérer PIKVM-SHARE');
    const refresh=button('Actualiser',()=>load(),'quiet');
    const root=el('div',{},status,evidence,actions,el('div',{class:'row'},refresh,link));
    let epoch=0,unsubscribe,controller;
    function render(){
        if(!context)return;
        const {resources,session}=context.store.data,share=resources.share,usb=resources.usb;
        refresh.disabled=session!=='ready'||!!controller;
        link.hidden=session!=='ready';
        if(session!=='ready'){status.textContent='Session PiKVM requise.';evidence.textContent='';actions.textContent='';return;}
        const known=share&&!share.stale&&share.data&&Object.hasOwn(shareModes,share.data.mode);
        status.textContent=known?`Drive 1 · ${shareModes[share.data.mode]}${share.data.uploads?' · transfert occupé':''}`:
            `État Drive 1 indisponible : ${share?.error||'vérification en cours'}`;
        evidence.textContent=usb&&!usb.stale?usbEvidence(usb.data):`Diagnostic USB indisponible${usb?.error?' : '+usb.error:''}.`;
        actions.textContent=!known?'Actualise l’état avant toute opération dans PIKVM-SHARE.':share.data.uploads?
            'Un transfert est en cours. Attends sa fin avant de changer de mode.':share.data.mode==='web'?
            'Les fichiers sont accessibles en gestion Web. Le passage USB se fait dans PIKVM-SHARE.':share.data.mode==='usb'?
            'Éjecte proprement le lecteur sur le PC avant de demander la gestion Web dans PIKVM-SHARE.':
            'Ouvre PIKVM-SHARE pour les actions autorisées et les éventuelles étapes de récupération.';
    }
    async function load(){
        if(!context||controller||context.store.data.session!=='ready')return;
        const generation=epoch;controller=new AbortController();const signal=controller.signal;render();
        await Promise.allSettled([['share','/extras/pikvm-share/api/status'],['usb','/extras/portable-os/api/usb']].map(async([name,url])=>{
            try{const data=await context.api.request(url,{signal,timeout:10000});
                if(epoch===generation)context.store.resource(name,data.result);
            }catch(error){if(epoch===generation)context.store.resource(name,null,error.message);}
        }));
        if(epoch===generation){controller=null;render();}
    }
    return {root,open(){
        if(!context){status.textContent='Service PIKVM-SHARE indisponible.';refresh.disabled=true;return;}
        unsubscribe?.();unsubscribe=context.store.subscribe(render);
        // Do not display a cached mode as a newly verified state on opening.
        context.store.resource('share',null,'vérification en cours');render();load();
    },close(){epoch++;controller?.abort();controller=null;unsubscribe?.();unsubscribe=null;}};
}
