import sys

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QAbstractSpinBox,
    QHBoxLayout,
    QHeaderView,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from reezsynth_gui_v03 import MainWindow, THEME, APP_NAME


ROW_HEIGHT = 36
STEP_COLUMN_WIDTH = 30


class StepButton(QAbstractButton):
    """An arrow button that fills its allocated half of the control."""

    def __init__(self, direction):
        super().__init__()
        self.direction = direction

        self.setAutoRepeat(True)
        self.setAutoRepeatDelay(350)
        self.setAutoRepeatInterval(80)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )

        description = (
            "Increase frame number"
            if direction > 0
            else "Decrease frame number"
        )
        self.setToolTip(description)
        self.setAccessibleName(description)

    def sizeHint(self):
        return QSize(STEP_COLUMN_WIDTH, ROW_HEIGHT // 2)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event):
        width = self.width()
        height = self.height()
        if width < 1 or height < 1:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.isEnabled():
            background = "#303030"
            foreground = "#777777"
        elif self.isDown():
            background = "#007e6b"
            foreground = "#ffffff"
        elif self.underMouse():
            background = "#555555"
            foreground = "#ffffff"
        else:
            background = "#414141"
            foreground = "#eeeeee"

        painter.fillRect(self.rect(), QColor(background))

        # Clearly separate the two button hit areas.
        painter.setPen(QColor("#626262"))
        painter.drawLine(0, 0, width - 1, 0)

        center_x = width / 2
        center_y = height / 2
        half_width = min(6.5, width * 0.24)
        half_height = min(4.0, height * 0.24)

        if self.direction > 0:
            points = [
                QPointF(center_x, center_y - half_height),
                QPointF(center_x - half_width, center_y + half_height),
                QPointF(center_x + half_width, center_y + half_height),
            ]
        else:
            points = [
                QPointF(center_x - half_width, center_y - half_height),
                QPointF(center_x + half_width, center_y - half_height),
                QPointF(center_x, center_y + half_height),
            ]

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(foreground))
        painter.drawPolygon(QPolygonF(points))


class FullHeightSpinBox(QWidget):
    """
    A normal editable QSpinBox with a separate full-height arrow column.

    Each arrow receives equal vertical space. The existing queue code
    can continue using setRange(), setValue(), and value().
    """

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(92)

        self.number = QSpinBox()
        self.number.setObjectName("QueueNumberEditor")
        self.number.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        self.number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.number.setKeyboardTracking(False)
        self.number.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self.up = StepButton(1)
        self.down = StepButton(-1)

        column = QWidget()
        column.setFixedWidth(STEP_COLUMN_WIDTH)

        arrows = QVBoxLayout(column)
        arrows.setContentsMargins(0, 0, 0, 0)
        arrows.setSpacing(0)
        arrows.addWidget(self.up, 1)
        arrows.addWidget(self.down, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.number, 1)
        layout.addWidget(column)

        self.up.clicked.connect(self.number.stepUp)
        self.down.clicked.connect(self.number.stepDown)
        self.number.valueChanged.connect(self.update_buttons)

        self.update_buttons()

    def sizeHint(self):
        return QSize(92, ROW_HEIGHT)

    def update_buttons(self, *_):
        value = self.number.value()
        self.up.setEnabled(value < self.number.maximum())
        self.down.setEnabled(value > self.number.minimum())

    def setRange(self, minimum, maximum):
        self.number.setRange(minimum, maximum)
        self.update_buttons()

    def setValue(self, value):
        self.number.setValue(value)
        self.update_buttons()

    def value(self):
        # Commit any typed value before saving or starting a render.
        self.number.interpretText()
        return self.number.value()

    def minimum(self):
        return self.number.minimum()

    def maximum(self):
        return self.number.maximum()


class CenteredToggle(QAbstractButton):
    """A centered, clearly visible check control with a full-cell hit area."""

    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(32)

        self.toggled.connect(lambda _: self.update())

    def sizeHint(self):
        return QSize(36, ROW_HEIGHT)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#252525"))

        size = max(
            2.0,
            min(24.0, self.width() - 8.0, self.height() - 8.0),
        )
        x = (self.width() - size) / 2
        y = (self.height() - size) / 2

        if not self.isEnabled():
            fill = "#333333"
            border = "#555555"
            tick = "#888888"
        else:
            fill = "#009f87" if self.isChecked() else "#151515"
            border = "#00c9aa" if self.hasFocus() else "#777777"
            tick = "#ffffff"

        border_pen = QPen(QColor(border))
        border_pen.setWidthF(1.2)

        painter.setPen(border_pen)
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(QRectF(x, y, size, size), 2, 2)

        if self.isChecked():
            path = QPainterPath()
            path.moveTo(x + size * 0.19, y + size * 0.51)
            path.lineTo(x + size * 0.43, y + size * 0.75)
            path.lineTo(x + size * 0.82, y + size * 0.28)

            tick_pen = QPen(QColor(tick))
            tick_pen.setWidthF(max(1.5, size * 0.12))
            tick_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            tick_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

            painter.setPen(tick_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)


class UpdatedMainWindow(MainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME + " - v0.3.1")

        self.table.verticalHeader().setMinimumSectionSize(32)
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)

        header = self.table.horizontalHeader()
        for column in (2, 4):
            header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.Fixed
            )
            header.resizeSection(column, 36)

    def add_row(self, definition):
        # Keep the working v0.3 queue planning and project behavior.
        super().add_row(definition)

        row = self.rows[-1]
        index = self.table.rowCount() - 1
        self.table.setRowHeight(index, ROW_HEIGHT)

        # Replace the tiny native spin-button areas.
        for column, name in ((1, "start"), (5, "end")):
            old = row[name]

            replacement = FullHeightSpinBox()
            replacement.setRange(old.minimum(), old.maximum())
            replacement.setValue(old.value())

            row[name] = replacement
            self.table.setCellWidget(index, column, replacement)

        # Replace the left-aligned native checkboxes.
        for column, name, number_field, description in (
            (2, "reverse", "start", "Backward propagation"),
            (4, "forward", "end", "Forward propagation"),
        ):
            checked = row[name].isChecked()

            toggle = CenteredToggle()
            toggle.setChecked(checked)
            toggle.setToolTip(description)
            toggle.setAccessibleName(
                f"{description} for keyframe {row['key']}"
            )

            row[name] = toggle
            toggle.toggled.connect(
                lambda enabled, r=row, field=number_field:
                r[field].setEnabled(enabled and not self.busy)
            )

            self.table.setCellWidget(index, column, toggle)

        row["state"].setAlignment(Qt.AlignmentFlag.AlignCenter)

        key_item = self.table.item(index, 3)
        if key_item is not None:
            key_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        row["synth"].setStyleSheet(
            "QPushButton { padding: 4px 10px; }"
        )
        row["remove"].setStyleSheet(
            "QPushButton { padding: 4px 8px; }"
        )

        row["start"].setEnabled(
            row["reverse"].isChecked() and not self.busy
        )
        row["end"].setEnabled(
            row["forward"].isChecked() and not self.busy
        )


EXTRA_THEME = """
QSpinBox#QueueNumberEditor {
    background: #151515;
    border: none;
    padding: 0px 5px;
}
QSpinBox#QueueNumberEditor:disabled {
    color: #666666;
}
"""


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(THEME + EXTRA_THEME)

    window = UpdatedMainWindow()
    window.show()

    sys.exit(app.exec())