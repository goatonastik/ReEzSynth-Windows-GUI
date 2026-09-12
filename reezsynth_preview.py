"""Live synthesis previews, captured and decoded only while the window is open."""
import json
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QGridLayout, QHBoxLayout,
                               QLabel, QScrollArea, QVBoxLayout, QWidget)
from reezsynth_preview_transport import PREVIEW_DIR, preview_channels, preview_filename


class PreviewTile(QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title = title
        self.pixmap = QPixmap()
        self.path = None
        self.dirty = False
        self.setMinimumSize(180, 120)

    def set_path(self, path):
        self.path = Path(path)
        self.dirty = True
        self.refresh()

    def refresh(self):
        if not self.dirty or self.path is None:
            return
        try:
            # Bypass QPixmap's filename cache: this latest-frame file is replaced.
            image = QImage.fromData(self.path.read_bytes())
        except OSError:
            return
        if not image.isNull():
            self.pixmap = QPixmap.fromImage(image)
            self.dirty = False
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#151515'))
        label_x, label_y, label_width = 10, 25, self.width() - 20
        if self.pixmap.isNull():
            painter.setPen(QColor('#777777'))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Waiting for finished frame…')
        else:
            target = self.pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            x = (self.width() - target.width()) // 2
            y = (self.height() - target.height()) // 2
            painter.drawPixmap(x, y, target.width(), target.height(), self.pixmap)
            label_x, label_y, label_width = x + 10, y + 25, target.width() - 20
        path = QPainterPath()
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        label = painter.fontMetrics().elidedText(self.title, Qt.TextElideMode.ElideRight, label_width)
        path.addText(label_x, label_y, font, label)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.strokePath(path, QPen(QColor('black'), 3, Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.fillPath(path, QColor('white'))


class LivePreviewWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Render previews')
        self.resize(900, 650)
        self.entries = []
        self.tiles = {}
        self.catalog = {}
        self.limit = 8
        self.running = False
        self.requests = set()
        self.recent_jobs = []
        self.active_jobs = set()
        outer = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('Layout:'))
        self.layout_mode = QComboBox()
        self.layout_mode.addItem('Queue pairs', 'pairs')
        self.layout_mode.addItem('Square grid', 'grid')
        self.layout_mode.currentIndexChanged.connect(self.reflow)
        controls.addWidget(self.layout_mode)
        self.note = QLabel('Live synthesis previews precede final mask compositing and grouped blending.')
        self.note.setWordWrap(True)
        self.note.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        controls.addWidget(self.note, 1)
        outer.addLayout(controls)
        self.host = QWidget()
        self.grid = QGridLayout(self.host)
        self.grid.setContentsMargins(8, 8, 8, 8)
        self.grid.setSpacing(8)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.host)
        outer.addWidget(self.scroll)
        self.lease_timer = QTimer(self)
        self.lease_timer.setInterval(2000)
        self.lease_timer.timeout.connect(self.update_requests)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(150)
        self.refresh_timer.timeout.connect(self.refresh_images)

    def begin(self, records, limit):
        self.end()
        self.clear_tiles()
        self.catalog = {}
        self.recent_jobs = []
        self.active_jobs = set()
        self.limit = max(1, int(limit))
        for record in records:
            if 'job_path' in record:
                job = json.loads(Path(record['job_path']).read_text(encoding='utf-8'))
                channels = preview_channels(job)
                output = Path(record['output']).resolve()
            else:  # Isolated widget tests without job files.
                row = record['row']
                key = row.get('key', record.get('key', '?'))
                channels = []
                for field, endpoint, direction in (('reverse', 'start', 'Backward'), ('forward', 'end', 'Forward')):
                    if row.get(field) and row[field].isChecked() and row[endpoint].value() != key:
                        channels.append((key, direction))
                channels = channels or [(key, 'Keyframe')]
                output = None
            for entry in channels:
                self.catalog[entry] = dict(output=output, path=None, frame=None)
        self.running = True
        self.select_entries()

    def clear_tiles(self):
        while self.grid.count():
            self.grid.takeAt(0)
        for tile in self.tiles.values():
            tile.hide()
            tile.deleteLater()
        self.tiles = {}
        self.entries = []

    def activate(self, record):
        output = Path(record['output']).resolve()
        self.active_jobs.add(output)
        self.recent_jobs = [output] + [p for p in self.recent_jobs if p != output]
        self.select_entries()

    def finish(self, record):
        self.active_jobs.discard(Path(record['output']).resolve())

    def select_entries(self):
        # Later queue rows take the place of earlier completed jobs at the cap.
        preferred = [entry for entry, data in self.catalog.items() if data['output'] in self.active_jobs]
        for output in self.recent_jobs:
            preferred.extend(e for e, d in self.catalog.items() if d['output'] == output and e not in preferred)
        preferred.extend(e for e in self.catalog if e not in preferred)
        selected = set(preferred[:self.limit])
        entries = [entry for entry in self.catalog if entry in selected]
        if entries != self.entries:
            self.clear_tiles()
            self.entries = entries
            for key, direction in entries:
                entry = (key, direction)
                tile = PreviewTile(f'Keyframe {key} — {direction}', self.host)
                tile.path = self.catalog[entry]['path']
                tile.dirty = tile.path is not None
                frame = self.catalog[entry]['frame']
                if frame is not None:
                    tile.title += f' — Frame {frame}'
                self.tiles[entry] = tile
            self.reflow()
        hidden = len(self.catalog) - len(self.entries)
        self.note.setText('Live synthesis previews precede final mask compositing and grouped blending.'
                         + (f' Showing {len(self.entries)} of {len(self.catalog)} directions; active jobs take priority.' if hidden else ''))
        self.update_requests()
        self.refresh_images()

    def update_requests(self):
        desired = {}
        if self.isVisible() and self.running:
            for entry in self.entries:
                output = self.catalog[entry]['output']
                if output is not None:
                    desired.setdefault(output / PREVIEW_DIR / 'request.json', []).append(list(entry))
        for path in self.requests - set(desired):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass  # The short lease also stops capture after a GUI failure.
        self.requests = set(desired)
        for path, channels in desired.items():
            try:
                path.parent.mkdir(exist_ok=True)
                temporary = path.with_suffix('.json.part')
                temporary.write_text(json.dumps(dict(updated=time.time(), channels=channels)), encoding='utf-8')
                temporary.replace(path)
            except OSError as exc:
                self.note.setText(f'Preview capture unavailable: {exc}')
        if desired:
            if not self.lease_timer.isActive():
                self.lease_timer.start()
        else:
            self.lease_timer.stop()

    def receive(self, message, record):
        if not isinstance(message, dict):
            return
        try:
            entry = (message['key'], message['direction'])
            output = Path(record['output']).resolve()
            expected = output / PREVIEW_DIR / preview_filename(*entry)
            if entry not in self.catalog or self.catalog[entry]['output'] != output:
                return
            if Path(message['path']).resolve() != expected:
                return
            self.update_frame(*entry, expected, frame=message.get('frame'))
        except (KeyError, TypeError, ValueError, OSError):
            return

    def update_frame(self, key, direction, path, frame=None):
        entry = (key, direction)
        if entry not in self.catalog:
            return
        self.catalog[entry].update(path=Path(path), frame=frame)
        tile = self.tiles.get(entry)
        if tile is not None:
            tile.path = Path(path)
            tile.dirty = True
            tile.title = f'Keyframe {key} — {direction}' + (f' — Frame {frame}' if frame is not None else '')
            self.refresh_images()

    def refresh_images(self):
        if self.isVisible():
            for tile in self.tiles.values():
                tile.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.update_requests()
        self.refresh_images()
        self.refresh_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.update_requests()
        self.refresh_timer.stop()
        for tile in self.tiles.values():
            tile.pixmap = QPixmap()
            tile.dirty = tile.path is not None

    def end(self):
        self.running = False
        self.update_requests()

    def reflow(self, *_):
        while self.grid.count():
            self.grid.takeAt(0)
        for row in range(self.grid.rowCount()):
            self.grid.setRowStretch(row, 0)
        for column in range(self.grid.columnCount()):
            self.grid.setColumnStretch(column, 0)
        count = len(self.entries)
        if not count:
            return
        if self.layout_mode.currentData() == 'pairs':
            keys = list(dict.fromkeys(key for key, _ in self.entries))
            columns = 2 if count > 1 else 1
            for entry in self.entries:
                row = keys.index(entry[0])
                paired = sum(key == entry[0] for key, _ in self.entries) == 2
                col = int(entry[1] == 'Forward') if paired else 0
                self.grid.addWidget(self.tiles[entry], row, col, 1, 1 if paired else columns)
                self.grid.setRowStretch(row, 1)
        else:
            columns = max(1, min(count, round((self.width() / max(self.height(), 1) * count) ** 0.5)))
            for index, entry in enumerate(self.entries):
                self.grid.addWidget(self.tiles[entry], index // columns, index % columns)
                self.grid.setRowStretch(index // columns, 1)
        for tile in self.tiles.values():
            tile.show()
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'layout_mode') and self.layout_mode.currentData() == 'grid':
            self.reflow()
