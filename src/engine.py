"""Read-only input parsing and two-term radial distortion fitting."""
from dataclasses import dataclass
from io import BytesIO, StringIO
import csv
import math
import re
from decimal import Decimal
import numpy as np

NUMBER = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"


class UnitChoiceRequired(ValueError):
    def __init__(self, kind, key, context, conflict=False):
        self.kind = kind
        self.key = key
        self.context = context
        self.conflict = conflict
        super().__init__(f'{context} 的单位' + ('标注冲突' if conflict else '未标明'))


def distortion_unit_hints(text):
    hints = set()
    if re.search(r'[%％]|百分(?:数|比)|\bpercent(?:age)?\b', text, re.I):
        hints.add('percent')
    if re.search(r'小数|无量纲|(?<!百分)比例(?!尺)|\b(?:fractions?|fractional|ratios?|dimensionless|decimals?)\b', text, re.I):
        hints.add('fraction')
    return hints


def resolve_data_unit(hints, allowed, kind, key, context, decisions):
    if len(hints) == 1:
        return next(iter(hints))
    if decisions.get(key) in allowed:
        return decisions[key]
    raise UnitChoiceRequired(kind, key, context, conflict=len(hints) > 1)


def wavelength_label(value, unit):
    nm = unit.lower() in ('nm', '纳米', 'nanometer', 'nanometers', 'nanometre', 'nanometres')
    micron = Decimal(value) / (1000 if nm else 1)
    if not micron.is_finite() or micron <= 0:
        raise ValueError('波长必须是正数。')
    return f'{format(micron.normalize(), "f")} μm'


def number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('空白或非数值')
    text = str(value).strip().replace('\t', '')
    out = float(text)
    if not math.isfinite(out):
        raise ValueError('数据包含无穷大或非数值')
    return out


@dataclass
class Curve:
    id: str
    filename: str
    sheet: str
    wavelength: str
    start: int
    end: int
    first_header: str
    last_header: str
    first: list
    raw: list
    radius_kind: str
    unit: str

    def info(self):
        return {k: v for k, v in self.__dict__.items() if k not in ('first', 'raw')} | {'n': len(self.raw)}


def parse_input(blob, filename, unit_choices=None):
    """Numerical samples are ALWAYS first and last columns only.

    Other cells may provide table boundaries; metadata supplies wavelength labels.
    No real/predicted height, displacement, or focal length enters the fit.
    """
    if len(blob) > 40 * 1024 * 1024:
        raise ValueError('文件超过 40 MB，请只保留畸变数据后导入。')
    suffix = filename.lower().rsplit('.', 1)[-1]
    if suffix in ('xlsx', 'xlsm'):
        from openpyxl import load_workbook
        wb = load_workbook(BytesIO(blob), read_only=True, data_only=True)
        tables = []
        try:
            for ws in wb:
                if ws.max_row and ws.max_row > 200000:
                    raise ValueError('单个 Sheet 超过 20 万行，请缩小数据范围。')
                tables.append((ws.title, list(ws.iter_rows(values_only=True))))
        finally:
            wb.close()
    elif suffix in ('csv', 'tsv', 'txt'):
        encodings = ('utf-16',) if blob.startswith((b'\xff\xfe',b'\xfe\xff')) else ('utf-8-sig', 'gb18030')
        for encoding in encodings:
            try:
                content = blob.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError('文本编码无法识别，请保存为 UTF-8 CSV。')
        if suffix == 'txt':
            rows = []
            for line in content.splitlines():
                cells = line.split('\t') if '\t' in line else re.split(r'\s{2,}',line.strip())
                cells = [s.strip() for s in cells]
                if len(cells)>1:
                    rows.append([cells[0],cells[-1]])
                elif re.match(r'^\s*'+NUMBER+r'\s+',line):
                    tokens = line.split()
                    last = tokens[-2]+'%' if tokens[-1] in ('%','％') else tokens[-1]
                    rows.append([tokens[0],last])
                elif ('畸变' in line or 'distortion' in line.lower()) and ('角度' in line or '半径' in line or 'angle' in line.lower() or 'radius' in line.lower()):
                    label = re.search(r'(?:畸变|distortion).*', line, re.I)
                    rows.append(['角度（度）' if ('角度' in line or 'angle' in line.lower()) else '半径', label.group()])
                else:
                    rows.append([line])
            tables=[('TXT',rows)]
        else:
            delimiter = '\t' if suffix == 'tsv' else ','
            tables = [('文本数据', list(csv.reader(StringIO(content), delimiter=delimiter)))]
    else:
        raise ValueError('支持 .xlsx、.xlsm、.csv、.tsv；旧版 .xls 请另存为 .xlsx。')
    choices = unit_choices or {}
    curves = []
    for sheet, rows in tables:
        wave = '未标注波长'
        header = None
        width = None
        points = []
        firstrow = lastrow = 0
        wave_at_start = wave
        prose_hints = set()

        def finish():
            nonlocal points
            if len(points) >= 3:
                fh, lh = header if header else ('第一列', '最后一列')
                kind = 'angle' if ('角' in fh or 'angle' in fh.lower()) else 'normalized'
                hints = prose_hints | distortion_unit_hints(lh)
                if any(p[3] for p in points):
                    hints.add('percent')
                unit = resolve_data_unit(hints, ('percent','fraction'), 'distortion',
                                         ('distortion', sheet, firstrow),
                                         f'{sheet} 第 {firstrow} 行起的畸变', choices)
                curves.append(Curve(str(len(curves)), filename, sheet, wave_at_start,
                                    firstrow, lastrow, fh, lh, [p[1] for p in points],
                                    [p[2] for p in points], kind, unit))
            points = []

        for line, row in enumerate(rows, 1):
            nonempty = [i for i, v in enumerate(row) if v is not None and str(v).strip()]
            if not nonempty:
                continue
            left = row[0] if len(row) else None
            text = ' '.join(str(row[i]).strip() for i in nonempty)
            # Only explicit unit declarations qualify as prose hints. A line
            # reporting the overall maximum need not use the same unit as the table.
            if re.match(r'^\s*(?:畸变\s*单位|units?\s+(?:of|for)\s+distortion\b|distortion\s+(?:units?\b|is\s+(?:in|expressed|given)\b))', text, re.I):
                finish()
                prose_hints = distortion_unit_hints(text)
                continue
            match = re.search(r'(?:波长|wavelength)\s*[:：]?\s*(' + NUMBER + r')\s*([^\s,，。]*)', text, re.I)
            if match:
                finish()
                unittext = match.group(2).rstrip('.').lower()
                if unittext in ('μm', 'µm', 'um', '微米', 'micron', 'microns', 'micrometer',
                                'micrometers', 'micrometre', 'micrometres'):
                    wave = wavelength_label(match.group(1), 'μm')
                elif unittext in ('nm', '纳米','nanometer','nanometers','nanometre','nanometres'):
                    wave = wavelength_label(match.group(1), 'nm')
                elif not unittext:
                    unittext = resolve_data_unit(set(), ('nm', 'μm'), 'wavelength',
                                                 ('wavelength', sheet, line), f'{sheet} 第 {line} 行波长 {match.group(1)}', choices)
                    wave = wavelength_label(match.group(1), unittext)
                else:
                    raise ValueError(f'第 {line} 行无法识别波长单位“{unittext}”，请使用 nm 或 μm。')
                continue
            # Header location is taken from the last nonempty header cell, never from
            # the intermediate numeric columns. The same column stays fixed for data.
            tail = str(row[nonempty[-1]]).strip()
            fh = str(left or '').strip()
            is_header = ('畸变' in tail or 'distortion' in tail.lower()) and len(nonempty) >= 2
            if is_header:
                finish()
                header = (fh, tail)
                width = nonempty[-1] + 1
                continue
            lastindex = width - 1 if width else nonempty[-1]
            if lastindex == 0 or lastindex >= len(row):
                continue
            rawtext = str(row[lastindex] if row[lastindex] is not None else '').strip()
            haspercent = rawtext.endswith(('%', '％'))
            try:
                x = number(left)
                y = number(rawtext.rstrip('%％'))
            except (ValueError, TypeError):
                continue
            if not points:
                wave_at_start = wave
                firstrow = line
            lastrow = line
            points.append((line, x, y, haspercent))
        finish()
    if not curves:
        raise ValueError('未找到曲线。请保留第一列角度/半径、最后一列畸变，并保留表头；每段至少需要三个有效点。')
    return curves


def fit_curve(curve, radius='auto', unit='auto', method='curve', limit=None, terms=2):
    if terms not in (2,3): raise ValueError('模型只支持两项或三项。')
    radius = curve.radius_kind if radius == 'auto' else radius
    unit = curve.unit if unit == 'auto' else unit
    x = np.asarray(curve.first, dtype=float)
    raw = np.asarray(curve.raw, dtype=float)
    if radius == 'angle':
        if np.any(np.abs(x) >= 89.9):
            raise ValueError('角度应小于 89.9°；如果第一列是半径，请切换第一列类型。')
        q = np.abs(np.tan(np.deg2rad(x)))
        definition = 'r = tan(第一列角度)，无量纲；图中纵轴另归一化为 0～1'
    elif radius == 'normalized':
        q = np.abs(x)
        definition = 'r = 第一列半径的绝对值；图中纵轴再除以最大半径'
    else:
        raise ValueError('第一列类型无效。')
    scale = float(np.max(q))
    if scale <= 0:
        raise ValueError('所有半径都为零，无法拟合。')
    rho = q / scale
    if len(np.unique(np.round(rho[rho > 0], 10))) < terms:
        raise ValueError(f'至少需要 {terms} 个不同的非零半径，才能确定模型系数。')
    d = raw / 100 if unit == 'percent' else raw
    # Solve on scaled radius for conditioning; return coefficients on stated r.
    A = np.column_stack([rho**(2*(i+1)) for i in range(terms)])
    if method == 'curve':
        lhs, rhs = A, d
    elif method == 'point':
        lhs, rhs = A * rho[:, None], d * rho
    else:
        raise ValueError('拟合方法无效。')
    c, _, rank, _ = np.linalg.lstsq(lhs, rhs, rcond=None)
    if rank != terms:
        raise ValueError('数据不足以稳定确定模型系数，请增加不同半径的数据点。')
    pred = A @ c
    error = (pred - d) * 100
    dpp = d * 100
    dmax = float(np.max(np.abs(dpp)))
    worst = int(np.argmax(np.abs(error)))
    maxerr = float(np.max(np.abs(error)))
    relative = 100 * maxerr / dmax if dmax > 1e-14 else None
    if limit is not None and (not math.isfinite(limit) or limit < 0):
        raise ValueError('允许偏差应为大于或等于零的有限数值。')
    verdict = '未设置允许偏差'
    if limit is not None:
        passed = maxerr <= (dmax * limit / 100) + 1e-12
        verdict = '满足所设偏差' if passed else '超过所设偏差'
    order = np.argsort(rho, kind='stable')
    t = np.linspace(0, 1, 601)
    dense = 100 * sum(c[i]*t**(2*(i+1)) for i in range(terms))
    central = (rho <= .100001) & (rho > 0)
    return {
        'source': curve.info(), 'unit': unit, 'radius': radius,
        'definition': definition, 'method': method,
        'coefficients': [float(c[i]/scale**(2*(i+1))) for i in range(terms)],
        'terms': terms,
        'coefficients_normalized': c.tolist(), 'radius_max': scale,
        'distortion_unit': 'D 为小数比例，例如 0.005 代表 0.5%',
        'n': len(d), 'dmax': dmax, 'max_error': maxerr,
        'rms_error': float(np.sqrt(np.mean(error**2))),
        'relative_error': relative, 'worst_radius': float(rho[worst]),
        'worst_distortion': float(dpp[worst]), 'worst_fit': float(pred[worst]*100),
        'point_error': float(np.max(np.abs((pred-d)*q))),
        'limit': limit, 'verdict': verdict,
        'center_count': int(np.count_nonzero(central)),
        'sample_min_radius': float(np.min(rho[rho>0])),
        'samples': [[float(rho[i]), float(dpp[i]), float(pred[i]*100), float(error[i]), float(x[i])] for i in order],
        'fit': [[float(a), float(b)] for a, b in zip(t, dense)],
    }
