import {el, button, hint, notify} from '../core/ui.js';

export function unpackPixels(encoded) {
    const bits = atob(encoded);
    if (bits.length !== 1024) throw new Error('Framebuffer OLED incompatible.');
    const pixels = new Uint8ClampedArray(128 * 64 * 4);
    for (let index = 0; index < 8192; index++) {
        const on = bits.charCodeAt(index >> 3) & (128 >> (index & 7));
        const offset = index * 4;
        pixels[offset] = on ? 212 : 5; pixels[offset + 1] = on ? 247 : 10;
        pixels[offset + 2] = on ? 230 : 9; pixels[offset + 3] = 255;
    }
    return pixels;
}

export function openOled(context) {
    const host = document.getElementById('oled-sidebar');
    if (!host.dataset.ready) createPanel(host, context);
    host.hidden = !host.hidden;
    document.getElementById('device-oled').setAttribute('aria-expanded', String(!host.hidden));
    host.dispatchEvent(new Event('oled-toggle'));
}

function createPanel(host, context) {
    host.dataset.ready = 'true';
    let frame, timer, reading = false, controller, active, armedControl = null;
    const status = el('p', {class:'oled-status',role:'status','aria-live':'polite'}, 'Connexion…');
    const detail = el('p', {class:'oled-detail muted'});
    const canvas = el('canvas', {width:128,height:64,'aria-hidden':'true'});
    const screen = button('',()=>{},'oled-screen',{'aria-label':'Bouton OLED : appuyer et maintenir',disabled:true});
    screen.append(canvas);
    const arm = el('input',{type:'checkbox',onchange:()=>{armedControl=arm.checked?frame?.control_id:null;}});
    const armText = el('span');
    const armLabel = el('label',{class:'oled-arm',hidden:true},arm,armText);
    host.append(screen,status,detail,armLabel);
    function visible() {
        return !host.hidden && !document.hidden && (!document.fullscreenElement||document.fullscreenElement.contains(host)) &&
            getComputedStyle(host.closest('.sidebar')).visibility !== 'hidden';
    }
    const request = (data) => context.api.request('/extras/portable-os/api/oled/button',
        {method:'POST',body:data,timeout:1500});
    function capability(data) {
        const c=data?.context||{};
        if ((c.screen==='menu'&&c.selection===0)||c.screen==='rescue-power') return 'power';
        if (c.screen==='rescue') return 'network';
        if (c.screen==='iso-confirm') return 'delete';
        return '';
    }
    async function refresh() {
        clearTimeout(timer);
        if (!visible() || reading || context.store.data.session!=='ready') return;
        reading=true; controller=new AbortController();
        try {
            const {result}=await context.api.request('/extras/portable-os/api/oled',{signal:controller.signal,timeout:1500});
            if (!visible()||context.store.data.session!=='ready') return;
            if(result.width!==128||result.height!==64||result.format!=='1bpp-msb') throw new Error('Format OLED incompatible.');
            if(frame?.id!==result.id) canvas.getContext('2d').putImageData(new ImageData(unpackPixels(result.pixels),128,64),0,0);
            if(armedControl!==result.control_id) {arm.checked=false;armedControl=null;}
            frame=result;
            if(!result.button_available||(active?.permit&&active.control!==result.control_id)) finish(true);
            screen.disabled=!result.button_available;
            if(!active) status.textContent=result.button_available?'Appuyer ou maintenir · Échap annule':'Gestionnaire indisponible';
            detail.textContent=(result.physical==='connected'?'OLED physique connecté':'Mode virtuel')+' · miroir natif';
            const kind=capability(result); armLabel.hidden=!kind;
            arm.disabled=!!context.store.data.transfer||!!context.store.data.operation;
            armText.textContent=kind==='power'?'Autoriser arrêt / redémarrage pour cet appui':
                kind==='network'?'Autoriser le changement réseau (connexion interrompue)':
                'Autoriser la suppression de l’image affichée';
        } catch(error) {
            if(visible()&&context.store.data.session!=='expired') {
                status.textContent='Hors ligne : '+error.message; screen.disabled=true;
                detail.textContent='Dernière image conservée';
            }
            // Lost display data also cancels input; it must never keep a blind hold.
            finish(true);
        } finally {
            reading=false;controller=null;
            if(visible()&&context.store.data.session==='ready') timer=setTimeout(refresh,200);
        }
    }
    function start(event) {
        if(active||screen.disabled||!frame||!visible()||context.store.data.session!=='ready') return;
        if(event?.button!==undefined&&event.button!==0) return;
        event?.preventDefault();
        screen.focus();
        if(event?.pointerId!==undefined) screen.setPointerCapture(event.pointerId);
        const id=Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join('');
        const mayArm=!context.store.data.transfer&&!context.store.data.operation;
        const gesture={id,control:frame.control_id,ended:false,beat:null,permit:mayArm&&!arm.disabled&&arm.checked&&armedControl===frame.control_id?capability(frame):''};
        active=gesture; arm.checked=false;armedControl=null;
        status.textContent='Maintien en cours…';screen.setAttribute('aria-pressed','true');
        request({action:'start',gesture_id:id,control_id:frame.control_id,permit:gesture.permit})
            .then(()=>{if(active===gesture&&!gesture.ended) beat(gesture);})
            .catch(error=>{if(active===gesture){status.textContent=error.message;finish(true);}});
    }
    async function beat(gesture) {
        if(active!==gesture||gesture.ended) return;
        if(!visible()){finish(true);return;}
        try { await request({action:'keep',gesture_id:gesture.id}); }
        catch(error) { if(active===gesture){status.textContent='Maintien annulé : '+error.message;finish(true);} return; }
        if(active===gesture&&!gesture.ended) gesture.beat=setTimeout(()=>beat(gesture),200);
    }
    function finish(cancel=false) {
        const gesture=active;
        if(!gesture||gesture.ended) return;
        gesture.ended=true;clearTimeout(gesture.beat);active=null;
        screen.setAttribute('aria-pressed','false');
        // Send release immediately, even if the start response has not arrived.
        request({action:cancel?'cancel':'stop',gesture_id:gesture.id})
            .catch(error=>{status.textContent='Relâchement non confirmé : '+error.message;});
        status.textContent=cancel?'Appui annulé':'Appui relâché';
    }
    screen.addEventListener('pointerdown',start);
    screen.addEventListener('pointerup',()=>finish());
    for(const type of ['pointercancel','lostpointercapture']) screen.addEventListener(type,()=>finish(true));
    screen.addEventListener('keydown',event=>{
        if([' ','Enter'].includes(event.key)){event.preventDefault();if(!event.repeat)start();}
        if(event.key==='Escape')finish(true);
    });
    screen.addEventListener('keyup',event=>{if([' ','Enter'].includes(event.key)){event.preventDefault();finish();}});
    screen.addEventListener('blur',()=>finish(true));
    function lifecycle(){
        clearTimeout(timer);
        if(context.store.data.session==='expired'){finish(true);screen.disabled=true;status.textContent='Session PiKVM expirée.';return;}
        if(!visible()){finish(true);controller?.abort();screen.disabled=true;}
        else refresh();
    }
    host.addEventListener('oled-toggle',lifecycle);
    document.addEventListener('visibilitychange',lifecycle);
    document.addEventListener('fullscreenchange',lifecycle);
    window.addEventListener('resize',lifecycle);
    window.addEventListener('blur',()=>finish(true));
    window.addEventListener('pagehide',()=>{finish(true);clearTimeout(timer);controller?.abort();});
    new MutationObserver(lifecycle).observe(document.body,{attributes:true,attributeFilter:['class']});
    context.store.subscribe(data=>{
        if(data.session==='expired'){finish(true);clearTimeout(timer);controller?.abort();screen.disabled=true;
            status.textContent='Session PiKVM expirée.';}
    });
}
