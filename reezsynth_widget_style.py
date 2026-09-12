"""Shared vector-painted arrows and checkmarks for queue and compact controls."""
from pathlib import Path
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QDoubleSpinBox, QSpinBox,
    QProxyStyle, QSizePolicy, QStyle, QVBoxLayout, QWidget)


# Qt's stylesheet draws combobox arrows itself, bypassing drawComplexControl.
# Style them here for every combobox, including editable folder histories.
_ASSETS = Path(__file__).resolve().parent / 'assets'
COMBO_STYLE = f'''
QComboBox {{ padding-right: 32px; }}
QComboBox::drop-down {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 28px;
    background: #414141;
    border-top: 1px solid #626262;
}}
QComboBox::drop-down:hover {{ background: #555555; }}
QComboBox::drop-down:pressed {{ background: #007e6b; }}
QComboBox::drop-down:disabled {{ background: #303030; }}
QComboBox::down-arrow {{ image: url("{(_ASSETS / 'arrow-down.svg').as_posix()}"); width: 13px; height: 8px; }}
QComboBox::down-arrow:disabled {{ image: url("{(_ASSETS / 'arrow-down-disabled.svg').as_posix()}"); }}
'''


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


def paint_arrow(painter, rectangle, direction, color):
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    x, y = rectangle.center().x(), rectangle.center().y()
    dx, dy = min(6.5, rectangle.width()*.24), min(4, rectangle.height()*.24)
    if direction > 0:
        points = [QPointF(x, y-dy), QPointF(x-dx, y+dy), QPointF(x+dx, y+dy)]
    else:
        points = [QPointF(x-dx, y-dy), QPointF(x+dx, y-dy), QPointF(x, y+dy)]
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPolygon(QPolygonF(points))
    painter.restore()


def paint_arrow_button(painter, rectangle, direction, enabled=True, pressed=False, hovered=False):
    if not enabled:
        background, foreground = '#303030', '#777777'
    elif pressed:
        background, foreground = '#007e6b', '#ffffff'
    elif hovered:
        background, foreground = '#555555', '#ffffff'
    else:
        background, foreground = '#414141', '#eeeeee'
    painter.save()
    painter.fillRect(rectangle, QColor(background))
    painter.setPen(QColor('#626262'))
    painter.drawLine(rectangle.topLeft(), rectangle.topRight())
    paint_arrow(painter, rectangle, direction, foreground)
    painter.restore()


class QueueStyle(QProxyStyle):
    """Application-wide checkmarks and dropdown arrows, including new controls."""
    def drawPrimitive(self, element, option, painter, widget=None):
        if element in (QStyle.PrimitiveElement.PE_IndicatorArrowDown,
                       QStyle.PrimitiveElement.PE_IndicatorArrowUp):
            paint_arrow(painter, QRectF(option.rect),
                        1 if element == QStyle.PrimitiveElement.PE_IndicatorArrowUp else -1,
                        '#eeeeee' if option.state & QStyle.StateFlag.State_Enabled else '#777777')
            return
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
        paint_arrow_button(painter, QRectF(self.rect()), self.direction,
                           self.isEnabled(), self.isDown(), self.underMouse())


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


class QueueSpinBox(QSpinBox):
    """Integer counterpart to QueueDoubleSpinBox with the same arrow column."""
    def __init__(self):
        super().__init__()
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setStyleSheet('QSpinBox { padding-right: 28px; }')
        self.setMinimumHeight(30)
        self.column = QWidget(self)
        self.up = StepButton(1, 'Increase value')
        self.down = StepButton(-1, 'Decrease value')
        layout = QVBoxLayout(self.column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.up, 1)
        layout.addWidget(self.down, 1)
        self.up.clicked.connect(self.stepUp)
        self.down.clicked.connect(self.stepDown)
        self.valueChanged.connect(self.update_buttons)
        self.update_buttons()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.column.setGeometry(self.width() - 28, 0, 28, self.height())

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


class PyramidLevelsSpinBox(QueueSpinBox):
    """Expose the native -1 automatic value and skip unsupported zero when stepping."""
    def stepBy(self, steps):
        old = self.value()
        super().stepBy(steps)
        if self.value() == 0:
            self.setValue(1 if steps > 0 else -1)
        elif old == -1 and steps > 1:
            self.setValue(min(self.maximum(), self.value() + 1))
