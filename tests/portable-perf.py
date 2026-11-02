"""Deterministic local OLED workload. No I2C/GPIO, commands or live API access."""
import argparse
import importlib.machinery
import importlib.util
import inspect
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
from unittest.mock import patch

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import pikvm_oled as oled


def load_api():
    loader=importlib.machinery.SourceFileLoader('perf_api',str(ROOT/'scripts/pikvm-portable-api'))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    api=importlib.util.module_from_spec(spec);loader.exec_module(api)
    return api


def workload(changing, count=600):
    now=[0.0]; writes=[]; sent=[]; sizes=[]
    class Driver:
        def display(self,image):sent.append(1)
    with tempfile.TemporaryDirectory() as directory:
        device=oled.MirrorDevice('status',path=Path(directory)/'oled/frame.json',
            factory=Driver,clock=lambda:now[0],background=False)
        backend=load_api().SystemBackend()
        conditional='pixels_id' in inspect.signature(backend.oled).parameters
        reader=oled.read_frame;replace=oled.os.replace;last_pixels=None
        started=time.process_time(); wall=time.perf_counter()
        with patch.object(oled.os,'replace',side_effect=lambda a,b:(writes.append(1),replace(a,b))[1]):
            for i in range(count):
                now[0]=100+i*.05
                second=i//20 if changing else 0
                image=Image.new('1',(128,64))
                ImageDraw.Draw(image).text((0,0),'Counter '+str(second),fill=1)
                device.set_context(screen='status',remaining=30-second)
                device.display(image);device.output._attempt()
                # Five authenticated-frame-equivalent serializations / virtual sec.
                # Authentication and actual networking are intentionally not measured.
                if i%4==0:
                    with patch.object(oled,'read_frame',side_effect=lambda:reader(device.path,clock=lambda:now[0])):
                        data=backend.oled(pixels_id=last_pixels) if conditional else backend.oled()
                    last_pixels=data.get('pixel_id')
                    sizes.append(len(json.dumps({'ok':True,'result':data},separators=(',',':')).encode()))
        result={'cpu_ms':round((time.process_time()-started)*1000,3),
            'wall_ms':round((time.perf_counter()-wall)*1000,3),'frames_offered':count,
            'frame_replacements':len(writes),'physical_driver_calls':len(sent),
            'response_bytes':sum(sizes),'responses':len(sizes)}
        device.close()
        return result


def status_workload(source):
    loader=importlib.machinery.SourceFileLoader('perf_status',str(source))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    status=importlib.util.module_from_spec(spec);loader.exec_module(status)
    values={'battery':(82,3.95),'battery_charging':False,'wifi':('fixture',-50),'ip_address':'192.0.2.1',
            'usb_state':'configured','hdmi_state':'yes','cpu_temp':42,'cpu_usage':5,
            'transfer_info':{},'msd_free_space':4,'uptime':'10m'}
    for name,value in values.items():setattr(status,name,lambda value=value:value)
    class Cache:
        revision=0
        def wrap(self,reader,*args,**kwargs):return reader
    class Finished(Exception):pass
    ticks=[0];now=[100.0];draws=[0]
    def sleep(delay):
        ticks[0]+=1;now[0]=100+ticks[0]*.1
        if ticks[0]>=600:raise Finished()
    with tempfile.TemporaryDirectory() as directory:
        device=oled.MirrorDevice('status',path=Path(directory)/'oled/frame.json',
            factory=lambda:None,clock=lambda:now[0],background=False)
        display=device.display
        def counted(image):draws[0]+=1;display(image)
        device.display=counted
        start=time.process_time()
        with patch.object(status,'AsyncCache',Cache),patch.object(status,'MirrorDevice',return_value=device), \
             patch.object(status.time,'monotonic',side_effect=lambda:now[0]),patch.object(status.time,'sleep',side_effect=sleep):
            try:status.main()
            except Finished:pass
        cpu=(time.process_time()-start)*1000;device.close()
    return {'pillow_draws':draws[0],'virtual_seconds':60,'cpu_ms':round(cpu,3)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--label',required=True)
    parser.add_argument('--status-source',type=Path,default=ROOT/'scripts/pikvm-oled-custom')
    args=parser.parse_args()
    data={'label':args.label,'environment':{'platform':platform.platform(),'python':platform.python_version()},
          'note':'Local simulated 30s workload, 600 draws, fake I2C. CPU is Windows process CPU, not Pi CPU.',
          'scenarios':{}}
    for name,changing in [('static',False),('countdown-1Hz',True)]:
        runs=[workload(changing) for _ in range(5)]
        data['scenarios'][name]={key:statistics.median(run[key] for run in runs) for key in runs[0]}
        data['scenarios'][name]['runs']=runs
    runs=[status_workload(args.status_source) for _ in range(5)]
    data['native_status']={key:statistics.median(run[key] for run in runs) for key in runs[0]}
    data['native_status']['note']='Only status producer source varies; RC7 mirror used in both native-render comparisons.'
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(data['scenarios'],indent=2))
