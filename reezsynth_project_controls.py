
import re
import string
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from PySide6.QtWidgets import QWidget


HISTORY_LIMIT = 12

DEFAULT_BATCH_PATTERN = "batch_{date}_{time}_{microsecond}"
DEFAULT_JOB_PATTERN = "out_{key:0{padding}d}"

BATCH_FIELDS = {
    "date",
    "time",
    "microsecond",
    "quality",
    "width",
    "keyframe_dir_name",
    "video_dir_name",
}

JOB_FIELDS = BATCH_FIELDS | {
    "key",
    "start",
    "end",
    "index",
    "padding",
    "key_name",
}

FORMATTER = string.Formatter()
RESERVED_NAME = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)",
    re.IGNORECASE,
)


class FolderHistoryCombo(QComboBox):
    """Editable folder history compatible with the existing path fields."""

    textChanged = Signal(str)

    def __init__(self, label, editor, preferences):
        super().__init__()

        self.preferences = preferences
        self.history_key = (
            "folder_history/" + label.casefold().replace(" ", "_")
        )

        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setLineEdit(editor)
        editor.setStyleSheet("QLineEdit { border: none; padding: 0px; background: transparent; }")
        self.setMinimumWidth(250)
        self.setMaxVisibleItems(HISTORY_LIMIT)
        self.setToolTip(
            "Type or drop a directory, or choose a recently used folder."
        )

        stored = preferences.value(self.history_key, [])
        if isinstance(stored, str):
            stored = [stored]
        if not isinstance(stored, (list, tuple)):
            stored = []

        self.addItems([
            item for item in stored
            if isinstance(item, str) and item
        ][:HISTORY_LIMIT])
        self.setCurrentIndex(-1)
        self.setEditText("")

        self.editTextChanged.connect(self.textChanged.emit)
        self.lineEdit().editingFinished.connect(self.remember)

    def text(self):
        return self.currentText()

    def setText(self, text):
        self.setEditText(str(text))

    def remember(self):
        """Remember only existing directories, not partial typed paths."""
        raw = self.text().strip().strip('"')
        if not raw:
            return

        try:
            path = Path(raw).expanduser().resolve()
            if not path.is_dir():
                return
        except (OSError, ValueError):
            return

        value = str(path)
        existing = [
            self.itemText(index)
            for index in range(self.count())
        ]

        history = [value]
        seen = {value.casefold()}

        for item in existing:
            identity = item.casefold()
            if identity not in seen:
                history.append(item)
                seen.add(identity)

        history = history[:HISTORY_LIMIT]

        # Rebuilding the dropdown must not trigger another queue scan.
        blocker = QSignalBlocker(self)
        try:
            self.clear()
            self.addItems(history)
            self.setEditText(raw)
        finally:
            del blocker

        self.preferences.setValue(self.history_key, history)


def _values(window=None, definition=None, index=1, now=None):
    now = now or datetime.now()

    values = {
        "date": now.strftime("%Y%m%d"),
        "time": now.strftime("%H%M%S"),
        "microsecond": now.strftime("%f"),
        "quality": "Preview",
        "width": 512,
        "padding": 3,
        "key": 23,
        "start": 0,
        "end": 46,
        "index": index,
        "key_name": "style023",
        "keyframe_dir_name": "keys",
        "video_dir_name": "video",
    }

    if window is not None:
        values["quality"] = window.quality.currentText()
        width = window.resolution.currentData()
        values["width"] = width if width else "original"
        values["padding"] = window.padding
        values["keyframe_dir_name"] = Path(window.keyframe_dir.text()).name
        values["video_dir_name"] = Path(window.video_dir.text()).name

    if definition is not None:
        key = definition["key"]
        values["key"] = key
        if window is not None and key in window.keys:
            values["key_name"] = Path(window.keys[key]).stem
        values["start"] = (
            definition["start"]
            if definition["reverse"]
            else key
        )
        values["end"] = (
            definition["end"]
            if definition["forward"]
            else key
        )

    return values


def _check_pattern_fields(pattern, allowed, depth=0):
    if depth > 2:
        raise ValueError("Naming pattern has too much nested formatting.")

    try:
        parts = list(FORMATTER.parse(pattern))
    except ValueError as exc:
        raise ValueError(f"Invalid naming pattern: {exc}") from exc

    for _, field, specification, conversion in parts:
        if field is None:
            continue

        if field not in allowed:
            choices = ", ".join(sorted(allowed))
            raise ValueError(
                f"Unknown naming field {{{field}}}. "
                f"Allowed fields: {choices}."
            )

        if conversion is not None:
            raise ValueError(
                "Naming patterns do not support !r, !s, or !a conversions."
            )

        if "{" in specification or "}" in specification:
            _check_pattern_fields(
                specification, allowed, depth + 1
            )


def _validate_relative_name(value, allow_nested=True):
    """Validate Windows-compatible relative output names."""
    if not isinstance(value, str) or not value:
        raise ValueError("An output name cannot be empty.")

    if len(value) > 180:
        raise ValueError(
            "An output name is too long. Use a shorter pattern."
        )

    if any(ord(character) < 32 for character in value):
        raise ValueError("Output names cannot contain control characters.")

    if any(character in value for character in '<>:"|?*'):
        raise ValueError(
            'Output names cannot contain these characters: <>:"|?*'
        )

    parts = value.replace("\\", "/").split("/")

    if not allow_nested and len(parts) != 1:
        raise ValueError(
            "The batch pattern must produce one folder name, "
            "without slashes."
        )

    for part in parts:
        if not part or part in {".", ".."}:
            raise ValueError(
                "Output names must be relative folders without "
                "empty components, '.' or '..'."
            )

        if part.endswith((" ", ".")):
            raise ValueError(
                "Output folder names cannot end with a space or period."
            )

        if RESERVED_NAME.match(part):
            raise ValueError(
                f"'{part}' is a reserved Windows filename."
            )

    return value


def _format_name(pattern, values, allowed, allow_nested=True):
    pattern = str(pattern).strip()
    if not pattern:
        raise ValueError("A naming pattern cannot be empty.")

    if len(pattern) > 200:
        raise ValueError("The naming pattern is too long.")

    _check_pattern_fields(pattern, allowed)

    try:
        name = FORMATTER.vformat(pattern, (), values)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        raise ValueError(
            f"Cannot format naming pattern: {exc}"
        ) from exc

    return _validate_relative_name(name, allow_nested)


def validate_output_folders(names):
    """Reject duplicate or overlapping job output directories."""
    normalized = []

    for name in names:
        _validate_relative_name(name)
        normalized.append(
            name.replace("\\", "/").casefold()
        )

    for index, name in enumerate(normalized):
        for previous in normalized[:index]:
            if (
                name == previous
                or name.startswith(previous + "/")
                or previous.startswith(name + "/")
            ):
                raise ValueError(
                    "Selected jobs have duplicate or overlapping "
                    "output folders. Give each job its own folder."
                )


def validate_project_naming(data):
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("Invalid project output-naming settings.")

    batch = data.get("batch_pattern", DEFAULT_BATCH_PATTERN)
    job = data.get("job_pattern", DEFAULT_JOB_PATTERN)

    if not isinstance(batch, str) or not isinstance(job, str):
        raise ValueError("Output naming patterns must be text.")

    batch = batch.strip()
    job = job.strip()
    values = _values()

    _format_name(batch, values, BATCH_FIELDS, allow_nested=False)
    _format_name(job, values, JOB_FIELDS)

    return {
        "batch_pattern": batch,
        "job_pattern": job,
    }


def project_naming(window):
    return validate_project_naming({
        "batch_pattern": window.batch_name_pattern.text(),
        "job_pattern": window.job_name_pattern.text(),
    })


def set_project_naming(window, naming):
    window.batch_name_pattern.setText(naming["batch_pattern"])
    window.job_name_pattern.setText(naming["job_pattern"])
    update_naming_preview(window)


def add_output_controls(window, page):
    group = QGroupBox("Output naming")
    layout = QVBoxLayout(group)
    form = QFormLayout()

    window.batch_name_pattern = QLineEdit(DEFAULT_BATCH_PATTERN)
    window.batch_name_pattern.setToolTip(
        "Folder created under Project directory / renders.\n"
        "Fields: {date}, {time}, {microsecond}, {quality}, {width},\n"
        "{keyframe_dir_name}, {video_dir_name}.\n"
        "Existing folders are preserved; a numeric suffix is added "
        "when necessary."
    )

    window.job_name_pattern = QLineEdit(DEFAULT_JOB_PATTERN)
    window.job_name_pattern.setToolTip(
        "Pattern for each job's output subfolder.\n"
        "Fields: {key}, {start}, {end}, {index}, {padding}, "
        "{date}, {time}, {microsecond}, {quality}, {width},\n"
        "{key_name}, {keyframe_dir_name}, {video_dir_name}.\n"
        "Examples: out_{key:04d}, {index:02d}_key_{key}.\n"
        "{start} and {end} reflect enabled propagation directions."
    )

    form.addRow("Batch folder pattern", window.batch_name_pattern)

    job_controls = QWidget()
    job_layout = QHBoxLayout(job_controls)
    job_layout.setContentsMargins(0, 0, 0, 0)
    job_layout.addWidget(window.job_name_pattern)

    window.apply_output_names = QPushButton("Apply to Queue")
    window.apply_output_names.setToolTip(
        "Replace the current queue's output-subfolder names using "
        "this pattern. Existing rendered files are not renamed."
    )
    window.apply_output_names.clicked.connect(
        lambda checked=False: apply_names_to_queue(window)
    )
    job_layout.addWidget(window.apply_output_names)
    form.addRow("Job subfolder pattern", job_controls)

    layout.addLayout(form)
    suffixes = QHBoxLayout()
    suffixes.addWidget(QLabel("Job name suffixes:"))
    for label, suffix in (("Keyframe name", "_{key_name}"), ("Date/time", "_{date}_{time}"),
                          ("Keyframe folder", "_{keyframe_dir_name}"), ("Video folder", "_{video_dir_name}")):
        toggle = QCheckBox(label)
        suffixes.addWidget(toggle)
        window.locked.append(toggle)
        def change_suffix(enabled, text=suffix):
            pattern = window.job_name_pattern.text()
            if enabled and text not in pattern:
                window.job_name_pattern.setText(pattern + text)
            elif not enabled and text in pattern:
                window.job_name_pattern.setText(pattern.replace(text, ""))
        def sync_suffix(pattern, box=toggle, text=suffix):
            blocker = QSignalBlocker(box)
            box.setChecked(text in pattern)
            del blocker
        toggle.toggled.connect(change_suffix)
        window.job_name_pattern.textChanged.connect(sync_suffix)
    layout.addLayout(suffixes)

    window.naming_preview = QLabel()
    window.naming_preview.setWordWrap(True)
    layout.addWidget(window.naming_preview)

    explanation = QLabel(
        "A new batch folder is created for each run. "
        "Job patterns are applied when rebuilding the queue, or with "
        "Apply to Queue. You can still edit individual output names "
        "in the table."
    )
    explanation.setWordWrap(True)
    layout.addWidget(explanation)

    page.addWidget(group)

    window.locked.extend([
        window.batch_name_pattern,
        window.job_name_pattern,
        window.apply_output_names,
    ])

    for signal in (
        window.batch_name_pattern.textChanged,
        window.job_name_pattern.textChanged,
        window.quality.currentTextChanged,
        window.resolution.currentIndexChanged,
    ):
        signal.connect(
            lambda *args: update_naming_preview(window)
        )

    update_naming_preview(window)


def update_naming_preview(window):
    try:
        naming = project_naming(window)
        definition = (
            window.definition(window.rows[0])
            if window.rows
            else None
        )
        values = _values(window, definition)

        batch = _format_name(
            naming["batch_pattern"],
            values,
            BATCH_FIELDS,
            allow_nested=False,
        )
        job = _format_name(
            naming["job_pattern"],
            values,
            JOB_FIELDS,
        )

        window.naming_preview.setStyleSheet("color: #91b6aa;")
        window.naming_preview.setText(
            f"Pattern example: renders / {batch} / {job}\n"
            "Time fields are evaluated when names are generated; "
            "this preview does not rename existing queue entries."
        )

    except (ValueError, TypeError, KeyError) as exc:
        window.naming_preview.setStyleSheet("color: #e3a16f;")
        window.naming_preview.setText(str(exc))


def default_job_definitions(window, definitions):
    """Generate names for a newly scanned queue."""
    pattern = window.job_name_pattern.text()
    now = datetime.now()
    result = []

    for index, definition in enumerate(definitions, start=1):
        updated = dict(definition)
        updated["folder"] = _format_name(
            pattern,
            _values(window, definition, index, now),
            JOB_FIELDS,
        )
        result.append(updated)

    validate_output_folders([
        definition["folder"] for definition in result
    ])
    return result


def apply_names_to_queue(window):
    if window.busy or window.close_when_idle:
        return

    if not window.rows:
        QMessageBox.information(
            window,
            "No queue",
            "Select your source and keyframe folders first.",
        )
        return

    try:
        definitions = [
            window.definition(row)
            for row in window.rows
        ]
        generated = default_job_definitions(window, definitions)

    except (ValueError, TypeError, KeyError) as exc:
        QMessageBox.warning(
            window, "Cannot apply output names", str(exc)
        )
        return

    changed = any(
        row["folder"].text().strip() != definition["folder"]
        for row, definition in zip(window.rows, generated)
    )

    if not changed:
        window.status.setText(
            "The queue already uses these output names."
        )
        return

    answer = QMessageBox.question(
        window,
        "Replace queue output names?",
        "Apply this pattern to every job in the current queue?\n\n"
        "This replaces any manually edited output-subfolder names. "
        "Existing rendered files are not renamed or deleted.",
        QMessageBox.StandardButton.Yes
        | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return

    for row, definition in zip(window.rows, generated):
        row["folder"].setText(definition["folder"])

    save_ui_state(window)
    window.status.setText(
        "Output naming pattern applied to the queue."
    )


def create_batch_directory(window, project_root):
    """Create a fresh batch directory without overwriting an existing one."""
    name = _format_name(
        window.batch_name_pattern.text(),
        _values(window),
        BATCH_FIELDS,
        allow_nested=False,
    )

    render_root = Path(project_root) / "renders"
    render_root.mkdir(parents=True, exist_ok=True)

    for number in range(1, 10001):
        candidate_name = (
            name if number == 1 else f"{name}_{number:03d}"
        )
        candidate = render_root / candidate_name

        try:
            candidate.mkdir(exist_ok=False)
            return candidate
        except FileExistsError:
            continue

    raise ValueError(
        "Too many batches use this name. Choose a different batch pattern."
    )


def save_ui_state(window):
    preferences = window.preferences

    for key, field in (
        ("project_dir", window.project_dir),
        ("video_dir", window.video_dir),
        ("keyframe_dir", window.keyframe_dir),
    ):
        field.remember()
        preferences.setValue(
            "last_setup/" + key, field.text()
        )

    preferences.setValue(
        "last_setup/quality",
        window.quality.currentText(),
    )
    preferences.setValue(
        "last_setup/max_width",
        window.resolution.currentData(),
    )
    preferences.setValue(
        "last_setup/batch_pattern",
        window.batch_name_pattern.text(),
    )
    preferences.setValue(
        "last_setup/job_pattern",
        window.job_name_pattern.text(),
    )

    update_naming_preview(window)


def restore_ui_state(window):
    preferences = window.preferences
    previous_loading = window.loading_project
    window.loading_project = True

    try:
        for key, field in (
            ("project_dir", window.project_dir),
            ("video_dir", window.video_dir),
            ("keyframe_dir", window.keyframe_dir),
        ):
            value = preferences.value(
                "last_setup/" + key,
                field.text(),
            )
            if isinstance(value, str):
                field.setText(value)

        quality = preferences.value(
            "last_setup/quality", "Preview"
        )
        if quality in {"Preview", "Standard"}:
            window.quality.setCurrentText(quality)

        try:
            width = int(preferences.value(
                "last_setup/max_width", 512
            ))
        except (ValueError, TypeError):
            width = 512

        index = window.resolution.findData(width)
        if index >= 0:
            window.resolution.setCurrentIndex(index)

        batch = preferences.value(
            "last_setup/batch_pattern",
            DEFAULT_BATCH_PATTERN,
        )
        job = preferences.value(
            "last_setup/job_pattern",
            DEFAULT_JOB_PATTERN,
        )

        if isinstance(batch, str):
            window.batch_name_pattern.setText(batch)
        if isinstance(job, str):
            window.job_name_pattern.setText(job)

    finally:
        window.loading_project = previous_loading

    update_naming_preview(window)

    # Restore the last inputs, not an unsaved project's custom ranges.
    # Saved project files still restore their exact queue definitions.
    if (
        window.video_dir.text().strip()
        and window.keyframe_dir.text().strip()
    ):
        window.schedule_scan()
