#!/usr/bin/env python3
"""Native-pixel gallery and comparable renderer timing; synthetic telemetry only."""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time
from functools import lru_cache
from unittest.mock import patch
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import pikvm_config as config
import pikvm_oled_ui as current
from pikvm_oled_nav import preview_navigation
from pikvm_oled import prepare_frame

SAMPLE={'percent':82,'voltage':3.94,'charging':False,'cpu':17,'ram':62,'available_mb':148,'temperature':43,'uptime':'1h 25m',
        'ip':'192.0.2.1','ssid':'Atelier réseau avec nom long','dbm':-56,'connected':True,'usb':'OK','kvm':True,'hdmi':'1920x1080',
        'drives':{'0':{'known':True,'attached':True,'cdrom':True},'1':{'known':True,'attached':False,'cdrom':False}},
        'state':'importing','current':'Linux/Exemple très long avec espaces.iso','free':8.2}
MENUS=('menu','power','wifi','network','iso-root','iso','iso-action','iso-info','iso-connect-confirm','iso-eject-confirm','power-confirm','network-confirm','working','message')


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def scenes(ui,values,baseline=False,navigation=preview_navigation):
    pages=('main','battery','system','network','usb','transfer') if baseline else config.PAGES
    result={page:(lambda page=page:ui.render_status(page,SAMPLE,values,8)) for page in pages}
    for screen in MENUS:
        def draw(screen=screen):
            with patch.dict(sys.modules,{'pikvm_oled_ui':ui}):return navigation(screen,values)
        result[screen if screen not in result else 'menu-'+screen]=draw
    qr=Image.open(ROOT/'tests/fixtures/oled-demo-qr.png').convert('1')
    result['qr']=lambda:ui.render_qr(qr,'Exemple',values)
    result['error']=lambda:ui.render_message('Erreur',['API indisponible','Réessayer plus tard'],values,'Clic : retour')
    result['notification']=lambda:ui.render_message('Batterie faible',['Brancher le chargeur','Aucun arrêt automatique'],values,'Clic : retour')
    result['idle']=lambda:ui.render_idle('screen',values)
    result['off']=lambda:ui.render_idle('off',values)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--iterations',type=int,default=100)
    parser.add_argument('--font-directory',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/images/rc121');args=parser.parse_args()
    if not 1<=args.iterations<=1000:parser.error('iterations 1..1000')
    out=args.output;out.mkdir(parents=True,exist_ok=True)
    old=load('rc12_before_ui',ROOT/'tests/fixtures/rc12-oled-ui.py')
    old_nav=load('rc12_before_navigation',ROOT/'tests/fixtures/rc12-oled-nav.py')
    if args.font_directory:
        @lru_cache(maxsize=16)
        def shared_font(size=9,bold=False):
            return ImageFont.truetype(str(args.font_directory/('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')),size)
        current.font=old.font=shared_font
    baseline=json.loads((ROOT/'tests/fixtures/rc12-settings.json').read_text(encoding='utf-8'))['values']
    manifest=[];performance={};images={}
    for profile,ui,values in [('before',old,baseline),('readable',current,{**config.defaults(),'oled_style':'readable'}),('compact',current,{**config.defaults(),'oled_style':'compact'})]:
        performance[profile]={}
        for name,draw in scenes(ui,values,profile=='before',old_nav.preview_navigation if profile=='before' else preview_navigation).items():
            frame=draw().image;assert frame.size==(128,64) and frame.mode=='1'
            # RC12 used both 1 and 255 for white. Canonicalize the historical
            # drawing for cross-Pillow documentation; new UI emits 255 itself.
            if profile=='before':
                gray=Image.new('L',(128,64));gray.putdata([255 if frame.getpixel((x,y)) else 0 for y in range(64) for x in range(128)])
                frame=gray.convert('1')
            namefile=profile+'-'+name+'.png';frame.save(out/namefile)
            manifest.append({'profile':profile,'scene':name,'file':namefile,'width':128,'height':64,'pixels_sha256':hashlib.sha256(frame.tobytes()).hexdigest()})
            images[profile,name]=frame
            samples=[]
            for _ in range(args.iterations):
                start=time.perf_counter();draw();samples.append(1000*(time.perf_counter()-start))
            performance[profile][name]={'mean_ms':round(statistics.mean(samples),3),'p95_ms':round(sorted(samples)[int(.95*(len(samples)-1))],3)}
    rows=[]
    markdown=[]
    all_names=list(dict.fromkeys(x['scene'] for x in manifest))
    for name in all_names:
        cells=[]
        for profile in ('before','readable','compact'):
            file=profile+'-'+name+'.png'
            cells.append(f'<td><img width="128" height="64" src="{file}" alt="{profile} {name}"></td>' if (profile,name) in images else '<td>Nouvelle page</td>')
        rows.append('<tr><th>'+name+'</th>'+''.join(cells)+'</tr>')
        markdown.append('| '+name+' | '+' | '.join('!['+profile+' '+name+']('+profile+'-'+name+'.png)' if (profile,name) in images else 'Nouvelle page' for profile in ('before','readable','compact'))+' |')
    html='''<!doctype html><meta charset="utf-8"><title>OLED RC12 → RC12.1</title>
<style>body{background:#11181c;color:#d4f7e6;font:15px system-ui;margin:24px}table{border-collapse:collapse}th,td{padding:12px;border:1px solid #35454a;text-align:left}img{width:128px;height:64px;image-rendering:pixelated;background:black}button{margin:12px;padding:8px}.zoom img{width:384px;height:192px}</style>
<h1>Comparaison OLED — données synthétiques</h1><p>Rendus natifs 128 × 64, à taille réelle par défaut. Le zoom ne remplace pas la validation physique.</p>
<button onclick="document.body.classList.toggle('zoom')">Taille native / zoom ×3 sans interpolation</button>
<p>QR : réseau de démonstration uniquement. Gestes et actions sensibles non exécutés.</p>
<table><thead><tr><th>Page</th><th>RC12 Compact</th><th>RC12.1 Lisible</th><th>RC12.1 Compact</th></tr></thead><tbody>'''+''.join(rows)+'</tbody></table>'
    (out/'gallery.html').write_text(html,encoding='utf-8',newline='\n')
    (out/'gallery.md').write_text('# OLED : RC12 / RC12.1 Lisible / RC12.1 Compact\n\nImages synthétiques à taille native 128 × 64. Aucune validation physique implicite.\n\n[Zoom facultatif dans la galerie HTML](gallery.html).\n\n| Page | RC12 Compact | RC12.1 Lisible | RC12.1 Compact |\n| --- | --- | --- | --- |\n'+'\n'.join(markdown)+'\n',encoding='utf-8',newline='\n')
    (out/'manifest.json').write_text(json.dumps({'synthetic':True,'physical_validation':False,'images':manifest},indent=2)+'\n',encoding='utf-8')
    report={'platform':sys.platform,'python':sys.version.split()[0],'iterations':args.iterations,'scope':'Synthetic renderer timing on this computer, same fonts for before/after; no Pi CPU measurement','profiles':performance}
    (ROOT/'docs/performance/rc121-local.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    selected=('system','system_details','main','battery','network','usb','iso','power-confirm')
    sheet=Image.new('RGB',(3*400,len(selected)*224),(18,23,28));draw=ImageDraw.Draw(sheet)
    for row,name in enumerate(selected):
        for column,profile in enumerate(('before','readable','compact')):
            x=column*400+8;y=row*224+6
            draw.text((x,y),profile+' / '+name,font=current.font(11),fill='white')
            frame=images.get((profile,name))
            if frame is not None:
                # Canonicalize 1bpp before RGB conversion (Pillow may expose 1/255
                # differently for drawing primitives, while the packed bits agree).
                rgb=Image.frombytes('1',(128,64),frame.tobytes()).convert('RGB')
                sheet.paste(rgb.resize((384,192),Image.Resampling.NEAREST),(x,y+20))
    sheet.save(out/'comparison.png')
    print('Generated',len(manifest),'native frames; gallery and comparable timing report:',out)


if __name__=='__main__':main()
