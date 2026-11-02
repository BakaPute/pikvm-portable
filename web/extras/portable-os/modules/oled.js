import {OledInput} from '../core/oled-input.js';
import {el, button} from '../core/ui.js';

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
    let frame, timer, reading = false, controller, armedControl = null;
    const status = el('p', {class:'oled-status',role:'status','aria-live':'polite'}, 'Connexion…');
    const detail = el('p', {class:'oled-detail muted'});
    const canvas = el('canvas', {width:128,height:64,'aria-hidden':'true'});
    const screen = button('',()=>{},'oled-screen',{'aria-label':'Bouton OLED : appuyer et maintenir',disabled:true});
    screen.append(canvas);
    const arm = el('input',{type:'checkbox',onchange:()=>{armedControl=arm.checked?frame?.control_id:null;}});
    const armText = el('span');
    const armLabel = el('label',{class:'oled-arm',hidden:true},arm,armText);
    const freshness=el('span',{class:'oled-freshness',role:'status'});
    const diagnostics=el('details',{class:'oled-diagnostics'},el('summary',{},'Diagnostic OLED'));
    const measurement=el('output');diagnostics.append(measurement);
    host.append(screen,status,detail,freshness,armLabel,diagnostics);
    const text=(node,value)=>{if(node.textContent!==value)node.textContent=value;};
    const metrics={};
    const input=new OledInput(async data=>{
        const began=performance.now();
        const response=await context.api.request('/extras/portable-os/api/oled/button',
            {method:'POST',body:data,timeout:data.action==='keep'?650:1500});
        metrics['input_'+data.action+'_ms']=performance.now()-began;
        metrics.api_relay_ms=response.result?.api_relay_ms;
        return response;
    },(state,message)=>{
        screen.setAttribute('aria-pressed',String(!!input.active));
        text(status,message||({holding:'Maintien en cours…',released:'Appui relâché',cancelled:'Appui annulé'})[state]||'');
    });
    function visible() {
        return !host.hidden && !document.hidden && (!document.fullscreenElement||document.fullscreenElement.contains(host)) &&
            getComputedStyle(host.closest('.sidebar')).visibility !== 'hidden';
    }
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
        const began=performance.now();
        try {
            const {result}=await context.api.request('/extras/portable-os/api/oled',{signal:controller.signal,timeout:1500});
            if (!visible()||context.store.data.session!=='ready') return;
            if(result.width!==128||result.height!==64||result.format!=='1bpp-msb') throw new Error('Format OLED incompatible.');
            if(frame?.pixels!==result.pixels) canvas.getContext('2d').putImageData(new ImageData(unpackPixels(result.pixels),128,64),0,0);
            if(armedControl!==result.control_id) {arm.checked=false;armedControl=null;}
            frame=result;
            screen.disabled=false;
            if(!input.active) text(status,'Appuyer ou maintenir · Échap annule');
            // Controller health is diagnostic; a valid image never changes the
            // interaction state or flashes a warning during renderer handoff.
            text(freshness,'');
            text(detail,(result.physical==='connected'?'OLED physique connecté':'Mode virtuel')+' · miroir natif');
            const kind=capability(result); armLabel.hidden=!kind;
            arm.disabled=!!context.store.data.transfer||!!context.store.data.operation;
            text(armText,kind==='power'?'Autoriser arrêt / redémarrage pour cet appui':
                kind==='network'?'Autoriser le changement réseau (connexion interrompue)':
                'Autoriser la suppression de l’image affichée');
            Object.assign(metrics,{frame_rtt_ms:performance.now()-began,frame_age_ms:(result.age||0)*1000,
                api_auth_ms:result.api_auth_ms,api_frame_ms:result.api_frame_ms,...result.timing,
                controller_poll_age_ms:result.controller?.poll_age_ms});
            if(diagnostics.open)text(measurement,JSON.stringify({...metrics,...input.metrics},null,2));
        } catch(error) {
            if(visible()&&context.store.data.session!=='expired') {
                text(freshness,'Image conservée · actualisation en attente');
                metrics.frame_error=error.message;metrics.frame_rtt_ms=performance.now()-began;
                if(diagnostics.open)text(measurement,JSON.stringify({...metrics,...input.metrics},null,2));
            }
            // Frame transport is observational. It never releases pointer capture,
            // disables a held button, or cancels the independently renewed lease.
        } finally {
            reading=false;controller=null;
            if(visible()&&context.store.data.session==='ready') timer=setTimeout(refresh,200);
        }
    }
    function start(event) {
        if(input.active||screen.disabled||!frame||!visible()||context.store.data.session!=='ready') return;
        if(event?.button!==undefined&&event.button!==0) return;
        event?.preventDefault();
        screen.focus();
        if(event?.pointerId!==undefined) screen.setPointerCapture(event.pointerId);
        const mayArm=!context.store.data.transfer&&!context.store.data.operation;
        const permit=mayArm&&!arm.disabled&&arm.checked&&armedControl===frame.control_id?capability(frame):'';
        arm.checked=false;armedControl=null;
        input.start(frame.control_id,permit);
    }
    const finish=cancel=>input.end(cancel);
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
