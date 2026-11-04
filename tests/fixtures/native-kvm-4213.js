// Integration harness only: unchanged KVMD 4.213 controllers and DOM;
// synthetic HTTP state and a HID event sink replace the real server/USB host.
import {setRootPrefix} from '/__test/kvmd-4.213/web/share/js/vars.js';
import {initWindowManager} from '/__test/kvmd-4.213/web/share/js/wm.js';
import {Msd} from '/__test/kvmd-4.213/web/share/js/kvm/msd.js';
import {Keyboard} from '/__test/kvmd-4.213/web/share/js/kvm/keyboard.js';
import {Mouse} from '/__test/kvmd-4.213/web/share/js/kvm/mouse.js';
setRootPrefix('/');initWindowManager();
const hidEvents=[],socket={sendHidEvent:event=>hidEvents.push(structuredClone(event))};
const keyboard=new Keyboard(()=>{}),mouse=new Mouse(()=>{
    const r=document.getElementById('stream-box').getBoundingClientRect();
    return {x:r.x,y:r.y,width:r.width,height:r.height};
},()=>{});
keyboard.setSocket(socket);keyboard.setState(true,{caps:false,num:false,scroll:false},true,false);
mouse.setSocket(socket);mouse.setState(true,true,true,false);
window.addEventListener('blur',()=>{keyboard.releaseAll();mouse.releaseAll();});
const msd=new Msd();
const refresh=async()=>msd.setState((await(await fetch('/api/msd')).json()).result);
window.native4213={msd,keyboard,mouse,hidEvents,refresh};
await refresh();
const image=document.getElementById('stream-image');image.src='/__test/remote-desktop.svg';image.classList.remove('hidden');
document.getElementById('stream-window').classList.remove('hidden');
document.getElementById('stream-box').classList.remove('stream-box-offline');
document.getElementById('stream-info').textContent='MJPEG - 1600x900';
const script=document.createElement('script');script.src='/share/js/drive-folders.js';document.head.append(script);
