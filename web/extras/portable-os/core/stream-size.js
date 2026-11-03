// Observe decoded media/native status only. No stream/HID connection is created.
export function streamSize(doc) {
    const valid=(width,height)=>Number.isFinite(width)&&Number.isFinite(height)&&width>=16&&height>=16&&width<=32768&&height<=32768;
    for(const id of ['stream-video','stream-image','stream-canvas']){
        const node=doc.getElementById(id);
        if(!node||node.hidden||node.classList.contains('hidden')||node.style.display==='none')continue;
        if(id==='stream-image'&&/blank-stream\./.test(node.getAttribute('src')||''))continue;
        let width,height;
        if(id==='stream-video'){width=node.videoWidth;height=node.videoHeight;}
        else if(id==='stream-image'){width=node.naturalWidth;height=node.naturalHeight;}
        else if(node.hasAttribute('width')&&node.hasAttribute('height')){width=node.width;height=node.height;}
        if(valid(width,height))return {width,height};
    }
    const title=doc.querySelector('#stream-window-header .window-grab')?.textContent||'';
    const match=title.match(/\b(\d{2,5})x(\d{2,5})\b/);
    if(match&&valid(+match[1],+match[2]))return {width:+match[1],height:+match[2]};
    return null; // Offline: retain the last known ratio (initial placeholder 16:9).
}
