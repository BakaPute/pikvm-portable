"""Repeatable synthetic 128x64 captures; no GPIO, I2C or live API."""
from pathlib import Path
import argparse
import sys
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import pikvm_oled_ui as ui
from pikvm_config import defaults

def generate(directory):
    directory.mkdir(parents=True,exist_ok=True)
    sheet=Image.new('RGB',(800,666),'#12171c');draw=ImageDraw.Draw(sheet);scenes=[]
    for style in ('readable','compact'):
        values={**defaults(),'oled_style':style}
        for page,data in [('battery',{'percent':78,'voltage':4.02,'charging':False}),
                          ('system_details',{'ram':78,'available_mb':84,'total_mb':389,'uptime':'1h 25m'})]:
            scenes.append((style+' / '+page,ui.render_status(page,data,values,10).image))
        frame=ui.Surface(values);frame.header('Accents','system','10s')
        frame.text('é è ê ë à â ù û ç',2,21,124,size=11,h=15)
        frame.text('ï ô É È À Ç',2,42,124,size=11,h=16)
        scenes.append((style+' / accents',frame.image))
    for index,(name,image) in enumerate(scenes):
        x=index//3*400;y=index%3*222
        draw.text((x+8,y+2),name,font=ui.font(12),fill='#d4f7e6')
        image.save(directory/(name.replace(' / ','-')+'.png'))
        rgb=Image.new('RGB',(128,64));rgb.putdata([(212,247,230) if image.getpixel((px,py)) else (5,10,9) for py in range(64) for px in range(128)])
        sheet.paste(rgb.resize((384,192),Image.Resampling.NEAREST),(x+8,y+24))
    sheet.save(directory/'comparison.png')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=ROOT/'docs/images/rc131')
    generate(parser.parse_args().output)
