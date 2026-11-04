import {el, button} from './ui.js';
import {releaseNativeInput} from './native-bridge.js';
import {projectControls} from './native-controls.js';
import {streamSize} from './stream-size.js';
import {sharePanel} from './kvm-share-panel.js';
import {activity,values} from './configuration.js';
export const nativeMenus = Object.freeze({
    'msd-dropdown':'Lecteur ISO','atx-dropdown':'ATX','shortcuts-dropdown':'Raccourcis',
    'macro-dropdown':'Macros','text-dropdown':'Texte','system-dropdown':'Vidéo & HID',
});
export function adaptKvm(frame, fullscreen, onSize=()=>{}, context) {
    const doc=frame.contentDocument,win=frame.contentWindow,stream=doc.getElementById('stream-window');
    if(['navbar','stream-window','hid-mute-switch',...Object.keys(nativeMenus)].some(id=>!doc.getElementById(id))||
        !stream.querySelector('[data-wm-window-set-full-tab]')||
        Object.keys(nativeMenus).some(id=>!doc.getElementById(id).querySelector('.menu')))
        throw new Error('Structure KVM incompatible : adaptation interrompue. Ouvrir le KVM de secours.');
    let enabled=false,active=true,projection,source,modalProjection,nativeModal,parentModal;
    let selectedMenu=null,lastSize='',lastPresence=0;
    const listeners=[];
    const on=(target,type,fn,options)=>{target.addEventListener(type,fn,options);listeners.push(()=>target.removeEventListener(type,fn,options));};
    const mute=doc.getElementById('hid-mute-switch');
    const captured=()=>active&&enabled&&!mute.checked;
    const controls=el('div',{class:'kvm-controls','aria-label':'Commandes KVM'});
    const toggle=button('Activer clavier / souris',()=>setEnabled(!captured(),true),'quiet',{'aria-pressed':'false'});
    controls.append(toggle,button('Plein écran',fullscreen,'quiet'));
    const leds=Array.from(doc.querySelectorAll('#system-dropdown > .menu-button img'),node=>projectControls(node));
    if(leds.length)controls.append(el('span',{class:'kvm-signals','aria-label':'État KVMD'},leds.map(binding=>binding.root)));
    const panel=el('section',{class:'card kvm-subpanel',id:'kvm-control-panel',hidden:true,'aria-labelledby':'kvm-control-heading'});
    const heading=el('h2',{id:'kvm-control-heading'});
    const body=el('div',{class:'kvm-panel-body'});
    const close=button('Fermer',()=>closePanel(),'quiet');
    panel.append(el('div',{class:'row'},heading,close),body);
    const toolbarButtons=[];
    const usb=sharePanel(context);
    const usbControl=button('Clé USB',()=>{
        if(selectedMenu==='share'&&!panel.hidden){closePanel();return;}
        closePanel();releaseNativeInput(frame);selectedMenu='share';
        heading.textContent='Clé USB · PIKVM-SHARE';body.replaceChildren(usb.root);panel.hidden=false;
        usb.open();syncSelected();
    },'quiet',{'data-kvm-menu':'share','aria-expanded':'false','aria-controls':'kvm-control-panel'});
    function activate(node){
        if(!active)return true;
        if(node.hasAttribute('data-wm-window-close')){node.click();closePanel();return true;}
        const target=node.getAttribute('data-wm-window-show');
        if(target==='webterm-window'){location.hash='#terminal';return true;}
        if(target&&target!=='stream-window'&&doc.getElementById(target)){
            node.click();const windowNode=doc.getElementById(target);openedWindows.add(windowNode);
            openPanel(windowNode,windowNode.querySelector('.window-grab')?.textContent||'Contrôles natifs');return true;
        }
        return false; // All other actions remain native.
    }
    function openPanel(node,title){
        if(!active)return;
        usb.close();
        releaseNativeInput(frame);
        if(source!==node&&source?.classList.contains('window')&&!source.classList.contains('hidden'))source.querySelector('[data-wm-window-close]')?.click();
        source=node;projection=projectControls(node,{activate,enabled:captured,allowed:()=>active});
        heading.textContent=title;body.replaceChildren(projection.root);panel.hidden=false;
        syncSelected();
    }
    function closePanel(){
        usb.close();
        if(source?.classList.contains('window')&&!source.classList.contains('hidden'))source.querySelector('[data-wm-window-close]')?.click();
        source=null;projection=null;selectedMenu=null;body.replaceChildren();panel.hidden=true;
        syncSelected();
    }
    function syncSelected(){for(const [control,native]of toolbarButtons)control.setAttribute('aria-expanded',String(!panel.hidden&&selectedMenu===native.id));
        usbControl.setAttribute('aria-expanded',String(!panel.hidden&&selectedMenu==='share'));}
    for(const [id,title] of Object.entries(nativeMenus)){
        const native=doc.getElementById(id);
        const control=button(title,()=>{
            if(selectedMenu===id&&!panel.hidden){closePanel();return;}
            native.querySelector('.menu-button')?.dispatchEvent(new win.MouseEvent('mousedown',{bubbles:true,cancelable:true,button:0}));
            selectedMenu=id;openPanel(native.querySelector('.menu'),title);
        },'quiet',{'data-kvm-menu':id,'aria-expanded':'false','aria-controls':'kvm-control-panel'});
        controls.append(control);toolbarButtons.push([control,native]);
        if(id==='msd-dropdown')controls.append(usbControl);
    }
    function setEnabled(value,focus=false){
        if(!value){const stop=doc.getElementById('hid-recorder-stop');if(stop&&!stop.disabled)stop.click();}
        releaseNativeInput(frame);enabled=!!value&&active;mute.checked=!enabled;
        doc.documentElement.classList.toggle('portable-hid-enabled',enabled);
        if(enabled&&focus){win.focus();stream.focus();}
        sync();
    }
    // Native stream receives events only during an explicit active capture.
    const guard = event => {
        const target = event.target;
        const nativeInput = target.closest?.('#stream-window,#keyboard-window,#mouse-window,[data-keyboard-shortcut],#hid-recorder-play,#hid-recorder-record,#hid-pak-button');
        const windowManagement = target.closest?.('.window-header,[data-wm-window-close]');
        const pasteShortcut = target.closest?.('#hid-pak-text') && event.ctrlKey && event.key === 'Enter';
        if (!captured() && ((nativeInput && !windowManagement) || pasteShortcut)) {
            event.preventDefault(); event.stopImmediatePropagation();
        }
    };
    for (const type of ['click','keydown','keyup','mousedown','mouseup','mousemove','wheel','touchstart','touchmove','touchend','pointerdown'])
        on(doc, type, guard, {capture: true, passive: false});

    on(mute,'change',()=>setEnabled(!mute.checked));
    on(window,'blur',()=>releaseNativeInput(frame));
    on(doc,'keydown',event=>{
        if(event.code==='Escape'&&event.ctrlKey&&event.shiftKey){event.preventDefault();event.stopImmediatePropagation();setEnabled(false);toggle.focus();}
    },true);
    const openedWindows=new WeakSet();
    function closeNativeModal(){
        const chooser=doc.getElementById('pkdf-panel');if(chooser)chooser.hidden=true;
        nativeModal?.querySelector('[data-x-wm-modal-cancel]')?.click();
    }
    function syncModal(){
        // The folder browser is owned by the native page, but its overlay lives
        // outside #msd-menu (and is hidden by the embedded KVM stylesheet).
        // Project only this known widget; keep its listeners and API guards native.
        const chooser=doc.querySelector('#pkdf-overlay:not([hidden]) > #pkdf-panel:not([hidden])');
        const current=active?(Array.from(doc.querySelectorAll('.modal')).find(node=>!node.classList.contains('hidden'))||chooser):null;
        if(parentModal&&(!current||current!==nativeModal||!current.isConnected)){
            parentModal.close();parentModal.remove();parentModal=null;modalProjection=null;nativeModal=null;
        }
        if(current&&!parentModal&&!document.querySelector('dialog[open]')){
            const choosing=current===chooser;
            const cancel=()=>{if(choosing)current.hidden=true;else current.querySelector('[data-x-wm-modal-cancel]')?.click();};
            nativeModal=current;
            modalProjection=projectControls(current,{activate,enabled:captured,allowed:()=>active});
            parentModal=el('dialog',{class:'kvm-native-dialog','aria-label':choosing?'Choisir une image ISO':'Confirmation KVMD',oncancel:event=>{
                event.preventDefault();cancel();
            }},...(choosing?[el('div',{class:'row'},el('h2',{},'Choisir une image ISO'),button('Fermer le sélecteur',cancel,'quiet'))]:[]),modalProjection.root);
            document.getElementById('dialogs').append(parentModal);parentModal.showModal();
        }
        modalProjection?.sync();
    }
    function sync(){
        if(context&&active&&!document.hidden&&Date.now()-lastPresence>=10000){lastPresence=Date.now();activity(context,'kvm_presence');}
        const size=streamSize(doc);
        if(size&&`${size.width}x${size.height}`!==lastSize){lastSize=`${size.width}x${size.height}`;onSize(size);}
        leds.forEach(binding=>binding.sync());
        toggle.textContent=captured()?'Désactiver clavier / souris':'Activer clavier / souris';
        toggle.setAttribute('aria-pressed',String(captured()));toggle.disabled=!active;
        usbControl.disabled=!active;
        for(const [control,native]of toolbarButtons)control.disabled=!active||native.classList.contains('feature-disabled');
        for(const node of doc.querySelectorAll('.window:not(#stream-window):not(#stream-ocr-window)')){
            if(node.classList.contains('hidden')){openedWindows.delete(node);continue;}
            if(!openedWindows.has(node)&&active){openedWindows.add(node);openPanel(node,node.querySelector('.window-grab')?.textContent||'Contrôles natifs');}
        }
        if(source?.classList.contains('window')&&source.classList.contains('hidden'))closePanel();
        syncSelected();
        projection?.sync();syncModal();
    }
    stream.querySelector('[data-wm-window-set-full-tab]').click();
    for(const id of ['mouse-window','keyboard-window']){
        const node=doc.getElementById(id);if(node&&!node.classList.contains('hidden'))node.querySelector('[data-wm-window-close]')?.click();
    }
    doc.documentElement.classList.add('portable-kvm');
    setEnabled(false);
    let interval=null;
    function schedule(){
        clearInterval(interval);interval=null;
        if(active&&!document.hidden)interval=setInterval(sync,150);
    }
    on(document,'visibilitychange',()=>{
        if(document.hidden)setEnabled(false);
        schedule();
    });
    schedule();
    let preferenceKey='';
    let initialApplied=false;
    const configure=()=>{
        const config=values(context.store),key=JSON.stringify([config.kvm_order,config.kvm_hidden,config.kvm_fit]);
        if(key===preferenceKey)return;preferenceKey=key;
        for(const id of config.kvm_order||[]){const control=controls.querySelector(`[data-kvm-menu="${id}"]`);if(control){control.hidden=(config.kvm_hidden||[]).includes(id);controls.append(control);}}
        for(const node of doc.querySelectorAll('#stream-image,#stream-video,#stream-canvas'))node.style.setProperty('object-fit',config.kvm_fit==='cover'?'cover':'contain','important');
        if(!initialApplied&&config.kvm_default_panel){initialApplied=true;
            if(config.kvm_default_panel!=='none')controls.querySelector(`[data-kvm-menu="${config.kvm_default_panel}"]`)?.click();}
    };
    const unsubscribe=context?.store.subscribe(configure);
    if(context)configure();
    return {controls,panel,enable:()=>setEnabled(true,true),
        suspend(){setEnabled(false);active=false;clearInterval(interval);interval=null;closePanel();closeNativeModal();sync();},
        resume(){active=true;schedule();sync();},
        destroy(){setEnabled(false);active=false;clearInterval(interval);unsubscribe?.();listeners.forEach(fn=>fn());closePanel();
            closeNativeModal();parentModal?.close();parentModal?.remove();controls.remove();panel.remove();},
    };
}
