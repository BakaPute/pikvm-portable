#!/usr/bin/env python3
"""Native renderer benchmark on synthetic data. No I2C/GPIO/API/device access."""
import argparse
import json
import platform
from pathlib import Path
import statistics
import sys
import time
here=Path(__file__).resolve().parent
# A staged candidate must measure its own renderer, even while RC11 is installed.
sys.path.insert(0,str(here) if (here/'pikvm_config.py').is_file() else '/usr/local/lib/pikvm-portable')
from pikvm_config import defaults,PAGES
from pikvm_oled_ui import render_status,font
from pikvm_oled_nav import preview_navigation

SAMPLE={'percent':82,'voltage':3.94,'charging':False,'cpu':17,'ram':62,'available_mb':148,'temperature':43,'uptime':'1h 25m',
        'ip':'192.0.2.1','ssid':'Atelier / reseau avec nom long','dbm':-56,'connected':True,'usb':'OK','kvm':True,'hdmi':'1920x1080',
        'drives':{'0':{'known':True,'attached':True,'cdrom':True},'1':{'known':True,'attached':False,'cdrom':False}},
        'state':'importing','percent':82,'current':'Linux/Exemple avec espaces.iso','free':8.2}


def run(iterations):
    values=defaults();scenes={p:(lambda p=p:render_status(p,SAMPLE,values,10)) for p in PAGES}
    scenes.update({p:(lambda p=p:preview_navigation(p,values)) for p in ('menu','iso','iso-action','iso-info','iso-eject-confirm','power-confirm')})
    report={};images={}
    for name,draw in scenes.items():
        images[name]=draw().image;times=[]
        for _ in range(iterations):
            at=time.perf_counter();surface=draw();times.append((time.perf_counter()-at)*1000)
            assert surface.image.mode=='1' and surface.image.size==(128,64)
        report[name]={'mean_ms':round(statistics.mean(times),3),'p95_ms':round(sorted(times)[int(.95*(len(times)-1))],3)}
    return {'platform':platform.platform(),'python':platform.python_version(),'iterations':iterations,'scope':'Synthetic native rendering only; not electrical input or browser latency','scenes':report},images


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--iterations',type=int,default=100)
    parser.add_argument('--report',type=Path);parser.add_argument('--contact-sheet',type=Path);args=parser.parse_args()
    if not 1<=args.iterations<=1000:parser.error('iterations: 1..1000')
    report,images=run(args.iterations);encoded=json.dumps(report,indent=2,ensure_ascii=False)+'\n'
    if args.report:args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(encoded,encoding='utf-8',newline='\n')
    if args.contact_sheet:
        from PIL import Image,ImageDraw
        sheet=Image.new('RGB',(3*400,4*224),(18,23,28));draw=ImageDraw.Draw(sheet)
        for i,(name,img) in enumerate(images.items()):
            x=i%3*400+8;y=i//3*224+8
            draw.text((x,y),name,font=font(12,True),fill=(212,247,230))
            screen=Image.new('RGB',(128,64));screen.putdata([(212,247,230) if img.getpixel((x,y)) else (5,10,9) for y in range(64) for x in range(128)])
            sheet.paste(screen.resize((384,192),Image.Resampling.NEAREST),(x,y+20))
        args.contact_sheet.parent.mkdir(parents=True,exist_ok=True);sheet.save(args.contact_sheet)
    print(encoded,end='')


if __name__=='__main__':main()
