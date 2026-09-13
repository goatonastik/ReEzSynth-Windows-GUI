"""Still-image synthesis controls and weighted guide pairs."""
from pathlib import Path
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QFileDialog, QLabel, QDoubleSpinBox, QTableWidget, QHeaderView, QProgressBar, QComboBox)
from reezsynth_image import validate_image_settings
from reezsynth_widget_style import QueueDoubleSpinBox


class ImageFileEdit(QLineEdit):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setPlaceholderText('Select or drop an image file')

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile() and Path(urls[0].toLocalFile()).is_file():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile() and Path(urls[0].toLocalFile()).is_file():
            self.setText(urls[0].toLocalFile())
            event.acceptProposedAction()
        else:
            event.ignore()


class ImageSynthesisControls(QWidget):
    def __init__(self, window):
        super().__init__()
        self.w = window
        self.layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        for label, action in (('Open project', window.open_project),
                              ('Save project', window.save_project),
                              ('Save project as', lambda: window.save_project(True)),
                              ('Open outputs', window.open_outputs)):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, callback=action: callback())
            toolbar.addWidget(button)
            window.locked.append(button)
        self.layout.addLayout(toolbar)
        note = QLabel('Transfer a styled reference to a target image using corresponding source and target guides.\n'
            'Uses the shared quality, processing size and synthesis parameters. Video masks, edge/flow guides and blending settings do not apply.\n'
            'Source guides match the styled image size; all target guides match each other. Target size may differ from source size.')
        note.setWordWrap(True)
        self.layout.addWidget(note)
        form = QFormLayout()
        self.layout.addLayout(form)
        self.style, style_row = self.file_row('Styled image')
        self.source, source_row = self.file_row('Source guide')
        self.target, target_row = self.file_row('Target guide')
        form.addRow('Styled image', style_row)
        form.addRow('Source guide', source_row)
        form.addRow('Target guide', target_row)
        self.modulation, modulation_row = self.file_row('Primary guide modulation (optional)')
        self.modulation.setPlaceholderText('Optional 8-bit grayscale map matching the target')
        self.modulation.setToolTip('Multiplies all channels of the primary guide by grayscale / 255. '
                                   'White preserves weight; black removes the local guide cost. '
                                   'Legacy requires explicit CUDA; its CPU backend ignores maps.')
        form.addRow('Primary modulation', modulation_row)
        self.source_weight = self.weight(6)
        self.key_weight = self.weight(1, .001)
        form.addRow('Primary guide weight', self.source_weight)
        form.addRow('Style weight', self.key_weight)
        self.key_weight.setToolTip('Guide weights are divided by style weight, matching the video style-to-guide ratio control.')
        self.folder = QLineEdit('image_synthesis')
        self.folder.textChanged.connect(self.changed)
        form.addRow('Output subfolder', self.folder)
        window.locked.append(self.folder)
        output_note = QLabel('Uses Output naming on Video / Keyframes. For image jobs, keyframe-folder locations use the styled image folder; video-folder locations use the target image folder.\n'
                             'Saves image.png, numerical error.npy, and image_manifest.json in a new output subfolder.')
        output_note.setWordWrap(True)
        self.layout.addWidget(output_note)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Additional source guide', 'Additional target guide', 'Weight', 'Modulation (optional)', ''])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(4, 90)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.layout.addWidget(self.table, 1)
        window.locked.append(self.table)
        buttons = QHBoxLayout()
        add = QPushButton('Add guide pair')
        add.clicked.connect(lambda: self.add_guide())
        self.run = QPushButton('Synthesize Image')
        self.run.clicked.connect(window.run_image)
        buttons.addWidget(add)
        buttons.addStretch()
        self.stop = QPushButton('Stop')
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self.stop_render)
        buttons.addWidget(self.stop)
        buttons.addWidget(self.run)
        self.layout.addLayout(buttons)
        window.locked.extend([add, self.run])
        self.state = QLabel('Ready')
        self.bar = QProgressBar()
        self.layout.addWidget(self.state)
        self.layout.addWidget(self.bar)
        self.row = dict(key='image', label='Image synthesis', state=self.state, bar=self.bar)

    def changed(self, *_):
        if hasattr(self.w, 'options'):
            self.w.options.changed()

    def weight(self, value, minimum=0):
        widget = QueueDoubleSpinBox()
        widget.setRange(minimum, 10000)
        widget.setDecimals(6)
        widget.setSingleStep(.1)
        widget.setValue(value)
        widget.valueChanged.connect(self.changed)
        return widget

    def file_row(self, label):
        field = ImageFileEdit()
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(field, 1)
        button = QPushButton('Select')
        button.clicked.connect(lambda: self.choose(field, label))
        layout.addWidget(button)
        field.textChanged.connect(self.changed)
        return field, row

    def choose(self, field, label):
        path, _ = QFileDialog.getOpenFileName(self.w, label, field.text(),
            'Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All files (*)')
        if path:
            field.setText(path)

    def add_guide(self, data=None):
        data = data or dict(source='', target='', weight=1)
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, name in ((0, 'source'), (1, 'target')):
            field, container = self.file_row('Guide ' + name)
            field.setText(data[name])
            self.table.setCellWidget(row, column, container)
        weight = self.weight(data['weight'])
        self.table.setCellWidget(row, 2, weight)
        remove = QPushButton('Remove')
        remove.clicked.connect(lambda: self.remove_guide(remove))
        self.table.setCellWidget(row, 4, remove)
        modulation, container = self.file_row('Guide modulation (optional)')
        modulation.setText(data.get('modulation', ''))
        modulation.setPlaceholderText('Optional grayscale target map')
        modulation.setToolTip('8-bit grayscale image at the original target size; applies to every channel of this guide only.')
        self.table.setCellWidget(row, 3, container)
        self.table.setRowHeight(row, 38)
        self.changed()

    def remove_guide(self, button):
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 4) is button:
                self.table.removeRow(row)
                self.changed()
                return

    def settings(self):
        guides = []
        for row in range(self.table.rowCount()):
            guides.append(dict(source=self.table.cellWidget(row, 0).findChild(ImageFileEdit).text(),
                               target=self.table.cellWidget(row, 1).findChild(ImageFileEdit).text(),
                               weight=self.table.cellWidget(row, 2).value(),
                               modulation=self.table.cellWidget(row, 3).findChild(ImageFileEdit).text()))
        return validate_image_settings(dict(style=self.style.text(), source=self.source.text(), target=self.target.text(),
            source_weight=self.source_weight.value(), key_weight=self.key_weight.value(),
            folder=self.folder.text(), guides=guides, modulation=self.modulation.text()))

    def set_settings(self, data):
        data = validate_image_settings(data)
        for name in ('style', 'source', 'target', 'folder', 'modulation'):
            getattr(self, name).setText(data[name])
        self.source_weight.setValue(data['source_weight'])
        self.key_weight.setValue(data['key_weight'])
        self.table.setRowCount(0)
        for guide in data['guides']:
            self.add_guide(guide)

    def set_busy(self, busy):
        # Include dynamic selectors and guide rows, while leaving Stop reachable.
        for widget in self.findChildren(QWidget):
            if isinstance(widget, (QLineEdit, QDoubleSpinBox, QPushButton, QTableWidget, QComboBox)):
                widget.setEnabled(not busy and not self.w.close_when_idle)
        self.stop.setEnabled(busy and not self.w.cancelled)

    def stop_render(self):
        self.stop.setEnabled(False)
        self.w.stop_queue()
