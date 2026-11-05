// Presentation only; the server gateway is authoritative for every operation.
export function can(store,...permissions){const access=store.data.access;return !access||permissions.every(p=>access.permissions.includes(p));}
export function moduleAllowed(store,id){
    if(!store.data.access)return true;
    const needs={dashboard:'system.diagnostics',kvm:'kvm.video',images:'iso.view',share:'share.status',network:'system.network',tools:'system.diagnostics',power:'system.diagnostics'};
    if(id==='terminal')return false;
    return id==='settings'||can(store,needs[id]||'__unknown__');
}
