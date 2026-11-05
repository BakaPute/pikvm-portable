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
    text=unicodedata.normalize('NFC',''.join(c if unicodedata.category(c)[0]!='C' else ' ' for c in value))
    return text if len(text)<=limit else text[:limit-1]+'…'


@lru_cache(maxsize=16)
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
    ImageDraw.Draw(image).text((-box[0],-box[1]),value,font=font(size,bold),fill=255)
    return image


@lru_cache(maxsize=16)
def icon(name):
    im=Image.new('1',(9,9));d=ImageDraw.Draw(im)
    if name=='battery':
        d.rectangle((0,2,7,7),outline=255);d.line((8,4,8,5),fill=255);d.rectangle((2,4,4,5),fill=255)
    elif name=='wifi':
        d.arc((0,0,8,8),205,335,fill=255);d.arc((2,3,6,7),205,335,fill=255);d.point((4,7),fill=255)
    elif name=='usb':
        d.line([(4,8),(4,0),(2,2),(4,0),(6,2)],fill=255);d.line([(4,6),(1,4),(1,2)],fill=255);d.line([(4,5),(7,3),(7,2)],fill=255)
    elif name=='folder':d.polygon([(0,2),(3,2),(4,3),(8,3),(8,8),(0,8)],outline=255)
    elif name=='disc':d.ellipse((0,0,8,8),outline=255);d.ellipse((3,3,5,5),outline=255)
    elif name=='back':d.line([(4,1),(0,4),(4,7)],fill=255);d.line((0,4,8,4),fill=255)
    elif name=='alert':d.polygon([(4,0),(8,8),(0,8)],outline=255);d.line((4,3,4,5),fill=255);d.point((4,7),fill=255)
    elif name=='power':d.arc((0,1,8,8),-45,225,fill=255);d.line((4,0,4,4),fill=255)
    elif name=='system':d.rectangle((1,1,7,7),outline=255);d.rectangle((3,3,5,5),outline=255)
    else:d.rectangle((0,0,8,6),outline=255);d.line((4,6,4,8),fill=255);d.line((2,8,6,8),fill=255)
    return im


class Surface:
    def __init__(self,values=None,phase=0):
        self.image=Image.new('1',SIZE);self.draw=ImageDraw.Draw(self.image)
        self.values=values or {};self.phase=max(0,phase);self.animated=False
        self.text_regions=[]
        self.text_runs=[]
        self.readable=self.values.get('oled_style','readable')!='compact'

    def text(self,value,x,y,w,size=9,bold=False,scroll=False,fill=1,h=None,align='left'):
        x=max(0,int(x));y=max(0,int(y));w=max(0,min(int(w),128-x))
        value=clean(value);mask=text_mask(value,size,bold);elided=False
        height=min(64-y,mask.height if h is None else max(0,int(h)))
        minimum=min(size,10 if self.readable else 9)
        while mask.height>height and size>minimum:
            size-=1;mask=text_mask(value,size,bold)
        if w<=0 or height<=0:return
        if mask.height>height:
            # Never show half an accent/descender when a font cannot fit the row.
            value='…';mask=text_mask(value,size,bold);elided=True
            if mask.height>height:
                self.draw.line((x,y+height//2,x+min(w-1,4),y+height//2),fill=255 if fill else 0)
                self.text_regions.append((x,y,x+min(w,5),y+height));return
        animations=self.values.get('oled_animations',True) and self.values.get('animations',True)
        if mask.width>w and scroll and animations:
            self.animated=True
            content_width=max(1,w-4)
            speed=self.values.get('oled_scroll_speed',16)
            distance=mask.width-content_width
            # Pause at both ends; no split words caused by circular character rotation.
            period=2*distance/speed+2
            point=self.phase%period
            offset=0 if point<1 else min(distance,(point-1)*speed) if point<1+distance/speed else max(0,distance-(point-2-distance/speed)*speed)
            offset=distance if offset>=distance else max(0,int(offset)//2*2)
            mask=mask.crop((offset,0,offset+content_width,mask.height))
            # A fixed edge marker signals that more text is available.
            self.draw.line([(x+w-3,y+3),(x+w-1,y+5),(x+w-3,y+7)],fill=255 if fill else 0)
            elided=True
        elif mask.width>w:
            mask=text_mask(fit(value,w,size,bold),size,bold)
            elided=True
        if align=='right':x+=max(0,w-mask.width)
        elif align=='center':x+=max(0,(w-mask.width)//2)
        self.image.paste(255 if fill else 0,(x,y),mask)
        self.text_regions.append((x,y,x+min(w,mask.width),y+mask.height))
        self.text_runs.append({'text':value,'size':size,'elided':elided,'box':self.text_regions[-1]})

    def symbol(self,name,x,y,invert=False):
        mask=icon(name);self.image.paste(0 if invert else 255,(x,y),mask)

    def header(self,title,symbol='monitor',right=''):
        self.symbol(symbol,2,1)
        space=min(49,width(right,9)+4) if right else 0
        self.text(title,15,1,110-space,size=11 if self.readable else 10,bold=True,h=12)
        if right:self.text(right,128-space,3,space-2,size=9,align='right',h=10)
        self.draw.line((2,15,125,15),fill=255)

    def footer(self,help_text='',position=None):
        self.draw.line((1,52,126,52),fill=255)
        right=clean(position) if position is not None else ''
        reserve=min(48,width(right,9)+4) if right else 0
        self.text(help_text,3,54,122-reserve,size=9,h=10)
        if right:self.text(right,128-reserve,54,reserve-2,size=9,align='right',h=10)

    def metrics(self,pairs,top=19,bottom=63,value_size=None):
        """Shared column layout; measured label widths, full-height value rows."""
        if not pairs:return
        label_size=11 if self.readable else 10
        value_size=value_size or (14 if self.readable else 12)
        label_width=min(53,max(width(label,label_size) for label,_ in pairs)+3)
        pitch=(bottom-top+1)//len(pairs)
        for index,(label,value) in enumerate(pairs):
            y=top+pitch*index
            self.text(label,3,y+2,label_width,size=label_size,h=pitch-2)
            self.text(value,3+label_width+5,y,122-label_width-5,size=value_size,bold=True,align='right',h=pitch-1)

    def bar(self,x,y,w,h,value):
        x,y,w,h=int(x),int(y),int(w),int(h)
        if w<3 or h<3 or x<0 or y<0 or x+w>128 or y+h>64:raise ValueError('Jauge hors écran')
        self.draw.rectangle((x,y,x+w-1,y+h-1),outline=255)
        if type(value) in (int,float) and math.isfinite(value):
            length=int((w-4)*min(1,max(0,value)))
            if length>0:self.draw.rectangle((x+2,y+2,x+1+length,y+h-3),fill=255)
        else:self.draw.line((x+3,y+h//2,x+w-4,y+h//2),fill=255)

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
    size=12 if s.readable else 11
    if page=='main':
        s.header('PiKVM','monitor',percent(data['percent']) if values.get('oled_show_battery',True) else timer)
        address=data.get('ip') if values.get('oled_show_ip',True) else 'IP masquée'
        s.text(address or 'IP inconnue',3,20,122,size=13,bold=True,scroll=True,h=16,align=values.get('oled_alignment','left'))
        if s.readable:
            second=(data.get('ssid') or 'Wi-Fi inconnu') if values.get('oled_show_ssid',True) else 'KVM '+{True:'actif',False:'arrêté',None:'?'}.get(data.get('kvm'),'?')
            s.text(second,3,37,122,size=12,scroll=True,h=14)
        else:
            s.text('KVM '+{True:'actif',False:'arrêté',None:'?'}.get(data.get('kvm'),'?'),3,39,65,size=10,h=12)
            s.text('USB '+(data.get('usb') or '?'),72,39,53,size=10,h=12,align='right')
        if not s.readable and values.get('oled_show_ssid',True):s.footer(data.get('ssid') or 'Wi-Fi inconnu',timer)
        else:s.footer('KVM '+{True:'actif',False:'arrêté',None:'?'}.get(data.get('kvm'),'?'),timer)
    elif page=='battery':
        charge={True:'Charge',False:'Repos',None:'?'}.get(data.get('charging'),'?')
        s.header('Batterie','battery',charge)
        s.text(percent(data['percent']),3,19,122 if s.readable else 78,size=24 if s.readable else 22,bold=True,h=26,align=values.get('oled_alignment','left'))
        voltage=f"{data['voltage']:.2f} V" if data['voltage'] is not None else '-- V'
        if s.readable:
            label='Inconnue' if data['percent'] is None else 'Critique' if data['percent']<=values.get('battery_critical',10) else 'Faible' if data['percent']<=values.get('battery_low',20) else 'Estimée'
            s.text(label,3,49,65,size=11,h=13)
            if values.get('oled_show_voltage',True):s.text(voltage,72,49,53,size=11,h=13,align='right')
        else:
            if values.get('oled_show_voltage',True):s.text(voltage,82,26,43,size=10,align='right',h=12)
            s.bar(3,43,122,8,None if data['percent'] is None else data['percent']/100)
            s.footer('Mesure absente' if data['percent'] is None else 'Mesure estimée',timer)
    elif page=='system':
        s.header('Système','system',timer or '1/2')
        temperature=data['temperature']
        temp=f'{temperature:.0f} °C' if temperature is not None else '-- °C'
        if s.readable:
            pairs=[('CPU',percent(data['cpu'])),('RAM',percent(data['ram']))]
            if values.get('oled_show_temperature',True):pairs.append(('Temp.',temp))
            s.metrics(pairs)
        else:
            for index,label in enumerate(('CPU','RAM')):
                value=data[label.lower()];y=20+index*16
                s.text(label,3,y,27,size=10,h=12)
                s.bar(33,y+2,48,8,None if value is None else value/100)
                s.text(percent(value),84,y,41,size=11,bold=True,align='right',h=13)
            s.footer(temp if values.get('oled_show_temperature',True) else 'Système',timer)
    elif page=='system_details':
        s.header('Ressources','system',timer or '2/2')
        available=data['available_mb'];available=f'{available:.0f} Mio' if available is not None else '-- Mio'
        s.metrics([('Libre',available),('Durée',data.get('uptime') or '--')],top=22)
    elif page=='network':
        s.header('Réseau','wifi',timer or '1/2')
        s.text((data.get('ip') or 'IP inconnue') if values.get('oled_show_ip',True) else 'IP masquée',3,21,122,size=13,bold=True,scroll=True,h=16)
        s.text(data.get('ssid') or 'SSID inconnu',3,44,122,size=size,scroll=True,h=15)
    elif page=='network_details':
        s.header('Connexion','wifi',timer or '2/2')
        connected={True:'Lié',False:'Hors ligne',None:'Inconnu'}.get(data.get('connected'),'Inconnu')
        s.text(connected,3,22,122,size=14,bold=True,h=17)
        signal=f"{data['dbm']:.0f} dBm" if data['dbm'] is not None else '-- dBm'
        s.metrics([('Signal',signal)],top=45)
    elif page=='usb':
        s.header('USB','usb',timer)
        pairs=[]
        for index,label in ((0,'ISO'),(1,'Clé USB')):
            drive=data.get('drives',{}).get(str(index),{})
            state='Inconnu' if not drive.get('known') else 'Éjecté' if not drive.get('attached') else 'CD/DVD' if drive.get('cdrom') else 'Flash'
            pairs.append((label,state))
        # Two generous rows. Mounted-on-PC status is deliberately never inferred.
        s.metrics(pairs,top=22,bottom=51,value_size=12)
        s.footer('PC : montage inconnu')
    elif page=='transfer':
        status=data.get('state','unknown')
        labels={'ready':'Prêt','connected':'USB connecté','importing':'Import','preparing':'Préparation','starting':'Activation','stopping':'Éjection','done':'Terminé','error':'Échec','interrupted':'Interrompu','unknown':'Inconnu'}
        s.header('Transfert','alert' if status in ('error','interrupted','unknown') else 'usb',timer)
        s.text(labels.get(status,'Inconnu'),3,19,122,size=size,bold=True,h=14)
        s.bar(3,37,76,9,None if data['percent'] is None else data['percent']/100)
        s.text(percent(data['percent']),83,34,42,size=14,bold=True,align='right',h=17)
        s.text(data.get('current') or data.get('message') or 'Aucune opération',3,52,122,size=10,scroll=True,h=12)
    else:raise ValueError('Page OLED inconnue')
    return s


def render_list(title,items,index,values,help_text='',phase=0,remaining=None):
    s=Surface(values,phase);count=len(items);rows=2 if s.readable else 3
    s.header(title,'folder',f'{index+1}/{count}' if count else '0/0')
    if not count:s.text('Liste vide',3,27,122,size=12,h=16)
    else:
        index=min(count-1,max(0,index));start=min(max(0,index-1),max(0,count-rows))
        pitch=18 if s.readable else 12
        for row,item in enumerate(items[start:start+rows]):
            y=19+row*pitch if s.readable else 16+row*pitch;selected=start+row==index
            if selected:s.draw.rectangle((1,y-2 if s.readable else y,126,y+(13 if s.readable else 11)),fill=255)
            name=item.get('name','?') if isinstance(item,dict) else str(item)
            symbol=item.get('icon','disc') if isinstance(item,dict) else 'disc'
            s.symbol(symbol,3,y+1,invert=selected)
            s.text(name,16,y,107,size=12 if s.readable else 10,bold=selected,fill=not selected,scroll=selected,h=14 if s.readable else 12)
    s.footer(help_text or '1 suiv.  2 ouvrir')
    return s


def render_message(title,lines,values,help_text='',symbol='alert',progress=None,phase=0):
    s=Surface(values,phase);s.header(title,symbol)
    limit=2 if progress is not None else 4
    content=list(lines[:limit])
    if len(lines)>limit:content[-1]='… +'+str(len(lines)-limit+1)+' lignes'
    footer=progress is None and len(content)<=2
    top=20 if footer else 18;bottom=52 if footer else 47 if progress is not None else 63
    pitch=(bottom-top+1)//max(1,len(content))
    for i,line in enumerate(content):
        s.text(line,3,top+i*pitch,122,size=12 if s.readable else 11,bold=i==0,scroll=True,h=pitch-2)
    if progress is not None:s.bar(3,54,122,8,progress)
    elif footer:s.footer(help_text)
    return s


def render_qr(qr,ssid,values,phase=0):
    if qr.width!=qr.height or qr.width>56:raise ValueError('QR trop dense pour 128×64')
    factor=max(1,64//(qr.width+8))  # At least four quiet modules on every side.
    if factor>1:qr=qr.resize((qr.width*factor,qr.height*factor),Image.Resampling.NEAREST)
    s=Surface(values,phase);s.draw.rectangle((0,0,63,63),fill=255)
    s.image.paste(qr,((64-qr.width)//2,(64-qr.height)//2))
    s.text('Wi-Fi',68,3,59,size=11,bold=True,h=14)
    s.text('Scanner',68,22,59,size=10,h=13)
    s.text(ssid,68,38,59,size=11,scroll=True,h=13)
    s.text('Retour',68,54,59,size=9,h=10)
    return s


def render_idle(mode,values):
    s=Surface(values)
    if mode!='off':
        s.header('PiKVM','monitor');s.text('Inactif',3,25,122,size=18,bold=True,align='center',h=23)
        s.footer('Appui : réveiller')
    return s
