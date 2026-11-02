// Input transport owns its lease independently of images and renderer health.
export class OledInput {
    constructor(send, changed, {clock=()=>performance.now(), timer=(fn,delay)=>setTimeout(fn,delay), clear=id=>clearTimeout(id),
        nonce=()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join('')}={}) {
        Object.assign(this,{send,changed,clock,timer,clear,nonce}); this.active=null;
        this.metrics={last_keep_ms:0,max_keep_ms:0};
    }
    start(control_id,permit='') {
        if(this.active)return;
        const gesture={id:this.nonce(),control:control_id,permit,beat:null};this.active=gesture;
        this.changed('holding');
        this.send({action:'start',gesture_id:gesture.id,control_id,permit}).then(()=>{
            if(this.active===gesture)this.keep(gesture);
        }).catch(error=>{if(this.active===gesture){this.end(true);this.changed('error',error.message);}});
    }
    async keep(gesture) {
        if(this.active!==gesture)return;
        const began=this.clock();
        try {await this.send({action:'keep',gesture_id:gesture.id});}
        catch(error){if(this.active===gesture){this.end(true);this.changed('error','Maintien annulé : '+error.message);}return;}
        const elapsed=this.clock()-began;
        this.metrics.last_keep_ms=elapsed;this.metrics.max_keep_ms=Math.max(this.metrics.max_keep_ms,elapsed);
        // Fixed cadence without overlapping requests or adding response latency
        // to every interval. The server's 800 ms deadline is never extended here.
        if(this.active===gesture)gesture.beat=this.timer(()=>this.keep(gesture),Math.max(0,200-elapsed));
    }
    end(cancel=false) {
        const gesture=this.active;if(!gesture)return;
        this.active=null;this.clear(gesture.beat);this.changed(cancel?'cancelled':'released');
        this.send({action:cancel?'cancel':'stop',gesture_id:gesture.id})
            .catch(error=>this.changed('error','Relâchement non confirmé : '+error.message));
    }
}
