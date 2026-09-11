"""Shared vector-painted arrows and checkmarks for queue and compact controls."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QDoubleSpinBox,
    QProxyStyle, QSizePolicy, QStyle, QVBoxLayout, QWidget)


def paint_check(painter, rectangle, checked, enabled=True, focused=False, partial=False):
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if not enabled:
        fill, border, tick = '#333333', '#555555', '#888888'
    else:
        fill = '#009f87' if checked or partial else '#151515'
        border = '#00c9aa' if focused else '#777777'
        tick = '#ffffff'
    pen = QPen(QColor(border))
    pen.setWidthF(1.2)
    painter.setPen(pen)
    painter.setBrush(QColor(fill))
    painter.drawRoundedRect(rectangle, 2, 2)
    if checked or partial:
        size, x, y = rectangle.width(), rectangle.x(), rectangle.y()
        path = QPainterPath()
        if partial:
            path.moveTo(x + size*.22, y + size*.5)
            path.lineTo(x + size*.78, y + size*.5)
        else:
            path.moveTo(x + size*.19, y + size*.51)
            path.lineTo(x + size*.43, y + size*.75)
            path.lineTo(x + size*.82, y + size*.28)
        pen = QPen(QColor(tick))
        pen.setWidthF(max(1.5, size*.12))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
    painter.restore()


class QueueStyle(QProxyStyle):
    def drawPrimitive(self, element, option, painter, widget=None):
        if element in (QStyle.PrimitiveElement.PE_IndicatorCheckBox,
                       QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck):
            paint_check(painter, QRectF(option.rect).adjusted(1, 1, -1, -1),
                        bool(option.state & QStyle.StateFlag.State_On),
                        bool(option.state & QStyle.StateFlag.State_Enabled),
                        bool(option.state & QStyle.StateFlag.State_HasFocus),
                        bool(option.state & QStyle.StateFlag.State_NoChange))
            return
        super().drawPrimitive(element, option, painter, widget)

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (QStyle.PixelMetric.PM_IndicatorWidth, QStyle.PixelMetric.PM_IndicatorHeight):
            return 14
        return super().pixelMetric(metric, option, widget)


class StepButton(QAbstractButton):
    """The same full-height arrow painter for frame and weight controls."""
    def __init__(self, direction, description=None):
        super().__init__()
        self.direction = direction
        self.setAutoRepeat(True)
        self.setAutoRepeatDelay(350)
        self.setAutoRepeatInterval(80)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        description = description or ('Increase frame number' if direction > 0 else 'Decrease frame number')
        self.setToolTip(description)
        self.setAccessibleName(description)

    def sizeHint(self):
        return QSize(30, 18)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event):
        width, height = self.width(), self.height()
        if width < 1 or height < 1:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            background, foreground = '#303030', '#777777'
        elif self.isDown():
            background, foreground = '#007e6b', '#ffffff'
        elif self.underMouse():
            background, foreground = '#555555', '#ffffff'
        else:
            background, foreground = '#414141', '#eeeeee'
        painter.fillRect(self.rect(), QColor(background))
        painter.setPen(QColor('#626262'))
        painter.drawLine(0, 0, width-1, 0)
        x, y = width/2, height/2
        dx, dy = min(6.5, width*.24), min(4, height*.24)
        if self.direction > 0:
            points = [QPointF(x,y-dy), QPointF(x-dx,y+dy), QPointF(x+dx,y+dy)]
        else:
            points = [QPointF(x-dx,y-dy), QPointF(x+dx,y-dy), QPointF(x,y+dy)]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(foreground))
        painter.drawPolygon(QPolygonF(points))


class QueueDoubleSpinBox(QDoubleSpinBox):
    """Keep Qt's numeric editor/signals, replacing only its native tiny arrows."""
    def __init__(self):
        super().__init__()
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setStyleSheet('QDoubleSpinBox { padding-right: 28px; }')
        self.setMinimumHeight(30)
        self.column = QWidget(self)
        self.up = StepButton(1, 'Increase weight')
        self.down = StepButton(-1, 'Decrease weight')
        layout = QVBoxLayout(self.column)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        layout.addWidget(self.up, 1)
        layout.addWidget(self.down, 1)
        self.up.clicked.connect(self.stepUp)
        self.down.clicked.connect(self.stepDown)
        self.valueChanged.connect(self.update_buttons)
        self.update_buttons()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.column.setGeometry(self.width()-28, 0, 28, self.height())

    def update_buttons(self, *_):
        if hasattr(self, 'up'):
            self.up.setEnabled(self.value() < self.maximum())
            self.down.setEnabled(self.value() > self.minimum())

    def setRange(self, minimum, maximum):
        super().setRange(minimum, maximum)
        self.update_buttons()

    def setMinimum(self, minimum):
        super().setMinimum(minimum)
        self.update_buttons()

    def setMaximum(self, maximum):
        super().setMaximum(maximum)
        self.update_buttons()
