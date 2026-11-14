from dataclasses import dataclass, field
from collections import defaultdict
from pathlib import Path, PureWindowsPath
import re
import numpy as np
from engine import parse_input, fit_curve

PLACEHOLDER = '双击输入'

def zmx_name(text):
    match=re.search(r'^\s*(?:文件|file)\s*[:：]\s*(.*?)\.zmx[\s\"\u0027]*$',text,re.I|re.M)
    return PureWindowsPath(match.group(1).strip().strip('\"\u0027')).name if match else ''

def decode_text(blob):
    encodings=('utf-16',) if blob.startswith((b'\xff\xfe',b'\xfe\xff')) else ('utf-8-sig','gb18030')
    for encoding in encodings:
        try:return blob.decode(encoding)
        except UnicodeError:pass
    return ''


def distance_or_placeholder(name):
    """Explicit working distances keep their text; anything else invites a click-to-edit label."""
    name = name.strip()
    return name if re.fullmatch(r'\d+(?:\.\d+)?\s*(?:mm|毫米)', name, re.I) else PLACEHOLDER


def distortion_grade(value):
    if value <= .5:
        return 'green', '较好', '#087647', '#e8f5ed'
    if value <= 1:
        return 'yellow', '需关注', '#9b6800', '#fff3ce'
    return 'red', '超过 1%', '#bc302b', '#ffedeb'


def turning_grade(value):
    if value<=1:return 'green','较好','#087647','#e8f5ed'
    if value<=2:return 'yellow','需关注','#9b6800','#fff3ce'
    return 'red','超过 2 个','#bc302b','#ffedeb'


def fit_grade(value):
    """Relative max residual in percent: max |fit-data| divided by max |distortion|."""
    if value is None:return 'green','较好','#087647','#e8f5ed'
    if value<=5:return 'green','较好','#087647','#e8f5ed'
    if value<=10:return 'yellow','需关注','#9b6800','#fff3ce'
    return 'red','较差','#bc302b','#ffedeb'


def distance_name(filename, text=''):
    # Only explicit working-distance metadata or an mm-labelled filename is used.
    m = re.search(r'(?:工作距离|working\s*distance)\s*[:：=]?\s*('+r'\d+(?:\.\d+)?'+r')\s*(?:mm|毫米)?',text,re.I)
    if m: return m.group(1)+' mm'
    m = re.search(r'(?<!\d)(\d+(?:\.\d+)?)\s*(?:mm|毫米)',filename,re.I)
    return m.group(1)+' mm' if m else Path(filename).stem


def turning_points(curve):
    """Directional reversals, not mathematical second-derivative inflections.

    Ignore reversals whose amplitude is under 0.5% of the curve's full D range.
    Duplicate radii are averaged for shape recognition, never for fitting.
    """
    first=np.asarray(curve.first,dtype=float)
    q=np.abs(np.tan(np.deg2rad(first)))
    r=q/max(q) if max(q)>0 else q
    values=np.asarray(curve.raw,dtype=float)*(1 if curve.unit=='percent' else 100)
    pairs={}
    for a,b in zip(r,values):pairs.setdefault(round(float(a),10),[]).append(float(b))
    points=sorted((a,float(np.mean(b))) for a,b in pairs.items())
    ys=[b for a,b in points];tol=max((max(ys)-min(ys))*.005,1e-8)
    direction=0;index=0;extreme=ys[0];found=[]
    for i,y in enumerate(ys[1:],1):
        if direction==0:
            if y-extreme>=tol:direction=1;index=i;extreme=y
            elif extreme-y>=tol:direction=-1;index=i;extreme=y
        elif direction==1:
            if y>=extreme:index=i;extreme=y
            elif extreme-y>=tol:
                found.append({'rho':points[index][0],'distortion':extreme,'kind':'峰'})
                direction=-1;index=i;extreme=y
        else:
            if y<=extreme:index=i;extreme=y
            elif y-extreme>=tol:
                found.append({'rho':points[index][0],'distortion':extreme,'kind':'谷'})
                direction=1;index=i;extreme=y
    return {'count':len(found),'points':found,'tolerance':tol}


@dataclass
class Dataset:
    id: str
    name: str
    filename: str
    curves: dict
    visible: bool = True
    cache: dict = field(default_factory=dict)
    lens_name: str = ''
    wave_sel: str = None  # 行级波长覆盖；None 表示跟随全局波长

    def own_waves(self):
        def key(w):
            m=re.search(r'\d+(?:\.\d+)?',w)
            return (0,float(m.group())) if m else (1,w)
        return sorted(self.curves,key=key)

    def effective_wave(self, global_wave=None):
        """行级覆盖优先；否则跟随全局；全局不可用则回退到本数据集第一个波长。"""
        if self.wave_sel in self.curves: return self.wave_sel
        if global_wave in self.curves: return global_wave
        waves=self.own_waves()
        return waves[0] if waves else None

    def result(self, wave):
        if wave not in self.curves: return None
        if wave not in self.cache:
            shape=turning_points(self.curves[wave]);terms=3 if shape['count']>=2 else 2
            result=fit_curve(self.curves[wave], method='curve',radius='angle',terms=terms)
            result['turns']=shape
            self.cache[wave]=result
        return self.cache[wave]

    def row_result(self, global_wave=None):
        return self.result(self.effective_wave(global_wave))


class Collection:
    def __init__(self):
        self.items=[]
        self.serial=0

    def add_bytes(self, blob, filename, name=None):
        curves=parse_input(blob,filename)
        buckets=[]
        counts=defaultdict(int)
        for c in curves:
            i=counts[c.wavelength]
            counts[c.wavelength]+=1
            while len(buckets)<=i: buckets.append({})
            buckets[i][c.wavelength]=c
        # Do not change collection if any dataset cannot be evaluated.
        for bucket in buckets:
            for c in bucket.values():
                shape=turning_points(c)
                fit_curve(c,radius='angle',terms=3 if shape['count']>=2 else 2)
        text=decode_text(blob)
        if not name:
            name=distance_or_placeholder(distance_name(filename,text))
        added=[]
        for i,bucket in enumerate(buckets):
            self.serial+=1
            label=name if len(buckets)==1 else f'{name} / 第{i+1}组'
            dataset=Dataset(str(self.serial),label,filename,bucket,lens_name=zmx_name(text))
            self.items.append(dataset);added.append(dataset)
        return added

    def add_text(self,text,name):
        return self.add_bytes(text.encode('utf-8-sig'),name+'.txt',distance_or_placeholder(name))

    def waves(self):
        waves=list(dict.fromkeys(w for d in self.items for w in d.curves))
        def key(w):
            m=re.search(r'\d+(?:\.\d+)?',w)
            return (0,float(m.group())) if m else (1,w)
        return sorted(waves,key=key)

    def visible_results(self,wave):
        return [(d,d.result(wave)) for d in self.items if d.visible and wave in d.curves]

    def maximum(self,wave):
        results=self.visible_results(wave)
        return max((r['dmax'] for _,r in results),default=None)

    def remove(self,ids):
        self.items=[d for d in self.items if d.id not in ids]

    def rename(self,ident,name):
        if not name.strip(): raise ValueError('工作距离或名称不能为空。')
        for d in self.items:
            if d.id==ident: d.name=name.strip();return
        raise ValueError('未找到这条数据。')
