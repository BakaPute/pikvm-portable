import {notify} from './ui.js';

export const values=store=>store.get('settings')?.values||{};
export function activity(context,source){
    if(context.store.data.session!=='ready'||!values(context.store).idle_enabled)return;
    const now=performance.now();context.activityTimes??={};
    if(now-(context.activityTimes[source]??-Infinity)<10000)return;
    context.activityTimes[source]=now;
    context.api.system('activity',{source}).catch(()=>{}); // Missing telemetry never grants shutdown permission.
}
export function bindActivity(doc,context,kind){
    const onKey=e=>{if(e.isTrusted)activity(context,kind==='kvm'?'keyboard':kind==='terminal'?'terminal':'web');};
    const onPointer=e=>{if(e.isTrusted)activity(context,kind==='kvm'?'mouse':kind==='terminal'?'terminal':'web');};
    doc.addEventListener('keydown',onKey,{capture:true});
    for(const type of ['pointerdown','pointermove','wheel'])doc.addEventListener(type,onPointer,{capture:true,passive:true});
    return()=>{doc.removeEventListener('keydown',onKey,true);for(const type of ['pointerdown','pointermove','wheel'])doc.removeEventListener(type,onPointer,true);};
}

export function applyAppearance(store){
    let batteryAlert=false,networkAlert=false;
    return store.subscribe(data=>{
        const config=values(store);
        if(store.get('settings')?.revision>0&&['dark','light'].includes(config.theme))document.documentElement.dataset.theme=config.theme;
        document.documentElement.classList.toggle('reduce-animations',config.animations===false);
        const battery=data.resources.battery,network=data.resources.network;
        const low=battery&&!battery.stale&&Number.isFinite(battery.data?.percent)&&battery.data.percent<=(config.battery_low??20);
        if(low&&!batteryAlert&&config.battery_notifications)notify('Batterie faible : mesure estimée '+battery.data.percent+' %.');batteryAlert=low;
        const missing=!!network?.stale;
        if(missing&&!networkAlert&&config.network_notifications)notify('Informations réseau indisponibles ; aucune déconnexion du PC n’est déduite.',true);networkAlert=missing;
    });
}
