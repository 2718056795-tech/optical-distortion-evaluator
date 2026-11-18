# -*- coding: utf-8 -*-
"""光机镜头畸变评估工具 V6 — PySide6 (Qt 6) 界面。

与 V5 功能完全等效：导入 ZEMAX F-Tan(Theta) 畸变文本、表格行级波长、
KPI 分级、复选框图例、悬停读数、PNG/SVG 导出。
界面渲染走 Qt/DirectWrite，解决 Tk/GDI 字体观感问题。
"""
from pathlib import Path
import argparse
import json
import os
import re
import sys
import math
import hashlib

from PySide6.QtCore import Qt, QTimer, QEvent, QPoint, QPointF, QSize, QCoreApplication
from PySide6.QtGui import QFont, QFontDatabase, QFontInfo, QColor, QPainter, QPainterPath, QPen, QBrush, QPixmap, QMouseEvent
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QDialog, QMenu, QMessageBox, QFileDialog,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QLabel, QPushButton, QLineEdit,
    QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QStatusBar, QScrollBar, QSizePolicy, QStyledItemDelegate, QStyleOptionViewItem, QToolTip,
)

import matplotlib
matplotlib.use('QtAgg')
from matplotlib import font_manager
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.legend_handler import HandlerBase
from matplotlib.patches import FancyBboxPatch
from matplotlib.transforms import Bbox
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

_here = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))

# ---------- 字体 ----------
# 思源宋体：界面与图表的汉字
SERIF_CJK = 'Source Han Serif SC'
_serifcjk = _here / 'SourceHanSerifSC-Regular.otf'
_serifcjk_bold = _here / 'SourceHanSerifSC-Bold.otf'
_serifcjk_medium = _here / 'SourceHanSerifSC-Medium.otf'
SERIF_CJK_MPL = SERIF_CJK
if _serifcjk.exists():
    font_manager.fontManager.addfont(str(_serifcjk))
    try:
        SERIF_CJK_MPL = font_manager.FontProperties(fname=str(_serifcjk)).get_name()
    except Exception:
        pass
if _serifcjk_bold.exists():
    font_manager.fontManager.addfont(str(_serifcjk_bold))
# 数字、英文和中文统一使用随包提供的思源宋体。
SERIF = SERIF_CJK
SERIF_MPL = SERIF_CJK_MPL if _serifcjk.exists() else 'Microsoft YaHei UI'
matplotlib.rcParams['font.family'] = [SERIF_MPL]
matplotlib.rcParams['axes.unicode_minus'] = False
matplotlib.rcParams['font.weight'] = 'normal'
matplotlib.rcParams['text.color'] = '#2d2d2b'

from model import Collection, decode_text, distortion_grade, turning_grade, fit_grade  # noqa: E402
from engine import UnitChoiceRequired

HERE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
if getattr(sys, 'frozen', False):
    _external_sample = Path(sys.executable).resolve().parent / 'examples' / '畸变样例.txt'
    SAMPLE = _external_sample if _external_sample.is_file() else HERE / '畸变样例.txt'
else:
    SAMPLE = HERE.parent / 'examples' / '畸变样例.txt'
COLORS = ['#007aff', '#ff9500', '#00a68a', '#af52de', '#e84b76', '#5c8b34', '#32a8b8', '#91664d']
BG = '#f5f5f7'
INK = '#2d2d2b'
MUTED = '#7b7b85'
TEAL = '#007aff'


def ui_font(family=SERIF_CJK, pixels=16, weight=QFont.Weight.Normal):
    """Match browser text with explicit size, weight and smooth outline rendering."""
    f = QFont()
    f.setFamilies([family, SERIF_CJK, 'Microsoft YaHei UI'])
    f.setPixelSize(pixels)
    f.setWeight(weight)
    # Default hinting snaps CJK serifs to hard pixel edges at 1x scaling.
    # Compare against Chromium at the same size before changing this policy.
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
    return f


def tint(color, f=.5):
    r, g, b = matplotlib.colors.to_rgb(color)
    return tuple(c + (1 - c) * f for c in (r, g, b))


TINTS = [tint(c) for c in COLORS]


def wave_nm(w):
    """'0.43 μm' → '430'，供表格分段控件与列头使用。"""
    if not w:
        return ''
    m = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(nm|纳米|[μµu]m|微米)', w.strip(), re.I)
    if not m:
        return w
    from decimal import Decimal
    scale = 1 if m.group(2).lower() in ('nm', '纳米') else 1000
    return format((Decimal(m.group(1)) * scale).normalize(), 'f')


USAGE_TEXT = (
    '数据导入：在 ZEMAX 中打开「分析 → 像差分析 → 场曲/畸变 → 文本」，畸变类型选择 F-Tan(Theta)；'
    '复制文本后点「粘贴 TXT 文本」，或通过「选择 TXT 文件」自动填入文本；填写图例备注后点击「解析并加入」。\n\n'
    '图例备注：导入时必须填写；单击表格行可高亮对应曲线并加粗，再点一次取消；'
    '双击表格行名称即可修改图例备注；右侧图例仅用于单击显示 / 隐藏曲线。\n\n'
    '显示控制：点击图例前的复选框勾选 / 取消勾选，即可显示 / 隐藏对应曲线；'
    '单击表格序号列可切换该条数据的显示；「视图 → 全部显示」一键恢复所有曲线。\n\n'
    '多波长：每个设计的波长可以不同——在表格「波长」列直接点选（单位 nm）；超过 6 个波长时为弹出菜单。\n\n'
    '图片导出：「文件」菜单可将当前叠加图保存为 PNG 或 SVG。'
)

# ---------- macOS 风格复选框图例手柄 ----------

class _CheckHandler(HandlerBase):
    # 图例手柄 = 复选框 + 原有彩色线条：勾选=显示曲线，取消勾选=隐藏
    def legend_artist(self, legend, orig_handle, fontsize, handlebox):
        checked = orig_handle.get_visible()
        color = orig_handle.get_color()
        line_w = orig_handle.get_linewidth()
        w, h = handlebox.width, handlebox.height
        x0, y0 = handlebox.xdescent, handlebox.ydescent
        box_h = fontsize  # 按文字字号定尺寸，避免被偏矮的图例手柄区域压小
        gap = box_h * .45
        x, y = x0, y0 + (h - box_h) / 2
        box = FancyBboxPatch((x, y), box_h, box_h, boxstyle=f'round,pad=0,rounding_size={box_h*0.16}',
                             facecolor='white', edgecolor='#3a3a3c', linewidth=1.2,
                             clip_on=False, zorder=3)
        handlebox.add_artist(box)
        res = [box]
        if checked:
            pts = [(x + box_h * 0.15, y + box_h * 0.48), (x + box_h * 0.43, y + box_h * 0.16),
                   (x + box_h * 1.06, y + box_h * 1.10)]
            chk = Line2D([p[0] for p in pts], [p[1] for p in pts], color=color, linewidth=2.1,
                         solid_capstyle='round', solid_joinstyle='round', clip_on=False, zorder=4)
            handlebox.add_artist(chk)
            res.append(chk)
        # 右侧保留原有的彩色线条样例
        line = Line2D([x + box_h + gap, x0 + w], [y0 + h / 2] * 2, color=color, linewidth=line_w,
                      solid_capstyle='round', zorder=3)
        handlebox.add_artist(line)
        res.append(line)
        return res


# ---------- 表格行内迷你波长分段控件（macOS 分段样式，与 V5 相同） ----------

class MiniSegmented(QWidget):
    SEG_W, SEG_H = 46, 26

    def __init__(self, parent=None, command=None):
        super().__init__(parent)
        self.command = command
        self.values = []
        self.current = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.columns = 1

    def set_state(self, values, current):
        values = list(values)
        if values == self.values and current == self.current:
            return
        self.values = values
        self.current = current
        self.columns = 2 if len(values) == 4 else min(3, max(1, len(values)))
        lines = max(1, math.ceil(len(values) / self.columns))
        self.setFixedSize(self.columns * self.SEG_W + 2, lines * self.SEG_H + 2)
        self.update()

    def paintEvent(self, event):
        if not self.values:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # 灰色轨道圆角
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor('#eaeaef')))
        p.drawRoundedRect(0, 0, w, h, min(h / 2, 13), min(h / 2, 13))
        f = ui_font(SERIF, 16)
        f.setWeight(QFont.Weight.Bold)
        fm_num = ui_font(SERIF, 16)
        for idx, v in enumerate(self.values):
            x = (idx % self.columns) * self.SEG_W + 1
            y = (idx // self.columns) * self.SEG_H + 1
            if v == self.current:
                p.setBrush(QBrush(QColor('white')))
                pen = QPen(QColor('#d9d9de'))
                pen.setWidthF(.7)
                p.setPen(pen)
                p.drawRoundedRect(x, y, self.SEG_W - 2, self.SEG_H - 2, (self.SEG_H - 2) / 2, (self.SEG_H - 2) / 2)
                p.setPen(QColor(INK))
                p.setFont(f)
            else:
                p.setPen(QColor(MUTED))
                p.setFont(fm_num)
            p.drawText(int(x), int(y), self.SEG_W - 2, self.SEG_H - 2, Qt.AlignmentFlag.AlignCenter, wave_nm(v))
        p.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        column = int(event.position().x() // self.SEG_W)
        row = int(event.position().y() // self.SEG_H)
        idx = row * self.columns + column
        if row >= 0 and 0 <= column < self.columns and 0 <= idx < len(self.values) and self.command:
            event.accept()
            self.command(self.values[idx])
        else:
            event.ignore()

    def wheelEvent(self, event):
        # 转发滚轮给表格滚动
        table = self.parent()
        while table is not None and not isinstance(table, QTableWidget):
            table = table.parent()
        if table is not None:
            bar = table.verticalScrollBar()
            bar.setValue(bar.value() - event.angleDelta().y() // 120 * 1)
        event.accept()


# ---------- 可点击标签（PySide6 不支持实例级覆盖虚函数，用信号实现） ----------

class ClickLabel(QLabel):
    clicked = None  # 由 __init__ 赋值 Signal（见下）

    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self._clicked_callbacks = []

    def on_clicked(self, cb):
        self._clicked_callbacks.append(cb)
        return self

    def mousePressEvent(self, event):
        for cb in self._clicked_callbacks:
            cb(event)
        super().mousePressEvent(event)


# ---------- 弹窗：修改图例备注（frameless + 圆角卡片，macOS 风格） ----------

class RenameDialog(QDialog):
    def __init__(self, parent, current):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(400, 234)
        self.result_name = None
        self._drag_pos = None
        card = QFrame(self)
        card.setObjectName('rename_card')
        card.setGeometry(0, 0, 400, 234)
        card.setStyleSheet(
            'QFrame#rename_card{background:white;border:1px solid #e5e5ea;border-radius:14px;}')
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 20, 24, 18)
        title = QLabel('图例备注')
        title.setStyleSheet('border:none;background:transparent;')
        f = ui_font(SERIF_CJK, 17)
        f.setWeight(QFont.Weight.Bold)
        title.setFont(f)
        lay.addWidget(title)
        hint = QLabel('例如：300 mm、600 mm、2000 mm')
        hint.setStyleSheet('border:none;background:transparent;')
        hint.setFont(ui_font(SERIF_CJK, 16))
        hint.setStyleSheet(f'border:none;background:transparent;color:{INK};')
        lay.addWidget(hint)
        lay.addSpacing(12)
        self.entry = QLineEdit('' if current == '双击输入' else current)
        self.entry.setFont(ui_font(SERIF, 16))
        self.entry.setStyleSheet(
            'QLineEdit{background:white;color:#2d2d2b;border:1px solid #d8d8de;border-radius:6px;'
            'padding:6px 8px;}'
            f'QLineEdit:focus{{border:1px solid {TEAL};}}')
        lay.addWidget(self.entry)
        lay.addSpacing(22)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton('取消')
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(f'QPushButton{{background:transparent;border:none;color:{TEAL};'
                             'font-size:16px;padding:6px 14px;}'
                             'QPushButton:hover{background:#f0f1f5;border-radius:10px;}')
        save = QPushButton('保存')
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.setStyleSheet('QPushButton{background:#007aff;color:white;border:none;'
                           'border-radius:12px;padding:6px 20px;font-size:16px;}'
                           'QPushButton:hover{background:#0068df;}')
        btns.addWidget(cancel)
        btns.addWidget(save)
        lay.addLayout(btns)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._save)
        if self.entry.text():
            self.entry.selectAll()

    def _save(self):
        self.result_name = self.entry.text().strip()
        self.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._save()
        elif event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)


def ask_rename(parent, current):
    dlg = RenameDialog(parent, current)
    if parent is not None:
        dlg.move(parent.frameGeometry().center() - dlg.rect().center())
    dlg.entry.setFocus()
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.result_name
    return None


# ---------- 弹窗：粘贴 TXT 文本 ----------

class PasteDialog(QDialog):
    def __init__(self, app, text='', source_path=None):
        super().__init__(app, Qt.WindowType.Dialog)
        self.app = app
        self.source_path = Path(source_path) if source_path is not None else None
        self.added = []
        self.setWindowTitle('导入 TXT - ' + self.source_path.name if self.source_path else '粘贴 TXT 文本')
        self.resize(870, 650)
        self.setMinimumSize(650, 460)
        self.setStyleSheet(f'QDialog{{background:{BG};}}')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        top = QHBoxLayout()
        lbl = QLabel('图例备注')
        lbl.setFont(ui_font(SERIF_CJK, 16))
        top.addWidget(lbl)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText('必填，例如 300mm')
        self.name_edit.setFont(ui_font(SERIF, 16))
        self.name_edit.setStyleSheet(
            'QLineEdit{background:white;border:1px solid #e5e5ea;border-radius:6px;padding:5px 8px;}'
            f'QLineEdit:focus{{border:1px solid {TEAL};}}')
        self.name_edit.setFixedWidth(300)
        top.addWidget(self.name_edit)
        top.addSpacing(12)
        hint = QLabel('必填')
        hint.setStyleSheet(f'color:{INK};border:none;background:transparent;')
        hint.setFont(ui_font(SERIF_CJK, 16))
        top.addWidget(hint)
        top.addStretch(1)
        lay.addLayout(top)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.text_edit.setStyleSheet(
            'QPlainTextEdit{background:white;border:1px solid #e5e5ea;border-radius:8px;'
            'padding:8px;font-family:Consolas;font-size:16px;}'
            'QScrollBar:horizontal{background:#fbfbfc;height:12px;border:none;}'
            'QScrollBar::handle:horizontal{background:#c3cad2;border-radius:6px;min-width:30px;}'
            'QScrollBar::handle:horizontal:hover{background:#a9b2bc;}'
            'QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;}')
        lay.addWidget(self.text_edit, 1)
        self.text_edit.setPlainText(text)
        buttons = QHBoxLayout()
        paste = QPushButton('从剪贴板粘贴')
        paste.setAutoDefault(False)
        self._style_button(paste)
        paste.clicked.connect(self._clipboard)
        cancel = QPushButton('取消')
        cancel.setAutoDefault(False)
        self._style_button(cancel)
        cancel.clicked.connect(self.reject)
        self.submit_btn = QPushButton('解析并加入')
        self.submit_btn.setDefault(True)
        self._style_button(self.submit_btn, primary=True)
        self.submit_btn.clicked.connect(self.submit)
        buttons.addWidget(paste)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.submit_btn)
        lay.addLayout(buttons)
        self.name_edit.textChanged.connect(self._sync_submit)
        self.text_edit.textChanged.connect(self._sync_submit)
        self._sync_submit()

    def _sync_submit(self):
        self.submit_btn.setEnabled(bool(self.name_edit.text().strip() and self.text_edit.toPlainText().strip()))

    def showEvent(self, event):
        super().showEvent(event)
        target = self.name_edit if self.source_path else self.text_edit
        target.setFocus(Qt.FocusReason.OtherFocusReason)

    @staticmethod
    def _style_button(btn, primary=False):
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if primary:
            btn.setStyleSheet('QPushButton{background:#007aff;color:white;border:none;border-radius:13px;'
                              'padding:7px 18px;font-size:16px;}'
                              'QPushButton:hover{background:#0068df;}'
                              'QPushButton:disabled{background:#e6e7ec;color:#9b9ba5;}')
        else:
            btn.setStyleSheet('QPushButton{background:#f0f1f5;color:#3a3a3c;border:none;border-radius:13px;'
                              'padding:7px 18px;font-size:16px;}'
                              'QPushButton:hover{background:#e8ebf1;}')

    def _clipboard(self):
        text = QApplication.clipboard().text()
        if text:
            self.text_edit.insertPlainText(text)
        else:
            QMessageBox.warning(self, '无法粘贴', '剪贴板中没有可读取的文本。')

    def submit(self):
        name = self.name_edit.text().strip()
        if not name:
            self.name_edit.setFocus()
            return
        text = self.text_edit.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, '未输入文本', '请先粘贴 TXT 内容。')
            return
        try:
            filename = self.source_path.name if self.source_path else '粘贴数据.txt'
            blob = text.encode('utf-8-sig')
            added = add_with_units(self, self.app.model, blob, filename, name)
            if added is None:
                return
            self.added = added
            self.app.refresh()
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, '解析未完成', str(exc))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)


def add_with_units(parent, model, blob, filename, name):
    choices = {}
    while True:
        try:
            return model.add_bytes(blob, filename, name=name, unit_choices=choices)
        except UnitChoiceRequired as exc:
            issue = exc
        box = QMessageBox(parent)
        box.setWindowTitle('确认数据单位')
        box.setText(str(issue) + '，请按原始数据选择。')
        if issue.kind == 'distortion':
            options = [('百分数（0.5 表示 0.5%）', 'percent'), ('小数比例（0.005 表示 0.5%）', 'fraction')]
        else:
            options = [('纳米（nm）', 'nm'), ('微米（μm）', 'μm')]
        buttons = {box.addButton(label, QMessageBox.ButtonRole.ActionRole): unit for label, unit in options}
        cancel = box.addButton('取消', QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        choice = buttons.get(box.clickedButton())
        if choice is None:
            return None
        choices[issue.key] = choice


# ---------- 弹窗：使用说明 ----------

class HelpDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.Dialog)
        self.setWindowTitle('使用说明')
        self.resize(640, 460)
        self.setStyleSheet(f'QDialog{{background:{BG};}}')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 16)
        box = QFrame()
        box.setStyleSheet('QFrame{background:white;border:1px solid #e5e5ea;border-radius:10px;}')
        bl = QVBoxLayout(box)
        bl.setContentsMargins(16, 16, 16, 16)
        text = QLabel(USAGE_TEXT)
        text.setWordWrap(True)
        text.setFont(ui_font(SERIF_CJK, 16))
        text.setStyleSheet('background:transparent;border:none;')
        bl.addWidget(text)
        lay.addWidget(box, 1)
        close = QPushButton('关闭')
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet('QPushButton{background:#f0f1f5;color:#3a3a3c;border:none;border-radius:13px;'
                            'padding:7px 26px;font-size:16px;}'
                            'QPushButton:hover{background:#e8ebf1;}')
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignmentFlag.AlignCenter)


# ---------- KPI 三档分级小表（macOS 风格：细线外框 + 通栏色条） ----------

class GradeTable(QFrame):
    _ROW_H = 32
    _GREEN, _YELLOW, _RED = '#087647', '#9b6800', '#bc302b'
    _HAIR = '#e5e5ea'
    _TIERS = [('较好', '#f0f7f2', _GREEN, [('≤', '0.5%'), ('≤', '1'), ('≤', '5%')]),
              ('需关注', '#fbf5e8', _YELLOW, [('', '0.5%~1%'), ('', '2'), ('', '5%~10%')]),
              ('较差', '#fbf0f0', _RED, [('>', '1%'), ('>', '2'), ('>', '10%')])]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('grade_table')
        self.setStyleSheet(
            'QFrame#grade_table{background:white;border:1px solid #e5e5ea;border-radius:10px;}')
        self._band_labels = []
        self.setFixedHeight(4 * self._ROW_H + 4)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        grid.setColumnMinimumWidth(0, 72)
        for c in (1, 2, 3):
            grid.setColumnStretch(c, 1)
            grid.setColumnMinimumWidth(c, 74)
        for c, htext in enumerate(('档位', '畸变', '拐点个数', '拟合偏差')):
            lbl = QLabel(htext)
            lbl.setObjectName('grade_heading')
            lbl.setFixedHeight(self._ROW_H)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f'background:transparent;border:none;color:#2d2d2b;padding:2px 10px;')
            lbl.setFont(ui_font(SERIF_CJK, 16, QFont.Weight.Medium))
            grid.addWidget(lbl, 0, c)
        for r, (grade, tint, color, cells) in enumerate(self._TIERS):
            row = 1 + r * 2
            if r > 0:
                hair = QFrame()
                hair.setStyleSheet('background:#e5e5ea;border:none;')
                hair.setFixedHeight(1)
                grid.addWidget(hair, row - 1, 0, 1, 4)
            g = QLabel(grade)
            g.setFixedHeight(self._ROW_H)
            g.setAlignment(Qt.AlignmentFlag.AlignCenter)
            g.setStyleSheet(f'background:transparent;border:none;color:{color};padding:3px 10px;')
            f = ui_font(SERIF_CJK, 16)
            f.setWeight(QFont.Weight.Bold)
            g.setFont(f)
            grid.addWidget(g, row, 0)
            self._band_labels.append((g, tint))
            for c, (op, num) in enumerate(cells, start=1):
                cell = QWidget()
                cell.setFixedHeight(self._ROW_H)
                cell.setStyleSheet('background:transparent;border:none;')
                h = QHBoxLayout(cell)
                h.setContentsMargins(0, 3, 0, 3)
                h.setSpacing(2)
                h.addStretch(1)
                if op:
                    o = QLabel(op)
                    o.setStyleSheet(f'background:transparent;border:none;color:{color};')
                    o.setFont(ui_font(SERIF_CJK, 16))
                    h.addWidget(o)
                n = QLabel(num)
                n.setStyleSheet(f'background:transparent;border:none;color:{color};')
                n.setFont(ui_font(SERIF, 16))
                h.addWidget(n)
                h.addStretch(1)
                grid.addWidget(cell, row, c)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(1, 1, self.width() - 2, self.height() - 2, 9, 9)
        painter.setClipPath(clip)
        for i, (label, tint) in enumerate(self._band_labels):
            top = label.geometry().top()
            bottom = (self._band_labels[i + 1][0].geometry().top()
                      if i + 1 < len(self._band_labels) else self.height() - 1)
            painter.fillRect(1, top, self.width() - 2, bottom - top, QColor(tint))


class DataRowDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        # Preserve cell brushes instead of inheriting the card's white background.
        option = QStyleOptionViewItem(option)
        option.widget = None
        super().paint(painter, option, index)


# ---------- 主窗口 ----------

class App(QMainWindow):
    COLS = [('序号', 48), ('图例备注(双击修改)', 176), ('波长 nm', 84), ('最大畸变', 100), ('拐点个数', 90), ('相对偏差', 90)]

    def __init__(self):
        super().__init__()
        self.setWindowTitle('光机镜头畸变评估工具')
        self.resize(1610, 940)
        self.setMinimumSize(1180, 740)
        self.setStyleSheet(f'QMainWindow{{background:{BG};}}'
                           'QMenuBar{background:#f5f5f7;border:none;}'
                           'QMenuBar::item{background:transparent;padding:5px 12px;border-radius:6px;}'
                           'QMenuBar::item:selected{background:#e8ebf1;}'
                           'QMenu{background:white;border:1px solid #e5e5ea;border-radius:8px;padding:5px;}'
                           'QMenu::item{padding:6px 28px;border-radius:5px;}'
                           'QMenu::item:selected{background:#e3edfd;}'
                           'QStatusBar{background:#f5f5f7;border:none;}'
                           'QScrollBar:vertical{background:#fbfbfc;width:12px;border:none;}'
                           'QScrollBar::handle:vertical{background:#c3cad2;border-radius:6px;min-height:30px;}'
                           'QScrollBar::handle:vertical:hover{background:#a9b2bc;}'
                           'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}'
                           'QScrollBar:horizontal{height:0;}')
        self.model = Collection()
        self.wave = ''  # 全局波长（顶部选择器已按需求移除；行级覆盖优先）
        self._hover_id = None
        self._selected_id = None
        self._chart_lines = []
        self._legend_toggle = []
        self._last_legend_mouseevent = None
        self._resize_pending = False
        self._build()

    # ===== 构建界面 =====

    def _mac_button(self, text, primary=False):
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if primary:
            btn.setStyleSheet('QPushButton{background:#007aff;color:white;border:none;border-radius:13px;'
                              'padding:8px 20px;font-size:16px;}'
                              'QPushButton:hover{background:#0068df;}')
        else:
            btn.setStyleSheet('QPushButton{background:#f0f1f5;color:#3a3a3c;border:none;border-radius:13px;'
                              'padding:8px 20px;font-size:16px;}'
                              'QPushButton:hover{background:#e8ebf1;}')
        return btn

    def _build(self):
        cjk_b = lambda sz: ui_font(SERIF_CJK, round(sz * 4 / 3), QFont.Weight.Bold)
        # --- 菜单栏 ---
        bar = self.menuBar()
        m_file = bar.addMenu('文件')
        m_file.addAction('选择 TXT 文件…', self.choose_files)
        m_file.addAction('粘贴 TXT 文本…', self.open_paste)
        m_file.addSeparator()
        m_file.addAction('保存当前图为 PNG…', self.export_png)
        m_file.addAction('保存当前图为 SVG…', self.export_svg)
        m_file.addSeparator()
        m_file.addAction('退出', self.close)
        m_view = bar.addMenu('视图')
        m_view.addAction('全部显示', self.show_all_lines)
        m_view.addAction('刷新', self.refresh)
        m_help = bar.addMenu('帮助')
        m_help.addAction('使用说明…', self.show_help)
        m_help.addAction('关于 光机镜头畸变评估工具', self._about)

        central = QWidget()
        central.setStyleSheet(f'background:{BG};')
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 12, 24, 8)
        root.setSpacing(8)

        # --- 标题行 ---
        title = QLabel('光机镜头畸变评估工具')
        title.setFont(cjk_b(21))
        title.setStyleSheet(f'color:{INK};border:none;background:transparent;')
        root.addWidget(title)

        # --- 操作行 ---
        actions = QHBoxLayout()
        actions.setSpacing(9)
        btn_file = self._mac_button('选择 TXT 文件', primary=True)
        btn_file.clicked.connect(self.choose_files)
        btn_paste = self._mac_button('粘贴 TXT 文本', primary=True)
        btn_paste.clicked.connect(self.open_paste)
        actions.addWidget(btn_file)
        actions.addWidget(btn_paste)
        sample = self._mac_button('载入示例')
        sample.setStyleSheet('QPushButton{background:#e4ebf7;color:#274a77;border:1px solid #cbd8ed;'
                            'border-radius:13px;padding:8px 20px;font-size:16px;}'
                            'QPushButton:hover{background:#d5e2f7;}'
                            'QPushButton:pressed{background:#c6d8f3;}')
        sample.clicked.connect(self.load_sample)
        actions.addWidget(sample)
        actions.addStretch(1)
        root.addLayout(actions)

        # --- KPI 带（圆角卡片） ---
        band = QFrame()
        band.setObjectName('band')
        band.setStyleSheet('QFrame#band{background:white;border:1px solid #e5e5ea;border-radius:16px;}')
        band.setFixedHeight(180)
        bl = QHBoxLayout(band)
        bl.setContentsMargins(26, 6, 20, 10)
        bl.setSpacing(0)
        left = QVBoxLayout()
        left.setSpacing(0)
        self.kpi_scope = QLabel('全部数据 · 各项最差')
        self.kpi_scope.setFont(ui_font(SERIF_CJK, 16))
        self.kpi_scope.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.kpi_scope.setStyleSheet(f'color:{INK};border:none;background:transparent;')
        left.addWidget(self.kpi_scope)
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(0)
        kpi_row.setContentsMargins(0, 6, 0, 0)

        def kpi_block(text):
            blk = QVBoxLayout()
            blk.setSpacing(0)
            t = QLabel(text)
            t.setObjectName('kpi_heading')
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setFont(cjk_b(15))
            t.setStyleSheet(f'color:{INK};border:none;background:transparent;')
            blk.addWidget(t)
            row = QHBoxLayout()
            row.setSpacing(0)
            row.setContentsMargins(0, 6, 0, 0)
            num = QLabel('—')
            num.setFont(ui_font(SERIF, 36))
            num.setStyleSheet(f'color:{INK};border:none;background:transparent;')
            num.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            num.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            grd = QLabel('')
            grd.setFont(ui_font(SERIF_CJK, 28, QFont.Weight.Bold))
            grd.setStyleSheet(f'color:{INK};border:none;background:transparent;')
            grd.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grd.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            row.addStretch(1)
            row.addWidget(num)
            row.addSpacing(8)
            row.addWidget(grd)
            row.addStretch(1)
            blk.addLayout(row)
            source = QLabel('')
            source.setObjectName('kpi_source')
            source.setFont(ui_font(SERIF_CJK, 16))
            source.setAlignment(Qt.AlignmentFlag.AlignCenter)
            source.setFixedHeight(24)
            source.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            source.setStyleSheet(f'color:{MUTED};border:none;background:transparent;')
            blk.addWidget(source)
            wrap = QWidget()
            wrap.setStyleSheet('border:none;background:transparent;')
            wrap.setLayout(blk)
            wrap.setMinimumSize(230, 100)
            wrap.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            return wrap, num, grd, source

        w1, self.max_label, self.max_grade, self.max_source = kpi_block('畸变')
        kpi_row.addWidget(w1, 1)
        sep1 = QFrame()
        sep1.setFixedWidth(1)
        sep1.setStyleSheet('background:#ececf1;border:none;max-height:80px;')
        sep1.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        kpi_row.addWidget(sep1)
        w2, self.turn_label, self.turn_grade, self.turn_source = kpi_block('拐点个数')
        kpi_row.addWidget(w2, 1)
        sep2 = QFrame()
        sep2.setFixedWidth(1)
        sep2.setStyleSheet('background:#ececf1;border:none;')
        sep2.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        kpi_row.addWidget(sep2)
        w3, self.fit_label, self.fit_grade, self.fit_source = kpi_block('拟合偏差')
        kpi_row.addWidget(w3, 1)
        left.addLayout(kpi_row)
        left.addStretch(1)
        left_wrap = QWidget()
        left_wrap.setStyleSheet('border:none;background:transparent;')
        left_wrap.setLayout(left)
        left_wrap.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        bl.addWidget(left_wrap, 1)
        bl.addWidget(GradeTable())
        root.addWidget(band)

        # --- 主体：左表 + 右图 ---
        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, 1)

        left_card = QFrame()
        left_card.setObjectName('left_card')
        left_card.setStyleSheet('QFrame#left_card{background:white;border:1px solid #e5e5ea;border-radius:16px;}')
        left_card.setFixedWidth(680)
        ll = QVBoxLayout(left_card)
        ll.setContentsMargins(16, 14, 12, 12)
        head = QHBoxLayout()
        self.data_title = QLabel('数据')
        self.data_title.setFont(cjk_b(12))
        self.data_title.setStyleSheet(f'color:{INK};border:none;background:transparent;')
        head.addWidget(self.data_title, 1)
        btn_rm = self._mac_button('移除所选')
        btn_rm.clicked.connect(self.remove_selected)
        btn_clr = self._mac_button('清空')
        btn_clr.clicked.connect(self.clear_all)
        head.addWidget(btn_rm)
        head.addSpacing(6)
        head.addWidget(btn_clr)
        ll.addLayout(head)
        ll.addSpacing(8)

        self.table = QTableWidget(0, 6)
        self.table.setObjectName('data_table')
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setMouseTracking(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setShowGrid(False)
        self.table.setItemDelegate(DataRowDelegate(self.table))
        self.table.setStyleSheet(
            'QTableWidget#data_table{background:white;border:none;}'
            'QHeaderView::section{background:#f8f8fb;color:#2d2d2b;border:none;'
            'padding:7px;font-size:16px;font-weight:normal;}'
            'QTableWidget#data_table::item{border:none;}')
        for c, (text, width) in enumerate(self.COLS):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setHorizontalHeaderItem(c, item)
            header = self.table.horizontalHeader()
            if c == 1:
                header.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
                self.table.setColumnWidth(c, width)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.itemClicked.connect(self._on_row_click)
        self.table.itemDoubleClicked.connect(self._on_row_double_click)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.viewport().installEventFilter(self)
        ll.addWidget(self.table, 1)
        body.addWidget(left_card)

        # --- 右：图表卡片 ---
        right_card = QFrame()
        right_card.setObjectName('right_card')
        right_card.setStyleSheet('QFrame#right_card{background:white;border:1px solid #e5e5ea;border-radius:16px;}')
        rl = QVBoxLayout(right_card)
        rl.setContentsMargins(16, 14, 12, 8)
        line = QHBoxLayout()
        t2 = QLabel('全视场拟合叠加图')
        t2.setFont(cjk_b(12))
        t2.setStyleSheet(f'color:{INK};border:none;background:transparent;')
        line.addWidget(t2)
        readouts = QHBoxLayout()
        readouts.setSpacing(0)
        hx = QLabel('畸变')
        hx.setFont(ui_font(SERIF_CJK, 16))
        hx.setStyleSheet(f'color:{INK};border:none;background:transparent;')
        self.hover_x = QLabel('—')
        self.hover_x.setFont(ui_font(SERIF, 16))
        self.hover_x.setFixedWidth(88)
        self.hover_x.setStyleSheet(f'color:{INK};border:none;background:transparent;')
        hy = QLabel('归一化半径')
        hy.setFont(ui_font(SERIF_CJK, 16))
        hy.setStyleSheet(f'color:{INK};border:none;background:transparent;')
        self.hover_y = QLabel('—')
        self.hover_y.setFont(ui_font(SERIF, 16))
        self.hover_y.setFixedWidth(88)
        self.hover_y.setStyleSheet(f'color:{INK};border:none;background:transparent;')
        readouts.addWidget(hx)
        readouts.addSpacing(4)
        readouts.addWidget(self.hover_x)
        readouts.addSpacing(12)
        readouts.addWidget(hy)
        readouts.addSpacing(4)
        readouts.addWidget(self.hover_y)
        line.addSpacing(16)
        line.addLayout(readouts)
        line.addStretch(1)
        btn_svg = self._mac_button('导出 SVG')
        btn_svg.clicked.connect(self.export_svg)
        btn_png = self._mac_button('导出 PNG')
        btn_png.clicked.connect(self.export_png)
        line.addWidget(btn_svg)
        line.addSpacing(8)
        line.addWidget(btn_png)
        rl.addLayout(line)
        self.fig = Figure(figsize=(7.2, 5.4), dpi=100)
        self.fig.patch.set_facecolor('white')
        self.mpl_canvas = FigureCanvas(self.fig)
        self._frame_axes = self._frame_renderer = self._plain_plot = None
        self.mpl_canvas.mpl_connect('draw_event', self._remember_plot_frame)
        self.mpl_canvas.setStyleSheet('border:none;background:white;')
        self.mpl_canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.mpl_canvas.mpl_connect('pick_event', self.on_legend_pick)
        self.mpl_canvas.mpl_connect('motion_notify_event', self.on_motion)
        self.mpl_canvas.mpl_connect('scroll_event', self.on_legend_scroll)
        self.legend_scroll = QScrollBar(Qt.Orientation.Vertical, self.mpl_canvas)
        self.legend_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.legend_scroll.setSingleStep(32)
        self.legend_scroll.valueChanged.connect(self._position_legend)
        self.legend_scroll.hide()
        self.mpl_canvas.installEventFilter(self)
        rl.addWidget(self.mpl_canvas, 1)
        body.addWidget(right_card, 1)

        # --- 状态栏 ---
        status = QStatusBar()
        self.setStatusBar(status)
        ver = QLabel('V6')
        ver.setFont(ui_font(SERIF, 16))
        ver.setStyleSheet('color:#2d2d2b;border:none;background:transparent;')
        status.addPermanentWidget(ver)

    def _about(self):
        QMessageBox.about(self, '关于', '光机镜头畸变评估工具 V6\n\n'
                          '导入 ZEMAX F-Tan(Theta) 畸变文本，评估最大畸变、拐点与拟合偏差。\n'
                          '界面框架：Qt 6 (PySide6)。')

    # ===== 事件过滤（表格悬停 + 画布尺寸变化） =====

    def eventFilter(self, obj, event):
        if obj is self.table.viewport():
            if event.type() == QEvent.Type.MouseMove:
                row = self.table.rowAt(int(event.position().y()))
                ident = self.model.items[row].id if 0 <= row < len(self.model.items) else None
                self._set_hover(ident)
            elif event.type() == QEvent.Type.Leave:
                self._set_hover(None)
            elif (event.type() == QEvent.Type.MouseButtonPress
                  and event.button() == Qt.MouseButton.LeftButton
                  and not self.table.indexAt(event.position().toPoint()).isValid()
                  and self._selected_id is not None):
                self._selected_id = None
                self._hover_id = None
                self.show_source(rebuild_plot=False)
        elif obj is self.mpl_canvas:
            if event.type() == QEvent.Type.ToolTip:
                scale = self.mpl_canvas.device_pixel_ratio
                x = event.pos().x() * scale
                y = self.fig.bbox.height - event.pos().y() * scale
                tip = self._legend_hover_text(x, y)
                if tip:
                    QToolTip.showText(event.globalPos(), tip, self.mpl_canvas)
                else:
                    QToolTip.hideText()
                return True
            if event.type() == QEvent.Type.Resize and not self._resize_pending:
                self._resize_pending = True
                QTimer.singleShot(150, self._resize_redraw)
        return super().eventFilter(obj, event)

    # ===== 导入 =====

    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, '选择一个或多个 TXT', '', '畸变 TXT (*.txt);;所有文件 (*.*)')
        if files:
            self.add_files(files)

    def add_files(self, files):
        added, errors = [], []
        for filename in files:
            path = Path(filename)
            try:
                if path.stat().st_size > 40 * 1024 * 1024:
                    raise ValueError('文件超过 40 MB，请只保留畸变数据后导入。')
                text = decode_text(path.read_bytes())
                if not text.strip():
                    raise ValueError('TXT 为空或编码无法识别。')
                dialog = PasteDialog(self, text=text, source_path=path)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    break
                added.extend(dialog.added)
            except Exception as exc:
                errors.append(f'{path.name}：{exc}')
        self.refresh()
        if errors:
            QMessageBox.critical(self, '部分文件未导入', '\n\n'.join(errors))
        return added

    def open_paste(self):
        PasteDialog(self).exec()

    def show_help(self):
        HelpDialog(self).exec()

    def load_sample(self):
        try:
            if add_with_units(self, self.model, SAMPLE.read_bytes(), SAMPLE.name, '示例'):
                self.refresh()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '无法载入示例', str(exc))

    # ===== 数据 / KPI =====

    def row_results(self, global_wave=None):
        """可见数据集在其生效波长（行级覆盖 > 全局 > 自身第一个波长）下的结果。"""
        rows = []
        for d in self.model.items:
            if not d.visible:
                continue
            w = d.effective_wave(global_wave)
            r = d.result(w) if w else None
            if r:
                rows.append((d, w, r))
        return rows

    def _set_label_color(self, label, hexcolor):
        f = label.font()
        label.setStyleSheet(f'color:{hexcolor};border:none;background:transparent;')
        label.setFont(f)

    def _update_kpi(self):
        # Overview: each metric has its own worst source. Selected rows stay unified.
        wave = self.wave
        single = None
        d = next((d for d in self.model.items if d.id == self._selected_id), None)
        if d is not None and d.visible:
            w = d.effective_wave(wave)
            r = d.result(w) if w else None
            if r:
                single = (d, w, r)
        if single is not None:
            self.kpi_scope.setText(f'当前选中：{single[0].name}')
            rows = [single]
        else:
            rows = self.row_results(wave)
            self.kpi_scope.setText('全部数据 · 各项最差')
        worst_distortion = max(rows, key=lambda row: row[2]['dmax'], default=None)
        worst_turns = max(rows, key=lambda row: row[2]['turns']['count'], default=None)
        valid_fits = [row for row in rows if row[2]['relative_error'] is not None]
        worst_fit = single if single is not None else max(
            valid_fits, key=lambda row: row[2]['relative_error'], default=None)

        def show(row, value_fn, format_fn, grader, number, grade, source):
            value = value_fn(row[2]) if row is not None else None
            if row is not None:
                name = row[0].name.strip()
                distance = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(?:mm)?', name, re.I)
                name = distance.group(1) + 'mm' if distance else name
                source.setText('来源：' + name)
                source.setToolTip(row[0].name)
            else:
                source.setText('' if not rows else '来源：—')
                source.setToolTip('')
            if value is None:
                number.setText('—')
                grade.setText('')
                self._set_label_color(number, INK)
                self._set_label_color(grade, INK)
                return
            _, label, color, _ = grader(value)
            number.setText(format_fn(value))
            grade.setText(f'（{label}）')
            # Apply the final grade color synchronously, before expensive redraws.
            self._set_label_color(number, color)
            self._set_label_color(grade, color)

        show(worst_distortion, lambda r: r['dmax'], lambda v: f'{v:.5f}%', distortion_grade,
             self.max_label, self.max_grade, self.max_source)
        show(worst_turns, lambda r: r['turns']['count'], str, turning_grade,
             self.turn_label, self.turn_grade, self.turn_source)
        show(worst_fit, lambda r: r['relative_error'], lambda v: f'{v:.1f}%', fit_grade,
             self.fit_label, self.fit_grade, self.fit_source)

    # ===== 表格刷新 =====

    def _row_bg(self, d):
        if d.id == self._selected_id:
            return '#e3edfd'
        if d.id == self._hover_id:
            return '#f6f9ff'
        return 'white'

    def refresh(self):
        wave = self.wave
        self.table.setRowCount(len(self.model.items))
        f_num = ui_font(SERIF, 16)
        f_cjk = ui_font(SERIF_CJK, 16)
        f_cjk.setWeight(QFont.Weight.Normal)
        wave_width = self.COLS[2][1]
        for i, d in enumerate(self.model.items):
            w = d.effective_wave(wave)
            r = d.result(w) if w else None
            rowbg = self._row_bg(d)
            disabled = '#8a9aa5'
            normal = INK if d.visible else disabled

            def item(col, text, font, fg):
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                it.setFont(font)
                it.setForeground(QColor(fg))
                it.setBackground(QColor(rowbg))
                self.table.setItem(i, col, it)
                return it

            item(0, str(i + 1), f_num, normal)
            item(1, d.name, f_cjk, normal)
            for col in (3, 4, 5):
                item(col, '', f_num, normal)
            self._update_row_metrics(i, d, r)
            # 波长列：行内分段控件 / 超过 6 个波长时为弹出菜单
            row_height = 48
            if d.curves:
                values = d.own_waves()
                current = d.effective_wave(wave)
                if len(values) == 1:
                    self.table.removeCellWidget(i, 2)
                    item(2, wave_nm(current) or '—', f_num, normal)
                elif len(values) > 6:
                    self.table.takeItem(i, 2)
                    lbl = ClickLabel(f'{wave_nm(current)} ⌄')
                    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    lbl.setFont(f_cjk)
                    lbl.setCursor(Qt.CursorShape.PointingHandCursor)
                    lbl.setStyleSheet(f'background:{rowbg};color:{normal};border:none;')
                    lbl.on_clicked(lambda e, ident=d.id, lbl=lbl: self._wave_menu(ident, lbl))
                    self.table.setCellWidget(i, 2, lbl)
                    wave_width = max(wave_width, lbl.sizeHint().width() + 8)
                else:
                    self.table.takeItem(i, 2)
                    seg = MiniSegmented(command=lambda v, ident=d.id: self._set_row_wave(ident, v))
                    seg.set_state(values, current)
                    row_height = max(48, seg.height() + 8)
                    wave_width = max(wave_width, seg.width() + 6)
                    wrap = QWidget()
                    hl = QHBoxLayout(wrap)
                    hl.setContentsMargins(0, 0, 0, 0)
                    hl.addStretch(1)
                    hl.addWidget(seg)
                    hl.addStretch(1)
                    wrap.setStyleSheet(f'background:{rowbg};border:none;')
                    self.table.setCellWidget(i, 2, wrap)
            else:
                self.table.takeItem(i, 2)
                self.table.setCellWidget(i, 2, None)
            self.table.setRowHeight(i, row_height)
        self.table.setColumnWidth(2, wave_width)
        self.show_source()

    def _update_row_metrics(self, row, dataset, result):
        error = result['relative_error'] if result else None
        values = (
            (f"{result['dmax']:.4f}%", distortion_grade(result['dmax'])[2]),
            (str(result['turns']['count']), turning_grade(result['turns']['count'])[2]),
            (f"{error:.1f}%" if error is not None else '—', fit_grade(error)[2]),
        ) if result else [('—', MUTED)] * 3
        for col, (text, color) in enumerate(values, 3):
            cell = self.table.item(row, col)
            cell.setText(text)
            cell.setForeground(QColor(color if dataset.visible else '#8a9aa5'))

    def _set_row_wave(self, ident, w):
        row = next((i for i, d in enumerate(self.model.items) if d.id == ident), None)
        if row is None:
            return
        d = self.model.items[row]
        if w not in d.curves or d.effective_wave(self.wave) == w:
            return
        result = d.result(w)
        d.wave_sel = w
        cell = self.table.cellWidget(row, 2)
        if isinstance(cell, ClickLabel):
            cell.setText(f'{wave_nm(w)} ⌄')
        elif cell is not None:
            cell.findChild(MiniSegmented).set_state(d.own_waves(), w)
        self._update_row_metrics(row, d, result)
        self._update_kpi()
        for dataset, design, fit, markers in self._chart_lines:
            if dataset is not d:
                continue
            for line, points in ((design, result['samples']), (fit, result['fit'])):
                line.set_data([p[1] for p in points], [p[0] for p in points])
            turns = result['turns']['points']
            while len(markers) > len(turns):
                markers.pop().remove()
            for i, point in enumerate(turns):
                xy = (point['distortion'], point['rho'])
                if i < len(markers):
                    markers[i].set_offsets([xy])
                else:
                    markers.append(self.ax.scatter(*xy, s=52, facecolor='white',
                        edgecolor=design.get_color(), linewidth=1.5,
                        visible=design.get_visible(), zorder=7 if ident == self._selected_id else 4))
            self.ax.relim()
            self.ax.autoscale_view(scalex=True, scaley=False)
            self._reset_hover_readout()
            self._paint_curve_change()
            break

    def _wave_menu(self, ident, anchor):
        d = next((d for d in self.model.items if d.id == ident), None)
        if d is None:
            return
        current = d.effective_wave(self.wave)
        menu = QMenu(self)
        for w in d.own_waves():
            act = menu.addAction(('✓  ' if w == current else '　　') + wave_nm(w))
            act.triggered.connect(lambda checked=False, w=w: self._set_row_wave(ident, w))
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))

    # ===== 表格交互 =====

    def _on_row_click(self, it):
        d = self.model.items[it.row()]
        if it.column() == 0:
            # 序号列：切换该条数据显示
            d.visible = not d.visible
            if not d.visible and self._selected_id == d.id:
                self._selected_id = None
            self.refresh()
            return
        # 立即切换选中状态（双击改名在 _on_row_double_click 里会重新选中，无副作用）
        self._selected_id = None if self._selected_id == d.id or not d.visible else d.id
        self.show_source(rebuild_plot=False)

    def _on_row_double_click(self, it):
        if it is None or it.column() != 1:
            return
        d = self.model.items[it.row()]
        self._selected_id = d.id
        self.show_source(rebuild_plot=False)
        self._ask_rename(d)

    def _context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row is None or not (0 <= row < len(self.model.items)):
            return
        d = self.model.items[row]
        self._selected_id = d.id
        self.show_source(rebuild_plot=False)
        menu = QMenu(self)
        menu.addAction('修改图例备注', lambda: self._ask_rename(d))
        menu.addAction('只显示此条', lambda: self._solo(d.id))
        menu.addSeparator()
        menu.addAction('移除', self.remove_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _set_hover(self, ident):
        if ident == self._hover_id:
            return
        prev, self._hover_id = self._hover_id, ident
        self._update_row_backgrounds({prev, ident})

    def _update_row_backgrounds(self, idents=None):
        # Selection and hover share a single repaint path, including embedded cells.
        for row, d in enumerate(self.model.items):
            if idents is not None and d.id not in idents:
                continue
            rowbg = self._row_bg(d)
            for c in range(6):
                it = self.table.item(row, c)
                if it is not None:
                    it.setBackground(QColor(rowbg))
            wcell = self.table.cellWidget(row, 2)
            if wcell is not None:
                wcell.setStyleSheet(f'background:{rowbg};border:none;')
                if isinstance(wcell, QLabel):
                    disabled = '#8a9aa5'
                    wcell.setStyleSheet(f'background:{rowbg};color:{INK if d.visible else disabled};border:none;')
        self.table.viewport().update()

    def _ask_rename(self, d):
        name = ask_rename(self, d.name)
        if name:
            self.model.rename(d.id, name)
            self.refresh()

    def remove_selected(self):
        if self._selected_id is None:
            return
        self.model.remove([self._selected_id])
        self._selected_id = None
        self.refresh()

    def clear_all(self):
        if not self.model.items:
            return
        if QMessageBox.question(self, '清空数据', '确定清空所有已导入的数据？此操作不可撤销。') != QMessageBox.StandardButton.Yes:
            return
        self.model.items.clear()
        self._selected_id = None
        self.refresh()

    def _solo(self, ident):
        for d in self.model.items:
            d.visible = (d.id == ident)
            if d.visible:
                d._vis_d = d._vis_f = True
        if self._selected_id != ident:
            self._selected_id = None
        self.refresh()

    def show_source(self, rebuild_plot=True):
        self._update_row_backgrounds()
        self.data_title.setText('数据')
        self._update_kpi()
        if rebuild_plot:
            self.redraw()
        else:
            self._apply_line_styles()
            self._paint_selection()

    def _remember_plot_frame(self, event):
        if event.canvas is not self.mpl_canvas or event.canvas.is_saving():
            return
        self._frame_axes = getattr(self, 'ax', None)
        self._frame_renderer = event.renderer
        self._plain_plot = (event.canvas.copy_from_bbox(self.ax.bbox)
                            if self._frame_axes is not None and self._selected_id is None else None)

    def _frame_is_current(self):
        canvas = self.mpl_canvas
        return (self._frame_axes is self.ax and self._frame_renderer is canvas.get_renderer()
                and not canvas._draw_pending and not self._resize_pending)

    def _paint_selection(self):
        if self._plain_plot is None or not self._frame_is_current():
            self._paint_curve_change()
            return
        self.mpl_canvas.restore_region(self._plain_plot)
        for dataset, design, fit, markers in self._chart_lines:
            if dataset.id == self._selected_id:
                for artist in (fit, design, *markers):
                    self.ax.draw_artist(artist)
                break
        self.mpl_canvas.blit(self.ax.bbox)

    def _paint_curve_change(self):
        # Keep the legend pixels while repainting the axes, including changed ticks.
        self._plain_plot = None
        canvas = self.mpl_canvas
        legend = getattr(self, '_active_legend', None)
        if legend is None or not self._frame_is_current():
            canvas.draw_idle()
            return
        renderer = self._frame_renderer
        left = math.floor(legend.get_window_extent(renderer).x0)
        if left <= self.ax.bbox.x1 or left >= self.fig.bbox.width:
            canvas.draw_idle()
            return
        legend_strip = Bbox.from_extents(left, 0, self.fig.bbox.width, self.fig.bbox.height)
        saved = canvas.copy_from_bbox(legend_strip)
        self.fig.patch.draw(renderer)
        legend.set_visible(False)
        try:
            self.ax.draw(renderer)
        finally:
            legend.set_visible(True)
        canvas.restore_region(saved)
        if self._selected_id is None:
            self._plain_plot = canvas.copy_from_bbox(self.ax.bbox)
        canvas.blit(self.fig.bbox)

    # ===== 图表 =====

    def _reset_hover_readout(self):
        self.hover_x.setText('—')
        self.hover_y.setText('—')

    def on_motion(self, event):
        has_curve = any(dl.get_visible() or fl.get_visible() for _, dl, fl, _ in self._chart_lines)
        if (has_curve and event.inaxes is not None and event.inaxes is getattr(self, 'ax', None)
                and event.xdata is not None and event.ydata is not None):
            self.hover_x.setText(f'{event.xdata:.4f}%')
            self.hover_y.setText(f'{event.ydata:.4f}')
        else:
            self._reset_hover_readout()

    def on_legend_pick(self, event):
        # One physical click toggles once, even when overlapping artists are picked.
        if getattr(event.mouseevent, 'name', '') != 'button_press_event':
            return
        if event.mouseevent is self._last_legend_mouseevent:
            return
        if (hasattr(event.mouseevent, 'x') and hasattr(self, '_legend_clip_bbox')
                and not self._legend_clip_bbox.contains(event.mouseevent.x, event.mouseevent.y)):
            return
        for idx, (artists, target) in enumerate(getattr(self, '_legend_toggle', [])):
            if event.artist in artists:
                self._last_legend_mouseevent = event.mouseevent
                self._toggle_legend_item(idx)
                return

    def _toggle_legend_item(self, idx):
        if not getattr(self, '_legend_toggle', []):
            return
        artists, target = self._legend_toggle[idx]
        visible = not target.get_visible()
        target.set_visible(visible)
        for d, dl, fl, scs in getattr(self, '_chart_lines', []):
            if target is dl:
                for sc in scs:
                    sc.set_visible(visible)
                d._vis_d = visible  # 隐藏状态挂到数据对象上，重绘后保留
            elif target is fl:
                d._vis_f = visible
        self._apply_line_styles()
        # 复选框状态跟随曲线可见性，重建图例刷新勾选框
        if not any(target is not None and target.get_visible() for target in self._legend_targets):
            self._reset_hover_readout()
        if getattr(self, 'ax', None) is not None:
            self._make_legend(self.ax)
        self.mpl_canvas.draw_idle()

    def on_legend_scroll(self, event):
        if (self.legend_scroll.maximum() > 0 and event.x is not None and event.y is not None
                and event.x >= self._legend_left - 8
                and self._legend_clip_bbox.contains(event.x, event.y)):
            self.legend_scroll.setValue(self.legend_scroll.value() - round(event.step * 40))

    def _position_legend(self, value=None):
        leg = getattr(self, '_active_legend', None)
        if leg is None:
            return
        width, height = self.fig.bbox.size
        scale = self.mpl_canvas.device_pixel_ratio
        overflow = self.legend_scroll.maximum() > 0
        top = height + (self.legend_scroll.value() - 14) * scale if overflow else (height + self._legend_height) / 2
        right = width - (22 if overflow else 5) * scale
        leg.set_bbox_to_anchor((right / width, top / height), transform=self.fig.transFigure)
        self.mpl_canvas.draw_idle()

    def _legend_hover_text(self, x, y):
        leg = getattr(self, '_active_legend', None)
        if leg is None or x < self._legend_left or not self._legend_clip_bbox.contains(x, y):
            return ''
        renderer = self.fig.canvas.get_renderer()
        for artists, handle in zip(self._legend_toggle, self._legend_handles):
            parts = artists[0]
            if parts[-1].get_text() != handle.get_label():
                box = Bbox.union([part.get_window_extent(renderer) for part in parts])
                if box.contains(x, y):
                    return handle.get_label()
        return ''

    def _apply_line_styles(self):
        # 所有曲线默认同等亮度；选中行对应的曲线仅加粗作为提醒，不压暗其他曲线
        lines = getattr(self, '_chart_lines', [])
        if not lines:
            return
        sel = self._selected_id
        for d, dl, fl, scs in lines:
            on = (sel is None) or (d.id == sel)
            dl.set_alpha(1.0)
            dl.set_linewidth(4.0 if (sel and on) else 2.6)
            dl.set_zorder(6 if (sel and on) else 3)
            fl.set_alpha(1.0)
            fl.set_linewidth(3.0 if (sel and on) else 2.0)
            fl.set_zorder(5 if (sel and on) else 2)
            for sc in scs:
                sc.set_alpha(1.0)
                sc.set_zorder(7 if (sel and on) else 4)

    def show_all_lines(self):
        restore_rows = any(not d.visible for d in self.model.items)
        for d in self.model.items:
            d.visible = d._vis_d = d._vis_f = True
        if restore_rows:
            self.refresh()
            return
        for d, dl, fl, scs in getattr(self, '_chart_lines', []):
            dl.set_visible(True)
            fl.set_visible(True)
            for sc in scs:
                sc.set_visible(True)
        self._apply_line_styles()
        if getattr(self, 'ax', None) is not None:
            self._make_legend(self.ax)
        self.mpl_canvas.draw_idle()

    def _make_legend(self, ax):
        # 重建图例复选框及单击响应。redraw 与显隐切换后调用。
        handles = getattr(self, '_legend_handles', [])
        targets = getattr(self, '_legend_targets', [])
        # Legend handles are proxies, not the plotted lines. The custom checkbox
        # handler must receive the current target state on every legend rebuild.
        for handle, target in zip(handles, targets):
            if target is not None:
                handle.set_visible(target.get_visible())
        old = ax.get_legend()
        if old is not None:
            old.remove()
        compact = self.mpl_canvas.width() < 680
        leg = ax.legend(handles=handles, labels=[h.get_label() for h in handles],
                        loc='upper right', bbox_to_anchor=(.995, .98),
                        bbox_transform=self.fig.transFigure,
                        ncol=2, frameon=False, handler_map={Line2D: _CheckHandler()},
                        fontsize=11.52, handlelength=2.1 if compact else 3.0,
                        handletextpad=.35 if compact else .6,
                        columnspacing=.55 if compact else 1.2, labelspacing=.7, borderaxespad=0)
        # The legend must never participate in the curve axes' vertical layout.
        leg.set_in_layout(False)
        self._active_legend = leg
        renderer = self.fig.canvas.get_renderer()
        texts = leg.get_texts()
        for text in texts:
            text.set_parse_math(False)
        extent = leg.get_window_extent(renderer)
        self._legend_height = extent.height
        width, height = self.fig.bbox.size
        scale = self.mpl_canvas.device_pixel_ratio
        viewport_height = max(1, self.mpl_canvas.height() - 28)
        self.legend_scroll.blockSignals(True)
        self.legend_scroll.setRange(0, max(0, math.ceil(extent.height / scale - viewport_height)))
        self.legend_scroll.setPageStep(viewport_height)
        self.legend_scroll.blockSignals(False)
        overflow = self.legend_scroll.maximum() > 0
        self.legend_scroll.setGeometry(self.mpl_canvas.width() - 12, 14, 12, viewport_height)
        self.legend_scroll.setVisible(overflow)
        self.legend_scroll.raise_()
        # Use renderer pixels for text measurement, axes and clipping. Qt's scrollbar
        # uses logical pixels. Reserve at least half of the canvas for axes/margins.
        right = width - (22 if overflow else 5) * scale
        budget = right - width * .50 - 14 * scale
        if extent.width > budget and texts:
            cols = (texts[:len(texts)//2], texts[len(texts)//2:])
            natural = [max(t.get_window_extent(renderer).width for t in col) for col in cols]
            available = max(0, budget - (extent.width - sum(natural)) - 2 * scale)
            for i, col in enumerate(cols):
                limit = max(available / 2, available - natural[1-i])
                for text in col:
                    original = text.get_text()
                    if text.get_window_extent(renderer).width <= limit:
                        continue
                    lo, hi = 0, len(original)
                    while lo < hi:
                        keep = (lo + hi + 1) // 2
                        text.set_text(original[:(keep+1)//2] + '…' + original[len(original)-keep//2:])
                        if text.get_window_extent(renderer).width <= limit:
                            lo = keep
                        else:
                            hi = keep - 1
                    text.set_text(original[:(lo+1)//2] + '…' + original[len(original)-lo//2:])
            extent = leg.get_window_extent(renderer)
        self._legend_clip_bbox = Bbox.from_bounds(0, 14 * scale, width - (16 if overflow else 0) * scale, viewport_height * scale)
        for artist in leg.findobj():
            artist.set_clip_box(self._legend_clip_bbox)
            artist.set_clip_on(True)
        self._legend_left = right - extent.width
        self._position_legend()
        self._legend_toggle = []
        for (art_h, art_t), target in zip(zip(leg.legend_handles, leg.get_texts()), targets):
            if target is None:
                continue
            group = art_h if isinstance(art_h, list) else [art_h]  # 自定义 handler 返回的是列表
            for a in group:
                a.set_picker(8)
            art_t.set_picker(8)
            self._legend_toggle.append((group + [art_t], target))
        return leg

    def _resize_redraw(self):
        # 窗口/图表尺寸变化后重算图例右侧留白（redraw 不改变控件尺寸，不会循环）
        self._resize_pending = False
        self.redraw()

    def redraw(self):
        self._reset_hover_readout()
        fig = self.fig
        fig.clear()
        self.ax = ax = fig.add_subplot(111)
        ax.set_facecolor('white')
        results = [(d, w, r) for d, w, r in self.row_results(self.wave)]
        if not results:
            self._legend_toggle = []
            self._legend_handles = []
            self._legend_targets = []
            self._active_legend = None
            self.legend_scroll.hide()
            self._chart_lines = []
            ax.text(.5, .58, '暂无数据', ha='center', va='center', color='#c9c9d1', fontsize=22, weight='bold')
            ax.text(.5, .42, '在 ZEMAX 中导出 F-Tan(Theta) 畸变文本后，\n点击上方「选择 TXT 文件」或「粘贴 TXT 文本」导入',
                    ha='center', va='center', color=MUTED, fontsize=11, linespacing=1.9)
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_visible(False)
            fig.tight_layout()
            self.mpl_canvas.draw_idle()
            return
        handles = []
        targets = []
        design_lines = []
        fit_lines = []
        scatter_lines = []
        for d, w, r in results:
            # Production IDs are monotonically increasing import serials.
            color_index = (int(d.id) - 1 if d.id.isdecimal() else sum(d.id.encode('utf-8'))) % len(COLORS)
            color = COLORS[color_index]
            fitc = TINTS[color_index]
            # 拟合线先画、用同族浅色，归属一目了然
            fitl, = ax.plot([v[1] for v in r['fit']], [v[0] for v in r['fit']], color=fitc, lw=2,
                            solid_capstyle='round', solid_joinstyle='round', zorder=2)
            dl, = ax.plot([v[1] for v in r['samples']], [v[0] for v in r['samples']], color=color, lw=2.6,
                          solid_capstyle='round', solid_joinstyle='round', zorder=3)
            scs = [ax.scatter([p['distortion']], [p['rho']], s=52, facecolor='white', edgecolor=color,
                              linewidth=1.5, zorder=4) for p in r['turns']['points']]
            # 恢复上次取消勾选的隐藏状态（图例显隐在重绘后保留）
            fitl.set_visible(getattr(d, '_vis_f', True))
            dl.set_visible(getattr(d, '_vis_d', True))
            if not dl.get_visible():
                for sc in scs:
                    sc.set_visible(False)
            design_lines.append(dl)
            fit_lines.append(fitl)
            scatter_lines.append(scs)
            handles.append(Line2D([0], [0], color=color, lw=2.6, label=d.name))
            targets.append(dl)
        for (d, _, _), line in zip(results, fit_lines):
            handles.append(Line2D([0], [0], color=line.get_color(), lw=2, label=f'拟合（{d.name}）'))
            targets.append(line)
        # 图例放图表右侧，两列：左列待拟合、右列拟合
        self._legend_handles = handles
        self._legend_targets = targets
        ax.set_ylim(0, 1.025)
        ax.margins(x=.10)
        ax.set_xlabel('径向畸变（%）', fontsize=11.52, color=INK)
        ax.set_ylabel('归一化半径', fontsize=11.52, color=INK)
        ax.grid(True, color='#e0e8ed', linewidth=.8)
        ax.set_axisbelow(True)
        ax.tick_params(colors=MUTED, labelsize=11.52)
        for _lbl in ax.get_xticklabels() + ax.get_yticklabels():
            _lbl.set_fontfamily(SERIF_MPL)
        for spine in ax.spines.values():
            spine.set_color('#8195a1')
        leg = self._make_legend(ax)
        self._chart_lines = [(d, dl, fl, scs) for (d, _, _), dl, fl, scs in
                             zip(results, design_lines, fit_lines, scatter_lines)]
        self._apply_line_styles()
        fig.tight_layout()
        # 量出图例实际像素宽度，坐标轴右缘精确让到图例左侧，始终紧贴
        right_px = self._legend_left - 14 * self.mpl_canvas.device_pixel_ratio
        fig.subplots_adjust(right=right_px / fig.bbox.width)
        self.mpl_canvas.draw_idle()

    # ===== 导出 =====

    def _save_plot(self, path, format, dpi=None):
        # Exports include the complete legend, regardless of its scroll position.
        fig, leg = self.fig, getattr(self, '_active_legend', None)
        size, position = fig.get_size_inches().copy(), self.ax.get_position().frozen()
        clip_states = [(a, a.get_clip_on(), a.get_clip_box()) for a in leg.findobj()] if leg else []
        screen_labels = [text.get_text() for text in leg.get_texts()] if leg else []
        try:
            if leg is not None:
                for text, handle in zip(leg.get_texts(), self._legend_handles):
                    full = handle.get_label()
                    text.set_text('\n'.join(full[i:i+64] for i in range(0, len(full), 64)))
                bounds = leg.get_window_extent(fig.canvas.get_renderer())
                old_width, old_height = size * fig.dpi
                scale = self.mpl_canvas.device_pixel_ratio
                width = max(old_width, position.x1 * old_width + bounds.width + 24 * scale)
                height = max(old_height, bounds.height + 28 * scale)
                fig.set_size_inches(width / fig.dpi, height / fig.dpi, forward=False)
                self.ax.set_position([position.x0 * old_width / width,
                                      (position.y0 * old_height + (height - old_height) / 2) / height,
                                      position.width * old_width / width, position.height * old_height / height])
                for artist, _, _ in clip_states:
                    artist.set_clip_on(False)
                leg.set_bbox_to_anchor((1 - 5 * scale / width, (1 + bounds.height / height) / 2), transform=fig.transFigure)
            fig.savefig(path, format=format, dpi=dpi, facecolor='white')
        finally:
            fig.set_size_inches(*size, forward=False)
            self.ax.set_position(position)
            if leg is not None:
                for text, label in zip(leg.get_texts(), screen_labels):
                    text.set_text(label)
            for artist, enabled, box in clip_states:
                artist.set_clip_box(box)
                artist.set_clip_on(enabled)
            self._position_legend()

    def export_svg(self):
        results = self.row_results(self.wave)
        if not results:
            QMessageBox.information(self, '没有曲线', '请先导入要展示的数据。')
            return
        path, _ = QFileDialog.getSaveFileName(self, '保存当前叠加图', '畸变曲线对比.svg', '矢量图 (*.svg)')
        if not path:
            return
        self._save_plot(path, 'svg')

    def export_png(self):
        results = self.row_results(self.wave)
        if not results:
            QMessageBox.information(self, '没有曲线', '请先导入要展示的数据。')
            return
        path, _ = QFileDialog.getSaveFileName(self, '保存当前叠加图', '畸变曲线对比.png', 'PNG 图片 (*.png)')
        if not path:
            return
        self._save_plot(path, 'png', dpi=200)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--smoke-test')
    parser.add_argument('--check-data')
    parser.add_argument('--preview')
    parser.add_argument('--startup-self-test', action='store_true')
    parser.add_argument('--native-runtime-check')
    args = parser.parse_args()
    if args.check_data:
        model = Collection()
        a = model.add_bytes(SAMPLE.read_bytes(), 'sample.txt')[0]
        b = model.add_text(SAMPLE.read_text(encoding='utf-16'), 'paste')[0]
        rows = []
        for wave in model.waves():
            result = a.result(wave)
            assert result['turns']['count'] == 1 and result['terms'] == 2
            assert abs(result['max_error'] - b.result(wave)['max_error']) < 1e-12
            rows.append({'wave': wave, 'maximum_percent': result['dmax'], 'turns': result['turns']['count'],
                         'terms': result['terms'], 'max_error_pp': result['max_error'],
                         'relative_error_percent': result['relative_error']})
        assert distortion_grade(.5)[0] == 'green' and distortion_grade(1)[0] == 'yellow' and distortion_grade(1.01)[0] == 'red'
        assert turning_grade(1)[0] == 'green' and turning_grade(2)[0] == 'yellow' and turning_grade(3)[0] == 'red'
        assert fit_grade(5)[0] == 'green' and fit_grade(5.01)[0] == 'yellow' and fit_grade(10)[0] == 'yellow' and fit_grade(10.01)[0] == 'red'
        Path(args.check_data).write_text(json.dumps({'ok': True, 'results': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
        return
    if args.smoke_test:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    elif args.native_runtime_check:
        os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
    app = QApplication(sys.argv)
    _register_qt_fonts()
    app.setFont(_app_font())
    if args.native_runtime_check:
        from startup_splash import close_startup
        close_startup()
        data = {'ok': app.platformName() == 'windows' and QFontInfo(app.font()).family() == SERIF_CJK,
                'platform': app.platformName(), 'font': QFontInfo(app.font()).family(),
                'plugin_paths': app.libraryPaths()}
        Path(args.native_runtime_check).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os._exit(0)
    win = App()
    if args.demo:
        QTimer.singleShot(100, win.load_sample)
    if args.smoke_test:
        def smoke():
            data = {}
            try:
                from types import SimpleNamespace
                win.redraw()
                win.on_motion(SimpleNamespace(inaxes=win.ax, xdata=.5, ydata=.25))
                assert win.hover_x.text() == '—' and win.hover_y.text() == '—'
                file_errors, file_dialogs = [], []
                def confirm_file_dialog():
                    dialog = app.activeModalWidget()
                    try:
                        assert isinstance(dialog, PasteDialog)
                        file_dialogs.append(dialog.source_path.name)
                        assert dialog.text_edit.toPlainText() == SAMPLE.read_text(encoding='utf-16')
                        assert dialog.name_edit.text() == '' and not dialog.submit_btn.isEnabled()
                        assert dialog.focusWidget() is dialog.name_edit
                        if len(file_dialogs) == 1:
                            if args.preview:
                                image = QPixmap(dialog.size())
                                dialog.render(image)
                                assert image.save(str(Path(args.preview).parent / 'import_dialog_preview.png'))
                            dialog.name_edit.setText('300mm')
                            assert dialog.submit_btn.isEnabled()
                            dialog.submit_btn.click()
                            QTimer.singleShot(0, confirm_file_dialog)
                        else:
                            dialog.reject()
                    except Exception:
                        import traceback
                        file_errors.append(traceback.format_exc())
                        if isinstance(dialog, QDialog):
                            dialog.reject()
                QTimer.singleShot(0, confirm_file_dialog)
                win.add_files([str(SAMPLE), str(SAMPLE)])
                assert not file_errors, file_errors
                assert len(file_dialogs) == 2
                assert len(win.model.items) == 1
                assert win.model.items[0].name == '300mm'
                assert win.model.items[0].filename == SAMPLE.name
                win.on_motion(SimpleNamespace(inaxes=win.ax, xdata=.5, ydata=.25))
                assert win.hover_x.text() == '0.5000%' and win.hover_y.text() == '0.2500'
                saved = win.model.items[:]
                win.model.items.clear()
                win.refresh()
                assert win.hover_x.text() == '—' and win.hover_y.text() == '—'
                win.on_motion(SimpleNamespace(inaxes=win.ax, xdata=.5, ydata=.25))
                assert win.hover_x.text() == '—' and win.hover_y.text() == '—'
                win.model.items.extend(saved)
                win.refresh()
                dlg = PasteDialog(win)
                dlg.show()
                app.processEvents()
                assert dlg.focusWidget() is dlg.text_edit
                assert app.focusWidget() is dlg.text_edit
                dlg.name_edit.setText('600 mm')
                assert not dlg.submit_btn.isEnabled()
                dlg.text_edit.setPlainText(SAMPLE.read_text(encoding='utf-16'))
                assert dlg.submit_btn.isEnabled()
                dlg.submit_btn.click()
                assert len(win.model.items) == 2
                dlg2 = PasteDialog(win)
                dlg2.text_edit.setPlainText(SAMPLE.read_text(encoding='utf-16'))
                assert not dlg2.submit_btn.isEnabled()
                dlg2.submit()
                assert len(win.model.items) == 2
                dlg2.name_edit.setText('   ')
                assert not dlg2.submit_btn.isEnabled()
                dlg2.submit()
                assert len(win.model.items) == 2
                dlg2.name_edit.setText('900')
                assert dlg2.submit_btn.isEnabled()
                dlg2.submit_btn.click()
                assert win.model.items[-1].name == '900'
                captured = []
                win._ask_rename = lambda d: captured.append(d.id)
                for column in (0, 2, 3, 4, 5):
                    win._on_row_double_click(win.table.item(0, column))
                assert not captured
                win._on_row_double_click(win.table.item(0, 1))
                assert captured == [win.model.items[0].id]
                win._selected_id = None
                win.show_source()
                captured.clear()
                mouse = SimpleNamespace(name='button_press_event', dblclick=False)
                old_artists = list(win._legend_toggle[0][0])
                win.on_legend_pick(SimpleNamespace(mouseevent=mouse, artist=old_artists[0]))
                assert not win._chart_lines[0][1].get_visible()
                win.on_legend_pick(SimpleNamespace(mouseevent=mouse, artist=old_artists[-1]))
                assert not win._chart_lines[0][1].get_visible()
                win.on_legend_pick(SimpleNamespace(
                    mouseevent=SimpleNamespace(name='button_press_event', dblclick=True),
                    artist=win._legend_toggle[0][0][0]))
                assert win._chart_lines[0][1].get_visible() and not captured
                del win._ask_rename
                win.wave = '0.48 μm'
                win.refresh()
                app.processEvents()
                win.mpl_canvas.draw()
                assert win.table.rowCount() == 3 and len(win.model.visible_results(win.wave)) == 3
                assert len(win.ax.get_lines()) == 6
                assert win.table.columnCount() == 6
                assert win.fit_label.text().endswith('%') and any(g in win.fit_grade.text() for g in ('较好', '需关注', '较差'))
                assert len(win._chart_lines) == 3
                first = win.model.items[0].id
                kpi_widgets = win.findChildren(QLabel, 'kpi_heading')
                kpi_values = [win.max_label, win.max_grade, win.turn_label, win.turn_grade,
                              win.fit_label, win.fit_grade]
                def kpi_geometry():
                    return [(widget.mapTo(win, QPoint(0, 0)).toTuple(),
                             widget.width(), widget.height()) for widget in kpi_widgets]
                def assert_kpi_centered():
                    for heading, num, grade in zip(kpi_widgets, kpi_values[::2], kpi_values[1::2]):
                        left = num.mapTo(win, QPoint(0, 0)).x()
                        right = grade.mapTo(win, QPoint(grade.width(), 0)).x()
                        center = heading.mapTo(win, QPoint(0, 0)).x() + heading.width() / 2
                        assert abs((left + right) / 2 - center) <= 1
                kpi_baseline = kpi_geometry()
                saved_text = [widget.text() for widget in kpi_values]
                assert_kpi_centered()
                for widget, text in zip(kpi_values,
                                        ['99.99999%', '（超过 1%）', '123', '（超过 2 个）',
                                         '100.0%', '（需关注）']):
                    widget.setText(text)
                app.processEvents()
                assert kpi_geometry() == kpi_baseline
                assert_kpi_centered()
                for widget, text in zip(kpi_values, saved_text):
                    widget.setText(text)
                app.processEvents()
                assert kpi_geometry() == kpi_baseline
                assert_kpi_centered()
                grade_table = win.findChild(GradeTable)
                assert [grade_table.layout().cellRect(row, 0).height()
                        for row in (0, 1, 3, 5)] == [32] * 4
                def click_row(row):
                    item = win.table.item(row, 1)
                    pos = win.table.visualItemRect(item).center()
                    local = QPointF(pos)
                    global_pos = QPointF(win.table.viewport().mapToGlobal(pos))
                    for kind, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                                          (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
                        event = QMouseEvent(kind, local, global_pos, Qt.MouseButton.LeftButton,
                                            buttons, Qt.KeyboardModifier.NoModifier)
                        app.sendEvent(win.table.viewport(), event)
                    app.processEvents()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    app.processEvents()
                    assert kpi_geometry() == kpi_baseline
                    assert_kpi_centered()
                def click_wave(row, column):
                    viewport = win.table.viewport()
                    seg = win.table.cellWidget(row, 2).findChild(MiniSegmented)
                    assert seg is not None
                    pos = seg.mapTo(viewport, QPoint(column * seg.SEG_W + seg.SEG_W // 2,
                                                    seg.SEG_H // 2))
                    assert viewport.childAt(pos) is seg
                    for kind, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                                          (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
                        target = viewport.childAt(pos)
                        event = QMouseEvent(kind, QPointF(target.mapFrom(viewport, pos)),
                                            QPointF(viewport.mapToGlobal(pos)), Qt.MouseButton.LeftButton,
                                            buttons, Qt.KeyboardModifier.NoModifier)
                        app.sendEvent(target, event)
                        app.processEvents()
                        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                        app.processEvents()
                    return win.table.cellWidget(row, 2).findChild(MiniSegmented)
                axes_before_wave, legend_before_wave = win.ax, win._active_legend
                other_wave_cell = win.table.cellWidget(1, 2)
                first_design = win._chart_lines[0][1]
                wave_control = click_wave(0, 0)
                assert win.ax is axes_before_wave and win._active_legend is legend_before_wave
                assert win.table.cellWidget(1, 2) is other_wave_cell
                assert win._chart_lines[0][1] is first_design
                assert win.model.items[0].effective_wave(win.wave) == '0.44 μm'
                assert wave_control.current == '0.44 μm'
                assert win.model.items[1].effective_wave(win.wave) == '0.48 μm'
                assert list(win._chart_lines[0][1].get_xdata()) == [
                    point[1] for point in win.model.items[0].result('0.44 μm')['samples']]
                click_wave(0, 2)
                click_row(0)
                assert win._selected_id == first
                assert win.table.item(0, 1).background().color().name() == '#e3edfd'
                sample_point = win.table.visualItemRect(win.table.item(0, 0)).topLeft() + QPoint(3, 8)
                table_image = win.table.viewport().grab().toImage()
                table_image.save(str(Path(args.smoke_test).parent / 'table_highlight.png'))
                assert table_image.pixelColor(sample_point).name() == '#e3edfd', table_image.pixelColor(sample_point).name()
                assert '#e3edfd' in win.table.cellWidget(0, 2).styleSheet()
                assert win._chart_lines[0][1].get_linewidth() == 4.0 and win._chart_lines[1][1].get_linewidth() == 2.6
                assert win._chart_lines[0][1].get_zorder() > win._chart_lines[1][1].get_zorder()
                assert all(dl.get_alpha() == 1.0 and fl.get_alpha() == 1.0 for _, dl, fl, _ in win._chart_lines)
                click_wave(0, 1)
                assert win.model.items[0].effective_wave(win.wave) == '0.46 μm'
                assert win._selected_id == first
                assert win.table.item(0, 1).background().color().name() == '#e3edfd'
                click_wave(0, 2)
                click_row(1)
                assert win._selected_id == win.model.items[1].id
                assert win.table.item(1, 1).background().color().name() == '#e3edfd'
                assert win.table.item(0, 1).background().color().name() != '#e3edfd'
                assert '#e3edfd' not in win.table.cellWidget(0, 2).styleSheet()
                assert win._chart_lines[1][1].get_linewidth() == 4.0 and win._chart_lines[0][1].get_linewidth() == 2.6
                click_wave(1, 0)
                assert win.model.items[1].effective_wave(win.wave) == '0.44 μm'
                assert win.model.items[0].effective_wave(win.wave) == '0.48 μm'
                assert win._selected_id == win.model.items[1].id
                click_wave(1, 2)
                click_row(1)
                assert win._selected_id is None
                assert all(win.table.item(i, 1).background().color().name() != '#e3edfd'
                           for i in range(3))
                assert win._chart_lines[0][1].get_linewidth() == 2.6
                click_row(0)
                axes_before_blank, legend_before_blank = win.ax, win._active_legend
                viewport = win.table.viewport()
                blank_pos = QPoint(20, win.table.visualItemRect(win.table.item(2, 1)).bottom() + 20)
                assert viewport.rect().contains(blank_pos)
                assert not win.table.indexAt(blank_pos).isValid()
                for kind, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                                      (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
                    app.sendEvent(viewport, QMouseEvent(
                        kind, QPointF(blank_pos), QPointF(viewport.mapToGlobal(blank_pos)),
                        Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))
                assert win._selected_id is None
                assert win.kpi_scope.text() == '全部数据 · 各项最差'
                assert all(win.table.item(i, 1).background().color().name() != '#e3edfd'
                           for i in range(3))
                assert all(dl.get_linewidth() == 2.6 for _, dl, _, _ in win._chart_lines)
                assert win.ax is axes_before_blank and win._active_legend is legend_before_blank
                # 图例复选框：取消勾选设计线 → 目标线隐藏，重绘后隐藏状态保留，拟合线不受影响
                assert len(win._legend_toggle[0][0]) == 4  # box + check + line + label
                win._toggle_legend_item(0)
                assert not win._chart_lines[0][1].get_visible()
                assert win._chart_lines[0][2].get_visible()
                assert len(win._legend_toggle[0][0]) == 3  # check mark is actually gone
                win._toggle_legend_item(0)
                assert win._chart_lines[0][1].get_visible()
                assert len(win._legend_toggle[0][0]) == 4
                win._toggle_legend_item(0)
                win._toggle_legend_item(len(win._chart_lines))
                assert not win._chart_lines[0][2].get_visible()
                assert len(win._legend_toggle[len(win._chart_lines)][0]) == 3
                win.redraw()
                assert not win._chart_lines[0][1].get_visible() and not win._chart_lines[0][2].get_visible()
                assert len(win._legend_toggle[0][0]) == 3
                win.show_all_lines()
                assert all(dl.get_visible() and fl.get_visible() and dl.get_alpha() == 1.0 for _, dl, fl, _ in win._chart_lines)
                assert all(len(artists) == 4 for artists, _ in win._legend_toggle)
                win.on_motion(SimpleNamespace(inaxes=win.ax, xdata=.5, ydata=.25))
                for idx in range(len(win._legend_toggle)):
                    win._toggle_legend_item(idx)
                assert win.hover_x.text() == '—' and win.hover_y.text() == '—'
                win.on_motion(SimpleNamespace(inaxes=win.ax, xdata=.5, ydata=.25))
                assert win.hover_x.text() == '—' and win.hover_y.text() == '—'
                win.show_all_lines()
                win._on_row_click(win.table.item(1, 3))
                win._toggle_legend_item(1)
                win._toggle_legend_item(1 + len(win._chart_lines))
                win._on_row_click(win.table.item(1, 0))
                assert win._selected_id is None and not win.model.items[1].visible
                assert win.kpi_scope.text() == '全部数据 · 各项最差'
                assert win.model.items[1].id not in [d.id for d, _, _ in win.row_results(win.wave)]
                win._toggle_legend_item(0)
                win._solo(first)
                assert sum(d.visible for d in win.model.items) == 1
                assert win._chart_lines[0][1].get_visible()
                win.show_all_lines()
                assert all(d.visible and d._vis_d and d._vis_f for d in win.model.items)
                assert len(win._chart_lines) == len(win.model.items)
                assert all(dl.get_visible() and fl.get_visible() and all(sc.get_visible() for sc in scs)
                           for _, dl, fl, scs in win._chart_lines)
                original_items, original_selected = win.model.items, win._selected_id
                def kpi_sample(ident, name, distortion, turns, error):
                    result = {'dmax': distortion, 'turns': {'count': turns}, 'relative_error': error}
                    return SimpleNamespace(id=ident, name=name, visible=True,
                                           effective_wave=lambda wave: wave, result=lambda wave: result)
                def assert_kpi_colors(distortion, turns, error):
                    for number, grade, color in (
                            (win.max_label, win.max_grade, distortion_grade(distortion)[2]),
                            (win.turn_label, win.turn_grade, turning_grade(turns)[2]),
                            (win.fit_label, win.fit_grade, fit_grade(error)[2])):
                        assert 'color:' + color + ';' in number.styleSheet()
                        assert 'color:' + color + ';' in grade.styleSheet()
                try:
                    fixtures = [kpi_sample('a', '600 mm', 1.2, 0, 5),
                                kpi_sample('b', '300', .3, 1, 20),
                                kpi_sample('c', '900mm', .8, 2, None)]
                    win.model.items = fixtures
                    win._selected_id = None
                    win._update_kpi()
                    assert win.kpi_scope.text() == '全部数据 · 各项最差'
                    assert (win.max_label.text(), win.turn_label.text(), win.fit_label.text()) == (
                        '1.20000%', '2', '20.0%')
                    assert (win.max_source.text(), win.turn_source.text(), win.fit_source.text()) == (
                        '来源：600mm', '来源：900mm', '来源：300mm')
                    assert win.max_grade.text() == '（' + distortion_grade(1.2)[1] + '）'
                    assert_kpi_colors(1.2, 2, 20)
                    win._selected_id = 'a'
                    win._update_kpi()
                    assert win.kpi_scope.text() == '当前选中：600 mm'
                    assert (win.max_label.text(), win.turn_label.text(), win.fit_label.text()) == (
                        '1.20000%', '0', '5.0%')
                    assert all(label.text() == '来源：600mm' for label in (
                        win.max_source, win.turn_source, win.fit_source))
                    assert_kpi_colors(1.2, 0, 5)
                    # Repeated refreshes must never introduce a gray animation frame.
                    fixtures[0].result = lambda wave: {
                        'dmax': .35402, 'turns': {'count': 2}, 'relative_error': 12.5}
                    for _ in range(8):
                        win._update_kpi()
                        assert_kpi_colors(.35402, 2, 12.5)
                    app.processEvents()
                    assert_kpi_colors(.35402, 2, 12.5)
                    fixtures[0].result = lambda wave: {
                        'dmax': 1.2, 'turns': {'count': 0}, 'relative_error': 5}
                    win._selected_id = None
                    fixtures[1].visible = False
                    win._update_kpi()
                    assert win.kpi_scope.text() == '全部数据 · 各项最差'
                    assert win.fit_label.text() == '5.0%'
                    assert win.fit_source.text() == '来源：600mm'
                    fixtures[0].visible = False
                    win._update_kpi()
                    assert (win.max_label.text(), win.turn_label.text(), win.fit_label.text()) == (
                        '0.80000%', '2', '—')
                    assert win.fit_source.text() == '来源：—'
                    fixtures[2].visible = False
                    win._update_kpi()
                    assert all(label.text() == '—' for label in (
                        win.max_label, win.turn_label, win.fit_label))
                    assert all(label.text() == '' for label in (
                        win.max_source, win.turn_source, win.fit_source))
                finally:
                    win.model.items, win._selected_id = original_items, original_selected
                    win._update_kpi()
                app.processEvents()
                assert kpi_geometry() == kpi_baseline
                assert_kpi_centered()
                small_label = next(label for label in win.findChildren(QLabel) if label.text() == '归一化半径')
                actual_font = QFontInfo(small_label.font())
                assert small_label.font().pixelSize() == 16
                assert small_label.font().weight() == QFont.Weight.Normal
                assert small_label.font().hintingPreference() == QFont.HintingPreference.PreferNoHinting
                assert small_label.font().styleStrategy() & QFont.StyleStrategy.PreferAntialias
                assert actual_font.family() == SERIF_CJK
                assert 'Bold' in QFontDatabase.styles(SERIF_CJK)
                assert 'Medium' in QFontDatabase.styles(SERIF_CJK)
                headings = win.findChildren(QLabel, 'grade_heading')
                assert len(headings) == 4
                assert all(label.font().pixelSize() == 16 and QFontInfo(label.font()).styleName() == 'Medium' for label in headings)
                assert app.font().pixelSize() == 16 and app.font().weight() == QFont.Weight.Normal
                export_dir = Path(args.smoke_test).resolve().parent / '导出自检'
                export_dir.mkdir(exist_ok=True)
                # Reproduce the reported overflow with 36 datasets. Real wheel and
                # mouse events must reach the last legend row without changing axes height.
                from copy import copy
                from PySide6.QtGui import QWheelEvent
                from matplotlib.backend_bases import MouseEvent
                real_items, real_selection = win.model.items, win._selected_id
                try:
                    many = []
                    for index in range(36):
                        dataset = copy(real_items[0])
                        dataset.id = f'legend-stress-{index}'
                        dataset.name = f'{(index + 1) * 100}mm'
                        many.append(dataset)
                    win._selected_id = None
                    win.model.items = many[:1]
                    win.refresh()
                    app.processEvents()
                    win.redraw()
                    win.mpl_canvas.draw()
                    plot_height = win.ax.get_window_extent().height
                    win.model.items = many
                    win.refresh()
                    app.processEvents()
                    win.redraw()
                    win.mpl_canvas.draw()
                    assert abs(win.ax.get_window_extent().height - plot_height) < 1
                    assert win.legend_scroll.isVisible() and win.legend_scroll.maximum() > 0
                    pos = QPointF((win._legend_left + win.mpl_canvas.width() - 22) / 2,
                                  win.mpl_canvas.height() / 2)
                    wheel = QWheelEvent(pos, QPointF(win.mpl_canvas.mapToGlobal(pos.toPoint())),
                                        QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
                                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
                    QApplication.sendEvent(win.mpl_canvas, wheel)
                    assert win.legend_scroll.value() > 0
                    win.legend_scroll.setValue(win.legend_scroll.maximum())
                    win.mpl_canvas.draw()
                    # Selection updates must reuse the plot and legend, with no
                    # delayed callbacks or full figure rebuilds.
                    from time import perf_counter
                    existing_axes, existing_legend = win.ax, win._active_legend
                    existing_lines = tuple(win.ax.get_lines())
                    saved_redraw = win.redraw
                    def unexpected_redraw():
                        raise AssertionError('Selecting a row rebuilt the plot')
                    win.redraw = unexpected_redraw
                    try:
                        selection_started = perf_counter()
                        win._on_row_click(win.table.item(0, 3))
                        selection_ms = (perf_counter() - selection_started) * 1000
                        assert win._selected_id == many[0].id
                        assert win.table.item(0, 3).background().color().name() == '#e3edfd'
                        assert win._chart_lines[0][1].get_linewidth() == 4.0
                        assert win.ax is existing_axes and win._active_legend is existing_legend
                        assert tuple(win.ax.get_lines()) == existing_lines
                        assert win.legend_scroll.value() == win.legend_scroll.maximum()
                        win._on_row_click(win.table.item(0, 4))
                        assert win._selected_id is None
                        assert win._chart_lines[0][1].get_linewidth() == 2.6
                    finally:
                        win.redraw = saved_redraw
                    win.mpl_canvas.draw()
                    last = win._active_legend.get_texts()[-1].get_window_extent(win.fig.canvas.get_renderer())
                    assert last.y0 >= win._legend_clip_bbox.y0 - 1
                    assert last.y1 <= win._legend_clip_bbox.y1 + 1
                    scroll_value = win.legend_scroll.value()
                    MouseEvent('button_press_event', win.mpl_canvas,
                               (last.x0 + last.x1) / 2, (last.y0 + last.y1) / 2, button=1)._process()
                    assert not win._legend_targets[-1].get_visible()
                    assert win.legend_scroll.value() == scroll_value
                    assert abs(win.ax.get_window_extent().height - plot_height) < 1
                    if args.preview:
                        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                        app.processEvents()
                        stress_image = QPixmap(win.size())
                        win.render(stress_image)
                        assert stress_image.save(str(Path(args.preview).parent / 'many_legend_preview.png'))
                    win._save_plot(export_dir / 'many.png', 'png', dpi=100)
                    exported = QPixmap(str(export_dir / 'many.png'))
                    assert exported.height() > win.mpl_canvas.height()
                    assert win.legend_scroll.value() == scroll_value
                    assert abs(win.ax.get_window_extent().height - plot_height) < 1
                    win._save_plot(export_dir / 'many.svg', 'svg')
                    assert win.legend_scroll.value() == scroll_value
                finally:
                    win.model.items, win._selected_id = real_items, real_selection
                    win.refresh()
                    app.processEvents()
                    win.redraw()
                assert not win.legend_scroll.isVisible()
                assert not hasattr(win, 'status_lbl')
                png_check = export_dir / 'check.png'
                svg_check = export_dir / 'check.svg'
                win._save_plot(png_check, 'png', dpi=120)
                win._save_plot(svg_check, 'svg')
                assert png_check.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
                assert '<svg' in svg_check.read_text(encoding='utf-8')[:1000]
                app.processEvents()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                app.processEvents()
                if args.preview:
                    pixmap = QPixmap(win.size())
                    win.render(pixmap)
                    assert pixmap.save(args.preview)
                data = {'datasets': len(win.model.items), 'waves': win.model.waves(),
                        'sample_sha256': hashlib.sha256(SAMPLE.read_bytes()).hexdigest(),
                        'sample_source': str(SAMPLE),
                        'maximum': win.model.maximum(win.wave), 'fit_text': win.fit_label.text(),
                        'paste_import': True, 'paste_initial_focus': True,
                        'graph_count': 1, 'line_count': len(win.ax.get_lines()),
                        'required_import_remark': True, 'file_to_text_dialog': True,
                        'multi_file_cancel': True, 'highlight': True,
                        'table_click_highlight': True,
                        'wavelength_mouse_click': True,
                        'kpi_positions_fixed': True, 'kpi_values_centered': True, 'grade_rows_equal': True,
                        'independent_worst_kpi': True, 'kpi_source_labels': True,
                        'kpi_grade_colors_immediate': True,
                        'table_selection_reuses_plot': True, 'remark_column_only_rename': True,
                        'table_blank_click_deselect': True,
                        'selection_36_datasets_callback_ms': round(selection_ms, 2),
                        'legend_toggle_persist': True, 'legend_checkmark_refresh': True,
                        'legend_toggle_only': True,
                        'legend_wheel_scroll': True, 'legend_scroll_last_row_click': True,
                        'plot_height_stable_many_datasets': True, 'full_legend_export': True,
                        'bottom_status_text_removed': True,
                        'empty_plot_readout': True,
                        'png_svg_export': True,
                        'typography': {'chinese_family': actual_font.family(), 'body_px': small_label.font().pixelSize(),
                                       'body_weight': int(small_label.font().weight()), 'embedded_bold': True,
                                       'grade_heading_weight': 500, 'embedded_medium': True,
                                       'hinting': small_label.font().hintingPreference().name,
                                       'antialias': 'grayscale'}, 'ok': True}
                if args.startup_self_test:
                    import builtins
                    splash = getattr(builtins, '_optical_startup_splash', None)
                    assert splash is not None
                    data['startup_splash'] = splash.stats()
                    assert data['startup_splash']['shown'] and data['startup_splash']['closed']
                    assert data['startup_splash']['error'] is None
                    assert data['startup_splash']['animated_frames'] > 0
                    assert data['startup_splash']['max_progress_step'] <= .041
            except Exception:
                import traceback
                data = {'ok': False, 'error': traceback.format_exc()}
            Path(args.smoke_test).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            QTimer.singleShot(100, win.close)
        QTimer.singleShot(100, smoke)
    win.show()
    # Close only after Qt has had an opportunity to paint the ready main window.
    from startup_splash import close_startup
    QTimer.singleShot(0, close_startup)
    app.exec()
    # 打包环境下解释器退出阶段偶发挂起，直接硬退出
    os._exit(0)


def _register_qt_fonts():
    if _serifcjk.exists():
        QFontDatabase.addApplicationFont(str(_serifcjk))
    if _serifcjk_bold.exists():
        QFontDatabase.addApplicationFont(str(_serifcjk_bold))
    if _serifcjk_medium.exists():
        QFontDatabase.addApplicationFont(str(_serifcjk_medium))


def _app_font():
    return ui_font(SERIF_CJK, 16, QFont.Weight.Normal)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        from startup_splash import close_startup
        close_startup()
        import traceback
        error = traceback.format_exc()
        try:
            if getattr(sys, 'frozen', False):
                from runtime_cache import user_cache_base
                log_dir = user_cache_base()
                log_dir.mkdir(parents=True, exist_ok=True)
            else:
                log_dir = Path(__file__).resolve().parent
            (log_dir / '启动错误.txt').write_text(error, encoding='utf-8')
        except Exception:
            pass
