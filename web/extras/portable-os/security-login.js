const form=document.querySelector('form'),message=document.querySelector('[role=alert]');
let portableEntry=false;
form.querySelector('button').disabled=true;
fetch('/api/portable-entry',{credentials:'same-origin',cache:'no-store',redirect:'error'}).then(async response=>{
    if(!response.ok)throw Error('wrong entry');
    const data=await response.json();if(data.result?.kind!=='portable-permissions-gateway'||data.result.native!==false)throw Error('wrong entry');
    portableEntry=true;form.querySelector('button').disabled=false;
}).catch(()=>{message.textContent='Cette page ne répond pas depuis la passerelle Portable. Utilisez son origine HTTPS dédiée, indiquée par votre administrateur ; aucun mot de passe n’a été envoyé.';});
form.addEventListener('submit',async event=>{
    event.preventDefault();const submit=form.querySelector('button');submit.disabled=true;message.textContent='';
    if(!portableEntry){message.textContent='Entrée Portable non vérifiée ; connexion refusée.';return;}
    try{
        const data=Object.fromEntries(new FormData(form));
        const response=await fetch('/api/auth/login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
        form.elements.passwd.value='';
        if(!response.ok){
            let error;try{error=(await response.json()).error;}catch{}
            throw Error(response.status===401?'Identifiant ou mot de passe Portable incorrect. Les comptes KVMD utilisent l’accès administrateur distinct.':error||'Entrée Portable indisponible ; vérifiez la passerelle auprès de votre administrateur.');
        }
        location.assign('/extras/portable-os/');
    }catch(error){message.textContent=error instanceof TypeError?'Connexion au portail impossible. Vérifiez le réseau et la passerelle ; ne désactivez pas la vérification HTTPS.':error.message;}finally{submit.disabled=false;}
});
