"""Shared, bounded 128x64 monochrome components. No telemetry/GPIO/device calls.

Native pages, menus and web previews all render through this module. Fonts and
small icons are cached. Animation is a quantized, clipped text crop, never a
permanent redraw of unchanged frames.
"""
from functools import lru_cache
import math
from pathlib import Path
import unicodedata
from PIL import Image, ImageDraw, ImageFont

SIZE=(128,64)


def clean(value,limit=256):
    value='--' if value is None else str(value)
    text=''.join(c if unicodedata.category(c)[0]!='C' else ' ' for c in value)
    return text if len(text)<=limit else text[:limit-1]+'…'


@lru_cache(maxsize=8)
def font(size=9,bold=False):
    name='DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    for directory in ('/usr/share/fonts/TTF','/usr/share/fonts/truetype/dejavu'):
        path=Path(directory)/name
        if path.is_file():
            try:return ImageFont.truetype(str(path),size)
            except OSError:pass
    # Pillow's bundled scalable font is also available in offline/headless tests.
    return ImageFont.load_default(size=size)


@lru_cache(maxsize=1024)
def bounds(value,size=9,bold=False):return font(size,bold).getbbox(value,mode='1')


def width(value,size=9,bold=False):
    box=bounds(clean(value),size,bold);return max(0,box[2]-box[0])


def fit(value,pixels,size=9,bold=False):
    text=clean(value)
    if width(text,size,bold)<=pixels:return text
    suffix='…'
    if width(suffix,size,bold)>pixels:return ''
    low,high=0,len(text)
    while low<high:
        middle=(low+high+1)//2
        if width(text[:middle]+suffix,size,bold)<=pixels:low=middle
        else:high=middle-1
    return text[:low]+suffix


@lru_cache(maxsize=64)
def text_mask(value,size=9,bold=False):
    value=clean(value);box=bounds(value,size,bold)
    # Input is bounded and very long names are elided before allocating a strip.
    if box[2]-box[0]>2048:value=fit(value,2048,size,bold);box=bounds(value,size,bold)
    image=Image.new('1',(max(1,box[2]-box[0]),max(1,box[3]-box[1])))
    ImageDraw.Draw(image).text((-box[0],-box[1]),value,font=font(size,bold),fill=1)
    return image


@lru_cache(maxsize=16)
def icon(name):
    im=Image.new('1',(9,9));d=ImageDraw.Draw(im)
    if name=='battery':
        d.rectangle((0,2,7,7),outline=1);d.line((8,4,8,5),fill=1);d.rectangle((2,4,4,5),fill=1)
    elif name=='wifi':
        d.arc((0,0,8,8),205,335,fill=1);d.arc((2,3,6,7),205,335,fill=1);d.point((4,7),fill=1)
    elif name=='usb':
        d.line([(4,8),(4,0),(2,2),(4,0),(6,2)],fill=1);d.line([(4,6),(1,4),(1,2)],fill=1);d.line([(4,5),(7,3),(7,2)],fill=1)
    elif name=='folder':d.polygon([(0,2),(3,2),(4,3),(8,3),(8,8),(0,8)],outline=1)
    elif name=='disc':d.ellipse((0,0,8,8),outline=1);d.ellipse((3,3,5,5),outline=1)
    elif name=='back':d.line([(4,1),(0,4),(4,7)],fill=1);d.line((0,4,8,4),fill=1)
    elif name=='alert':d.polygon([(4,0),(8,8),(0,8)],outline=1);d.line((4,3,4,5),fill=1);d.point((4,7),fill=1)
    elif name=='power':d.arc((0,1,8,8),-45,225,fill=1);d.line((4,0,4,4),fill=1)
    elif name=='system':d.rectangle((1,1,7,7),outline=1);d.rectangle((3,3,5,5),outline=1)
    else:d.rectangle((0,0,8,6),outline=1);d.line((4,6,4,8),fill=1);d.line((2,8,6,8),fill=1)
    return im


class Surface:
    def __init__(self,values=None,phase=0):
        self.image=Image.new('1',SIZE);self.draw=ImageDraw.Draw(self.image)
        self.values=values or {};self.phase=max(0,phase);self.animated=False
        self.text_regions=[]

    def text(self,value,x,y,w,size=9,bold=False,scroll=False,fill=1,h=None,align='left'):
        x=max(0,int(x));y=max(0,int(y));w=max(0,min(int(w),128-x))
        value=clean(value);mask=text_mask(value,size,bold)
        height=min(64-y,mask.height if h is None else max(0,int(h)))
        while mask.height>height and size>7:
            size-=1;mask=text_mask(value,size,bold)
        if w<=0 or height<=0:return
        animations=self.values.get('oled_animations',True) and self.values.get('animations',True)
        if mask.width>w and scroll and animations:
            self.animated=True
            speed=self.values.get('oled_scroll_speed',16)
            distance=mask.width-w
            # Pause at both ends; no split words caused by circular character rotation.
            period=2*distance/speed+2
            point=self.phase%period
            offset=0 if point<1 else min(distance,(point-1)*speed) if point<1+distance/speed else max(0,distance-(point-2-distance/speed)*speed)
            offset=distance if offset>=distance else max(0,int(offset)//2*2)
            mask=mask.crop((offset,0,offset+w,height))
        elif mask.width>w:
            mask=text_mask(fit(value,w,size,bold),size,bold)
        if align=='right':x+=max(0,w-mask.width)
        elif align=='center':x+=max(0,(w-mask.width)//2)
        if mask.height>height:mask=mask.crop((0,0,mask.width,height))
        self.image.paste(1 if fill else 0,(x,y),mask)
        self.text_regions.append((x,y,x+min(w,mask.width),y+height))

    def symbol(self,name,x,y,invert=False):
        mask=icon(name);self.image.paste(0 if invert else 1,(x,y),mask)

    def header(self,title,symbol='monitor',right=''):
        self.symbol(symbol,2,1)
        space=min(49,width(right,8)+3) if right else 0
        self.text(title,15,1,110-space,size=9,bold=True,h=10)
        if right:self.text(right,128-space,2,space-2,size=8,align='right',h=9)
        self.draw.line((1,13,126,13),fill=1)

    def footer(self,help_text='',position=None):
        self.draw.line((1,54,126,54),fill=1)
        right=clean(position) if position is not None else ''
        reserve=min(39,width(right,8)+4) if right else 0
        self.text(help_text,2,55,124-reserve,size=8,h=9)
        if right:self.text(right,128-reserve,55,reserve-2,size=8,align='right',h=9)

    def bar(self,x,y,w,h,value):
        x,y,w,h=int(x),int(y),int(w),int(h)
        if w<3 or h<3 or x<0 or y<0 or x+w>128 or y+h>64:raise ValueError('Jauge hors écran')
        self.draw.rectangle((x,y,x+w-1,y+h-1),outline=1)
        if type(value) in (int,float) and math.isfinite(value):
            length=int((w-4)*min(1,max(0,value)))
            if length>0:self.draw.rectangle((x+2,y+2,x+1+length,y+h-3),fill=1)
        else:self.draw.line((x+3,y+h//2,x+w-4,y+h//2),fill=1)

    def row(self,label,value,y,symbol=None):
        x=2
        if symbol:self.symbol(symbol,x,y);x+=12
        self.text(label,x,y,41-x,size=8)
        self.text(value,43,y,83,size=9,scroll=True)


def number(value):return value if type(value) in (int,float) and math.isfinite(value) else None


def percent(value):return '--' if number(value) is None else f'{max(0,min(100,value)):.0f}%'


def render_status(page,data,values,remaining=None,phase=0):
    data={**data,**{key:number(data.get(key)) for key in ('percent','voltage','cpu','ram','temperature','dbm','free','available_mb')}}
    s=Surface(values,phase);timer=f'{remaining}s' if remaining is not None else ''
    compact=values.get('oled_style','compact')=='compact'
    if page=='main':
        s.header('PiKVM','monitor',percent(data.get('percent')) if values.get('oled_show_battery',True) else timer)
        address=data.get('ip') if values.get('oled_show_ip',True) else 'IP masquée'
        s.text(address or 'IP inconnue',3,18,122,size=11 if compact else 12,bold=True,align=values.get('oled_alignment','left'))
        state={True:'actif',False:'arrêté',None:'?'}.get(data.get('kvm'),'?')
        s.text('KVM '+state,3,35,61,size=8)
        s.text('USB '+(data.get('usb') or '?'),66,35,60,size=8)
        if compact and values.get('oled_show_ssid',True):s.text(data.get('ssid') or 'Wi-Fi non observé',3,44,122,size=8,scroll=True,h=9)
        elif not compact:s.text('HDMI '+(data.get('hdmi') or '?'),3,44,122,size=8,h=9)
        s.footer('Pi Zero 2 W',timer)
    elif page=='battery':
        charge=data.get('charging');p=data.get('percent');voltage=data.get('voltage')
        s.header('Batterie','battery',{True:'Charge',False:'Repos',None:'État ?'}[charge])
        s.text(percent(p),3,17,77,size=21,bold=True,h=22,align=values.get('oled_alignment','left'))
        if values.get('oled_show_voltage',True):s.text(f'{voltage:.2f} V' if voltage is not None else '-- V',81,23,45,size=9,align='right')
        s.bar(3,43,122,8,None if p is None else p/100)
        label='Mesure indisponible' if p is None else 'CRITIQUE' if p<=values.get('battery_critical',10) else 'Batterie faible' if p<=values.get('battery_low',20) else 'Niveau estimé'
        s.footer(label,timer)
    elif page=='system':
        s.header('Système','system',timer)
        cpu=data.get('cpu');ram=data.get('ram')
        s.text('CPU',3,18,26,size=8);s.bar(31,18,61,8,None if cpu is None else cpu/100);s.text(percent(cpu),94,18,32,size=8,align='right')
        s.text('RAM',3,31,26,size=8);s.bar(31,31,61,8,None if ram is None else ram/100);s.text(percent(ram),94,31,32,size=8,align='right')
        temperature=data.get('temperature')
        if values.get('oled_show_temperature',True):s.text(f'{temperature:.0f} °C' if temperature is not None else 'Temp. ?',3,44,49,size=9)
        s.text(data.get('uptime') or 'Durée ?',54,44,72,size=9,align='right')
        s.footer('RAM disponible',f"{data['available_mb']} Mio" if data.get('available_mb') is not None else '?')
    elif page=='network':
        connected=data.get('connected')
        s.header('Réseau','wifi',{True:'Lié',False:'Hors ligne',None:'?'}[connected])
        s.text(data.get('ip') if values.get('oled_show_ip',True) else 'IP masquée',3,18,122,size=11,bold=True)
        s.text(data.get('ssid') or 'SSID indisponible',3,34,122,size=9,scroll=True)
        dbm=data.get('dbm')
        if dbm is not None:
            for i in range(5):
                x=4+i*6;h=2+i*2
                s.draw.rectangle((x,51-h,x+3,51),outline=1,fill=1 if dbm>=-90+i*10 else 0)
        s.text(f'{dbm} dBm' if dbm is not None else 'Signal inconnu',40,45,86,size=8,align='right')
        s.footer('Connexion observée',timer)
    elif page=='usb':
        s.header('USB & lecteurs','usb',timer)
        for i in (0,1):
            drive=data.get('drives',{}).get(str(i),{})
            text='Inconnu' if not drive.get('known') else 'Sans média' if not drive.get('attached') else 'CD/DVD' if drive.get('cdrom') else 'Flash attaché'
            s.row('ISO 0' if i==0 else 'USB 1',text,18+i*13,'disc' if i==0 else 'usb')
        s.text('Gadget : '+(data.get('usb') or '?'),3,44,122,size=8)
        s.footer('Montage PC non observable')
    elif page=='transfer':
        status=data.get('state','unknown')
        labels={'ready':'Prêt','connected':'Attaché au PC','importing':'Import en cours','preparing':'Préparation','starting':'Activation','stopping':'Éjection','done':'Terminé','error':'Échec','interrupted':'Interrompu','unknown':'État inconnu'}
        s.header('Transfert','alert' if status in ('error','interrupted','unknown') else 'usb',timer)
        s.text(labels.get(status,'État inconnu'),3,18,122,size=10,bold=True)
        s.text(data.get('current') or data.get('message') or 'Aucune opération',3,32,122,size=8,scroll=True)
        p=data.get('percent')
        s.bar(3,44,85,8,None if p is None else p/100)
        s.text(percent(p),92,44,34,size=8,align='right')
        s.footer('Progression observée',f"{data['free']:.1f} Gio" if data.get('free') is not None else None)
    else:raise ValueError('Page OLED inconnue')
    return s


def render_list(title,items,index,values,help_text='',phase=0,remaining=None):
    s=Surface(values,phase);count=len(items)
    s.header(title,'folder',f'{index+1}/{count}' if count else '0/0')
    if not count:s.text('Liste indisponible',3,26,122,size=10)
    else:
        index=min(count-1,max(0,index));start=min(max(0,index-1),max(0,count-3))
        for row,item in enumerate(items[start:start+3]):
            y=16+row*12;selected=start+row==index
            if selected:s.draw.rectangle((1,y-1,126,y+9),fill=1)
            name=item.get('name','?') if isinstance(item,dict) else str(item)
            symbol=item.get('icon','disc') if isinstance(item,dict) else 'disc'
            s.symbol(symbol,3,y,invert=selected)
            s.text(name,16,y,107,size=9,bold=selected,fill=not selected,scroll=selected,h=10)
    s.footer(help_text,f'{remaining}s' if remaining is not None else None)
    return s


def render_message(title,lines,values,help_text='',symbol='alert',progress=None,phase=0):
    s=Surface(values,phase);s.header(title,symbol)
    for i,line in enumerate(lines[:2 if progress is not None else 3]):s.text(line,3,18+i*12,122,size=9,bold=i==0,scroll=True,h=10)
    if progress is not None:s.bar(3,44,122,8,progress)
    s.footer(help_text)
    return s


def render_qr(qr,ssid,values,phase=0):
    if qr.width!=qr.height or qr.width>56:raise ValueError('QR trop dense pour 128×64')
    factor=max(1,56//qr.width)
    if factor>1:qr=qr.resize((qr.width*factor,qr.height*factor),Image.Resampling.NEAREST)
    s=Surface(values,phase);s.draw.rectangle((0,0,63,63),fill=1)
    s.image.paste(qr,((64-qr.width)//2,(64-qr.height)//2))
    s.symbol('wifi',68,2);s.text('Wi-Fi',80,2,46,size=9,bold=True)
    s.text('Scanner',68,18,58,size=8)
    s.text(ssid,68,30,58,size=9,scroll=True)
    s.symbol('back',68,51);s.text('Retour',81,51,45,size=8)
    return s


def render_idle(mode,values):
    s=Surface(values)
    if mode!='off':
        s.header('PiKVM','monitor');s.text('Inactif',3,24,122,size=18,bold=True,align='center')
        s.footer('Appui : réveiller')
    return s
