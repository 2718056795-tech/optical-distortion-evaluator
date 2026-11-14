"""Render the startup card with the same embedded fonts as the main UI."""
from pathlib import Path
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication


def render():
    root = Path(__file__).resolve().parent
    app = QApplication([])
    for name in ('SourceHanSerifSC-Regular.otf', 'SourceHanSerifSC-Bold.otf'):
        QFontDatabase.addApplicationFont(str(root / name))
    image = QImage(1120, 488, QImage.Format.Format_RGB32)
    image.fill(QColor('#ffffff'))
    p = QPainter(image)
    p.scale(2, 2)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setPen(QPen(QColor('#e5e5ea'), 1))
    p.setBrush(QColor('#ffffff'))
    p.drawRoundedRect(QRectF(.5, .5, 559, 243), 18, 18)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor('#007aff'))
    p.drawRoundedRect(QRectF(40, 36, 44, 44), 12, 12)
    p.setPen(QPen(QColor('#ffffff'), 2.4, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    curve = QPainterPath()
    curve.moveTo(52, 68)
    curve.cubicTo(75, 67, 47, 49, 72, 47)
    p.drawPath(curve)
    def text(x, y, value, pixels, color, bold=False, family='Source Han Serif SC'):
        font = QFont(family)
        font.setPixelSize(pixels)
        font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
        p.setFont(font)
        p.setPen(QColor(color))
        p.drawText(x, y, value)
    text(100, 65, '光机镜头畸变评估工具', 24, '#2d2d2b', True)
    text(40, 133, '正在启动…', 17, '#7b7b85')
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor('#e9edf5'))
    p.drawRoundedRect(QRectF(40, 176, 480, 5), 2.5, 2.5)
    text(40, 217, 'V6', 15, '#7b7b85')
    p.end()
    assert image.save(str(root / 'startup_card.bmp'))
    assert image.save(str(root / 'startup_card.png'))


if __name__ == '__main__':
    render()
