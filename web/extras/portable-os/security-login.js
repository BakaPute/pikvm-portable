const form=document.querySelector('form'),message=document.querySelector('[role=alert]');
form.addEventListener('submit',async event=>{
    event.preventDefault();const submit=form.querySelector('button');submit.disabled=true;message.textContent='';
    try{
        const data=Object.fromEntries(new FormData(form));
        const response=await fetch('/api/auth/login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
        form.elements.passwd.value='';
        if(!response.ok)throw Error((await response.json()).error||'Connexion refusée.');
        location.assign('/extras/portable-os/');
    }catch(error){message.textContent=error.message;}finally{submit.disabled=false;}
});
