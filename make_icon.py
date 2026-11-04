# -*- coding: utf-8 -*-
"""生成多尺寸 icon.ico（内嵌 PNG，Windows Vista+ 支持）"""
import sys, struct, io
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QLinearGradient
from PySide6.QtCore import Qt, QRectF, QPoint, QBuffer, QByteArray

app = QApplication(sys.argv)
PRIMARY = QColor("#17A673")
SIZES = [16, 24, 32, 48, 64, 128, 256]

pngs = []
for s in SIZES:
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    box = QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92)
    g = QLinearGradient(box.topLeft(), box.bottomRight())
    g.setColorAt(0.0, QColor("#33C692"))
    g.setColorAt(1.0, QColor("#0E8A5C"))
    p.setBrush(g)
    p.drawRoundedRect(box, s * 0.26, s * 0.26)
    pen = QPen(QColor("#FFFFFF"), max(1.5, s * 0.088))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPoint(int(s * 0.28), int(s * 0.52)), QPoint(int(s * 0.43), int(s * 0.67)))
    p.drawLine(QPoint(int(s * 0.43), int(s * 0.67)), QPoint(int(s * 0.73), int(s * 0.35)))
    p.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.WriteOnly)
    pm.save(buf, "PNG")
    buf.close()
    pngs.append(bytes(ba))

out = sys.argv[1] if len(sys.argv) > 1 else "icon.ico"
n = len(pngs)
header = struct.pack("<HHH", 0, 1, n)
offset = 6 + 16 * n
entries, data = b"", b""
for s, png in zip(SIZES, pngs):
    w = 0 if s >= 256 else s
    entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(png), offset)
    data += png
    offset += len(png)
open(out, "wb").write(header + entries + data)
print("saved", out, len(header + entries + data), "bytes,", n, "sizes")
