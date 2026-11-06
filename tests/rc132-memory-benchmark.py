"""Isolated renderer memory experiment. PC results are NOT Pi service savings."""
import argparse,gc,hashlib,importlib.util,json,os,statistics,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def worker(source):
    sys.path.insert(0,str(ROOT/'scripts'))
    spec=importlib.util.spec_from_file_location('pikvm_oled_ui',source);ui=importlib.util.module_from_spec(spec);sys.modules['pikvm_oled_ui']=ui;spec.loader.exec_module(ui)
    from pikvm_config import defaults,PAGES
    from pikvm_oled_nav import preview_navigation
    from test_oled_rc12 import SAMPLE
    try:
        import psutil
        process=psutil.Process()
        def memory():
            value=process.memory_full_info();return {k:getattr(value,k,None) for k in ('rss','uss','pss')}
    except ImportError:
        def memory():
            data={line.split(':')[0]:int(line.split(':')[1].split()[0])*1024 for line in Path('/proc/self/smaps_rollup').read_text().splitlines() if line.split(':')[0] in ('Rss','Pss','Private_Clean','Private_Dirty')}
            return {'rss':data.get('Rss'),'pss':data.get('Pss'),'uss':data.get('Private_Clean',0)+data.get('Private_Dirty',0)}
    hashes=[];timings=[]
    for _ in range(10):
        for style in ('readable','compact'):
            values={**defaults(),'oled_style':style}
            for page in PAGES:
                at=time.perf_counter();frame=ui.render_status(page,SAMPLE,values,10);timings.append((time.perf_counter()-at)*1000);hashes.append(frame.image.tobytes())
            for menu in ('menu','iso','iso-action','iso-info','power-confirm'):hashes.append(preview_navigation(menu,values).image.tobytes())
    gc.collect();result=memory()
    result.update(pixel_sha256=hashlib.sha256(b''.join(hashes)).hexdigest(),render_mean_ms=statistics.mean(timings),font_keys=ui.font.cache_info().currsize)
    print(json.dumps(result))

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--worker',type=Path);parser.add_argument('--output',type=Path,default=ROOT/'private/rc132-render-memory.json');parser.add_argument('--repeats',type=int,default=7);args=parser.parse_args()
    if args.worker:return worker(args.worker)
    # Same relative location depth as scripts/, so both resolve assets/fonts.
    baseline=ROOT/'private/rc132-ui-baseline.py';baseline.parent.mkdir(exist_ok=True)
    baseline.write_bytes(subprocess.check_output(['git','show','6815e73:scripts/pikvm_oled_ui.py'],cwd=ROOT))
    results={}
    for label,source in [('baseline',baseline),('candidate',ROOT/'scripts/pikvm_oled_ui.py')]:
        results[label]=[json.loads(subprocess.check_output([sys.executable,'-B',__file__,'--worker',str(source)],cwd=ROOT,text=True)) for _ in range(args.repeats)]
    assert len({value['pixel_sha256'] for values in results.values() for value in values})==1,'Renderer pixels changed'
    medians={label:{key:statistics.median(row[key] for row in values) if all(row[key] is not None for row in values) else None for key in ('rss','uss','pss','render_mean_ms')} for label,values in results.items()}
    report={'scope':'Isolated synthetic renderer on '+sys.platform+'; no Pi deployment, no global service gain claimed','repeats':args.repeats,'medians':medians,'uss_saved_bytes':medians['baseline']['uss']-medians['candidate']['uss'],'pixel_identity':True,'samples':results}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k!='samples'},indent=2))
if __name__=='__main__':main()
