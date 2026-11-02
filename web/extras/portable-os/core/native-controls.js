import {el} from './ui.js';

// New Portable OS components, bound to the existing live native controls.
// Source nodes, listeners and window-manager ownership never leave the iframe.
export function projectControls(source, {activate, enabled=()=>true, allowed=()=>true, rootVisible=true}={}) {
    const nodes=new WeakMap();let serial=0;
    const win=source.ownerDocument.defaultView;
    const blocked=node=>!allowed()||node.disabled||node.readOnly||!!node.closest('.feature-disabled')||(!enabled()&&!node.closest('.window-header,[data-wm-window-close]')&&
        !!node.closest('#keyboard-window,#mouse-window,[data-keyboard-shortcut],#hid-recorder-play,#hid-recorder-record,#hid-pak-button'));
    const event=(node,type,values={})=>node.dispatchEvent(type.startsWith('mouse')?
        new win.MouseEvent(type,{bubbles:true,cancelable:true,button:0,...values}):
        new win.Event(type,{bubbles:true,cancelable:true}));
    function make(node) {
        if(node.nodeType===3)return document.createTextNode(node.textContent);
        if(node.nodeType!==1||['SCRIPT','STYLE','LINK','IFRAME','OBJECT'].includes(node.tagName))return null;
        const keypad=node.hasAttribute('data-keypad-code');
        const tag=keypad?'button':node.tagName.toLowerCase();
        const led=tag==='img'&&/\bled-(green|red|gray|yellow|blue)\b/.test(node.className);
        const target=el(led?'span':['button','input','select','textarea','label','a','img','table','tbody','thead','tr','td','th','details','summary','hr','p','pre','b','i','strong','small','sup','br'].includes(tag)?tag:'div');
        target.className=['input','textarea','select'].includes(tag)?'native-field':
            tag==='button'?'quiet':tag==='table'?'native-fields':tag==='div'?'native-group':'';
        if(node.id)target.dataset.nativeId=node.id;
        if(led){target.dataset.nativeLed='gray';target.setAttribute('role','status');}
        if(keypad)target.dataset.nativeKey=node.getAttribute('data-keypad-code');
        if(node.classList.contains('keypad-row'))target.classList.add('native-keys');
        if(['input','select','textarea','button'].includes(tag)) {
            target.id='native-proxy-'+(++serial)+'-'+Math.random().toString(36).slice(2,7);
            const label=Array.from(node.labels||[],n=>n.textContent.trim()).filter(Boolean).join(' ')||node.closest('tr')?.querySelector('td')?.textContent.trim();
            target.setAttribute('aria-label',node.getAttribute('aria-label')||(keypad?node.textContent.trim():'')||label||node.title||node.textContent.trim()||node.name||node.id||tag);
            if(tag==='input')target.type=node.type;
            if(tag==='button') {
                target.type='button';
                let down=false;
                const release=e=>{if(down){down=false;event(node,'mouseup',{button:e?.button||0});}};
                target.addEventListener('pointerdown',e=>{if(!blocked(node)){down=true;target.setPointerCapture(e.pointerId);event(node,'mousedown',{button:e.button,buttons:e.buttons,ctrlKey:e.ctrlKey,shiftKey:e.shiftKey,altKey:e.altKey,metaKey:e.metaKey});}});
                for(const type of ['pointerup','pointercancel','lostpointercapture'])target.addEventListener(type,release);
                if(keypad)target.addEventListener('contextmenu',e=>e.preventDefault());
                target.addEventListener('click',e=>{e.preventDefault();if(!blocked(node)){if(!activate?.(node))node.click();}});
                target.addEventListener('keydown',e=>{if([' ','Enter'].includes(e.key)&&!e.repeat&&!blocked(node)){down=true;event(node,'mousedown');}});
                target.addEventListener('keyup',e=>{if([' ','Enter'].includes(e.key))release();});
            } else {
                const update=type=>{
                    if(blocked(node))return;
                    if(node.type==='file')node.files=target.files;
                    else if(['checkbox','radio'].includes(node.type))node.checked=target.checked;
                    else node.value=target.value;
                    event(node,type);
                };
                target.addEventListener('input',()=>update('input'));
                target.addEventListener('change',()=>update('change'));
                if(['checkbox','radio'].includes(node.type))target.addEventListener('click',()=>update('click'));
                for(const type of ['keydown','keyup'])target.addEventListener(type,e=>{
                    if(!node.dispatchEvent(new win.KeyboardEvent(type,{bubbles:true,cancelable:true,key:e.key,code:e.code,ctrlKey:e.ctrlKey,altKey:e.altKey,shiftKey:e.shiftKey,metaKey:e.metaKey})))e.preventDefault();
                });
            }
        }
        if(tag==='a') {
            target.href=node.href;
            target.addEventListener('click',e=>{if(!e.ctrlKey&&!e.metaKey){e.preventDefault();node.click();}});
        }
        return target;
    }
    function visit(node,isRoot=false) {
        let target=nodes.get(node);
        if(!target){target=make(node);if(!target)return null;nodes.set(node,target);}
        if(node.nodeType===3){if(target.textContent!==node.textContent)target.textContent=node.textContent;return target;}
        const tag=node.tagName.toLowerCase();
        const responsive=node.id==='keyboard-mobile'||node.id==='keyboard-desktop';
        target.hidden=!(isRoot&&rootVisible)&&(node.hidden||node.classList.contains('hidden')||node.style.display==='none'||(responsive&&win.getComputedStyle(node).display==='none'));
        if(target.dataset.nativeLed){target.dataset.nativeLed=(node.className.match(/\bled-(green|red|gray|yellow|blue)\b/)||[])[1]||'gray';target.setAttribute('aria-label',node.title||node.id);}
        const pressed=['pressed','holded','locked'].some(name=>node.classList.contains(name));
        target.classList.toggle('native-pressed',pressed);
        if(node.hasAttribute('data-keypad-code'))target.setAttribute('aria-pressed',String(pressed));
        if('disabled' in target)target.disabled=!!blocked(node);
        if('readOnly' in target)target.readOnly=!!node.readOnly;
        if('required' in target)target.required=!!node.required;
        for(const attr of ['title','min','max','step','placeholder','accept','multiple']) {
            const value=node.getAttribute(attr);
            if(value===null)target.removeAttribute(attr);else if(target.getAttribute(attr)!==value)target.setAttribute(attr,value);
        }
        if(tag==='img'){if(target.src!==node.src)target.src=node.src;target.alt=node.alt||'';}
        if(tag==='select') {
            const signature=Array.from(node.options,o=>JSON.stringify([o.value,o.text,o.disabled])).join();
            if(target.dataset.options!==signature){target.replaceChildren(...Array.from(node.options,o=>el('option',{value:o.value,disabled:o.disabled},o.text)));target.dataset.options=signature;}
        }
        if(['input','textarea','select'].includes(tag)) {
            if(tag==='input'&&['checkbox','radio'].includes(node.type))target.checked=node.checked;
            else if(node.type!=='file'&&document.activeElement!==target&&target.value!==node.value)target.value=node.value;
            if(tag==='input')return target;
            if(tag!=='select'&&tag!=='textarea')return target;
            return target;
        }
        const wanted=Array.from(node.childNodes,n=>visit(n)).filter(Boolean);
        let index=0;
        for(const child of wanted){if(target.childNodes[index]!==child)target.insertBefore(child,target.childNodes[index]||null);index++;}
        while(target.childNodes.length>wanted.length)target.lastChild.remove();
        if(tag==='label'&&node.htmlFor){const control=nodes.get(node.ownerDocument.getElementById(node.htmlFor));if(control)target.htmlFor=control.id;}
        return target;
    }
    const root=visit(source,true);root.classList.add('native-control-content');
    if(source.id==='keyboard-window'||source.id==='mouse-window'){
        root.tabIndex=0;
        for(const type of ['keydown','keyup'])root.addEventListener(type,e=>{
            if(!enabled()||e.target.matches('input,select,textarea')||[' ','Enter'].includes(e.key))return;
            if(!source.dispatchEvent(new win.KeyboardEvent(type,{bubbles:true,cancelable:true,key:e.key,code:e.code,location:e.location,repeat:e.repeat,
                ctrlKey:e.ctrlKey,altKey:e.altKey,shiftKey:e.shiftKey,metaKey:e.metaKey,modifierCapsLock:e.getModifierState('CapsLock')})))e.preventDefault();
        });
    }
    return {root,sync:()=>visit(source,true)};
}
