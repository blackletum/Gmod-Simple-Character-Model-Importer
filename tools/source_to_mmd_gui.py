"""Source character export panel, independent of the forward game's settings."""

from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Callable

from PySide6 import QtCore, QtGui, QtWidgets


class SourceToMmdWorker(QtCore.QThread):
    """Keep the worker alive until the backend has stopped its subprocesses."""

    log = QtCore.Signal(str)
    stage = QtCore.Signal(int, str)
    result = QtCore.Signal(dict)
    failed = QtCore.Signal(str)
    cancelled = QtCore.Signal()

    def __init__(self, operation: str, arguments: dict, parent=None) -> None:
        super().__init__(parent)
        self.operation = operation
        self.arguments = arguments
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()
        self.requestInterruption()

    def run(self) -> None:
        try:
            import source_to_mmd_core as backend

            arguments = dict(self.arguments, progress=self.log.emit, cancel_check=self._cancel_event.is_set)
            if self.operation == "analyze":
                result = backend.analyze_source(**arguments)
            else:
                result = backend.convert_source(**arguments, stage_callback=self.stage.emit)
            if self._cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.result.emit(result)
        except Exception as exc:
            if self._cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.log.emit(traceback.format_exc())
                self.failed.emit(str(exc) or type(exc).__name__)


class SourceToMmdTab(QtWidgets.QWidget):
    taskStarted = QtCore.Signal(object)
    taskFinished = QtCore.Signal(object)

    def __init__(self, parent=None, *, busy_check: Callable[[], bool] | None = None,
                 preview_class=None, settings: QtCore.QSettings | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sourceToMmdTab")
        self._busy_check = busy_check
        self.settings = settings or QtCore.QSettings("MMDCharacterImporter", "SourceToMMD")
        self.worker: SourceToMmdWorker | None = None
        self.analysis: dict | None = None
        self.result: dict | None = None
        self._close_when_finished: Callable[[], None] | None = None
        self._result_paths: dict[str, Path] = {}
        self._path_rows: list[QtWidgets.QWidget] = []
        self._updating_meshes = False
        self._build_ui(preview_class)
        for key, edit in self._settings_fields().items():
            edit.setText(str(self.settings.value(key, "") or ""))
        for edit in self._settings_fields().values():
            edit.textChanged.connect(self._save_settings)
        for edit in (self.mdl_edit, self.materials_edit, self.output_edit):
            edit.textChanged.connect(self._invalidate_analysis)
        self._update_buttons()

    def _path_row(self, label: str, placeholder: str, file_filter: str | None = None) -> QtWidgets.QLineEdit:
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QtWidgets.QLineEdit()
        edit.setPlaceholderText(placeholder)
        button = QtWidgets.QPushButton("Browse…")
        button.setAccessibleName("Browse " + label)
        layout.addWidget(edit, 1)
        layout.addWidget(button)

        def browse() -> None:
            start = edit.text().strip()
            if not start and hasattr(self, "mdl_edit"):
                start = self.mdl_edit.text().strip()
            if file_filter:
                value, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Choose " + label, start, file_filter)
            else:
                if start and Path(start).is_file():
                    start = str(Path(start).parent)
                value = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose " + label, start)
            if value:
                edit.setText(value)

        button.clicked.connect(browse)
        self.path_form.addRow(label, row)
        self._path_rows.append(row)
        return edit

    def _build_ui(self, preview_class) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel("Source → MMD")
        font = heading.font()
        font.setPointSize(font.pointSize() + 5)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)
        intro = QtWidgets.QLabel("Convert a Source character into a PMX model. Analyze the model, choose its parts, then export and inspect the result.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        paths = QtWidgets.QGroupBox("Character and destination")
        self.path_form = QtWidgets.QFormLayout(paths)
        self.path_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.mdl_edit = self._path_row("Source model", "Select a .mdl with its companion files nearby", "Source models (*.mdl)")
        self.materials_edit = self._path_row("Materials folder", "Optional: materials folder or the extracted addon's root")
        self.output_edit = self._path_row("Output folder", "Destination for the PMX, textures, and working files")
        layout.addWidget(paths)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        selection = QtWidgets.QWidget()
        left = QtWidgets.QVBoxLayout(selection)
        left.setContentsMargins(0, 0, 0, 0)
        self.analysis_summary = QtWidgets.QLabel("Analyze a model to see its available parts and materials.")
        self.analysis_summary.setWordWrap(True)
        left.addWidget(self.analysis_summary)
        self.meshes = QtWidgets.QTreeWidget()
        self.meshes.setHeaderLabels(["Character parts", "Group"])
        self.meshes.setRootIsDecorated(False)
        self.meshes.setMinimumHeight(180)
        self.meshes.itemChanged.connect(self._mesh_changed)
        left.addWidget(self.meshes, 1)
        self.warnings = QtWidgets.QPlainTextEdit()
        self.warnings.setReadOnly(True)
        self.warnings.setPlaceholderText("Analysis notes and conversion warnings appear here.")
        self.warnings.setMaximumHeight(100)
        left.addWidget(self.warnings)
        splitter.addWidget(selection)

        preview_panel = QtWidgets.QWidget()
        right = QtWidgets.QVBoxLayout(preview_panel)
        right.setContentsMargins(0, 0, 0, 0)
        right.addWidget(QtWidgets.QLabel("Export preview"))
        self.preview = preview_class() if preview_class else None
        if self.preview:
            self.preview.setMinimumSize(360, 240)
            self.preview.set_bones_visible(False)
            right.addWidget(self.preview, 1)
            controls = QtWidgets.QHBoxLayout()
            bones = QtWidgets.QCheckBox("Show bones")
            bones.toggled.connect(self.preview.set_bones_visible)
            reset = QtWidgets.QPushButton("Reset view")
            reset.clicked.connect(self.preview.reset_front_view)
            controls.addWidget(bones)
            controls.addStretch(1)
            controls.addWidget(reset)
            right.addLayout(controls)
        else:
            label = QtWidgets.QLabel("Preview is unavailable. Exported PMX files can still be opened in MMD.")
            label.setWordWrap(True)
            right.addWidget(label, 1)
        self.preview_status = QtWidgets.QLabel("The exported model will appear here after conversion.")
        self.preview_status.setWordWrap(True)
        right.addWidget(self.preview_status)
        splitter.addWidget(preview_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

        options_toggle = QtWidgets.QCheckBox("Show additional options")
        layout.addWidget(options_toggle)
        self.advanced = QtWidgets.QGroupBox("Additional options")
        advanced = QtWidgets.QFormLayout(self.advanced)
        motion_row = QtWidgets.QWidget()
        motion_layout = QtWidgets.QHBoxLayout(motion_row)
        motion_layout.setContentsMargins(0, 0, 0, 0)
        self.motion_edit = QtWidgets.QLineEdit()
        self.motion_edit.setPlaceholderText("Optional .vmd for a motion check")
        motion_browse = QtWidgets.QPushButton("Browse…")
        motion_browse.clicked.connect(self._browse_motion)
        motion_layout.addWidget(self.motion_edit, 1)
        motion_layout.addWidget(motion_browse)
        advanced.addRow("Motion check (optional)", motion_row)
        motion_hint = QtWidgets.QLabel("The motion check runs in Blender. Check the final exported model's playback in MMD as well.")
        motion_hint.setWordWrap(True)
        advanced.addRow(motion_hint)
        layout.addWidget(self.advanced)
        self.advanced.hide()
        options_toggle.toggled.connect(self.advanced.setVisible)

        actions = QtWidgets.QHBoxLayout()
        self.analyze_button = QtWidgets.QPushButton("Analyze model")
        self.convert_button = QtWidgets.QPushButton("Convert to MMD")
        self.convert_button.setObjectName("primaryButton")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.analyze_button.clicked.connect(lambda: self._start("analyze"))
        self.convert_button.clicked.connect(lambda: self._start("convert"))
        self.cancel_button.clicked.connect(self.cancel)
        for button in (self.analyze_button, self.convert_button, self.cancel_button):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.status = QtWidgets.QLabel("Ready")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.validation_status = QtWidgets.QLabel()
        self.validation_status.setWordWrap(True)
        self.validation_status.hide()
        layout.addWidget(self.validation_status)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        results = QtWidgets.QHBoxLayout()
        self.result_buttons: dict[str, QtWidgets.QPushButton] = {}
        for key, title in (("output", "Open output"), ("pmx", "Open PMX"), ("blend", "Open Blender checkpoint"), ("motion", "Open motion preview"), ("report", "Open report"), ("log", "Open log")):
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(lambda _checked=False, name=key: self._open_result(name))
            self.result_buttons[key] = button
            results.addWidget(button)
        results.addStretch(1)
        layout.addLayout(results)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setPlaceholderText("Conversion progress and tool output")
        self.log.setMaximumHeight(140)
        layout.addWidget(self.log)

    def _settings_fields(self) -> dict[str, QtWidgets.QLineEdit]:
        return {"mdl": self.mdl_edit, "materials_root": self.materials_edit, "output_root": self.output_edit, "motion_path": self.motion_edit}

    def _save_settings(self, *_args) -> None:
        for key, edit in self._settings_fields().items():
            self.settings.setValue(key, edit.text().strip())

    def _browse_motion(self) -> None:
        value, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Choose test motion", self.motion_edit.text(), "MMD motion (*.vmd)")
        if value:
            self.motion_edit.setText(value)

    def _invalidate_analysis(self, *_args) -> None:
        self.analysis = None
        self.result = None
        self.meshes.clear()
        self._result_paths.clear()
        self.analysis_summary.setText("Analyze this model to choose its character parts.")
        self.warnings.clear()
        self.validation_status.hide()
        self.preview_status.setText("The exported model will appear here after conversion.")
        if self.preview:
            self.preview.clear_model()
        self._update_buttons()

    def is_running(self) -> bool:
        # Also cover the interval between result delivery and QThread.finished.
        return self.worker is not None

    def _selected_meshes(self) -> list[str]:
        return [str(self.meshes.topLevelItem(i).data(0, QtCore.Qt.ItemDataRole.UserRole))
                for i in range(self.meshes.topLevelItemCount())
                if self.meshes.topLevelItem(i).checkState(0) == QtCore.Qt.CheckState.Checked]

    def _mesh_changed(self, item, _column) -> None:
        if self._updating_meshes:
            return
        # Bodygroup alternatives are exclusive; mandatory meshes cannot be unchecked.
        self._updating_meshes = True
        try:
            mandatory = item.data(0, QtCore.Qt.ItemDataRole.UserRole + 2)
            group = item.data(0, QtCore.Qt.ItemDataRole.UserRole + 1)
            if mandatory:
                item.setCheckState(0, QtCore.Qt.CheckState.Checked)
            elif group is not None and item.checkState(0) == QtCore.Qt.CheckState.Checked:
                for i in range(self.meshes.topLevelItemCount()):
                    other = self.meshes.topLevelItem(i)
                    if other is not item and other.data(0, QtCore.Qt.ItemDataRole.UserRole + 1) == group:
                        other.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
        finally:
            self._updating_meshes = False
        self._update_buttons()

    def _update_buttons(self) -> None:
        running = self.is_running()
        has_input = bool(self.mdl_edit.text().strip() and self.output_edit.text().strip())
        self.analyze_button.setEnabled(not running and has_input)
        self.convert_button.setEnabled(not running and self.analysis is not None and bool(self._selected_meshes()))
        self.cancel_button.setEnabled(running and not self.worker.isInterruptionRequested())
        self.meshes.setEnabled(not running)
        self.advanced.setEnabled(not running)
        for row in self._path_rows:
            row.setEnabled(not running)
        for key, button in self.result_buttons.items():
            path = self._result_paths.get(key)
            button.setEnabled(bool(path and path.exists()))
            if key == "motion":
                button.setVisible(bool(path and path.exists()))

    def _validated_arguments(self) -> dict:
        mdl = Path(self.mdl_edit.text().strip()).expanduser()
        if mdl.suffix.lower() != ".mdl" or not mdl.is_file():
            raise ValueError("Choose an existing Source .mdl file.")
        materials_text = self.materials_edit.text().strip()
        materials = Path(materials_text).expanduser() if materials_text else None
        if materials and not materials.is_dir():
            raise ValueError("The materials folder does not exist.")
        output_text = self.output_edit.text().strip()
        if not output_text:
            raise ValueError("Choose an output folder.")
        output = Path(output_text).expanduser()
        if output.exists() and not output.is_dir():
            raise ValueError("The output destination is a file. Choose a folder.")
        return {"mdl": mdl, "materials_root": materials, "output_root": output}

    def _start(self, operation: str) -> None:
        if self.is_running() or (self._busy_check and self._busy_check()):
            self.status.setText("Another task is running. Wait for it to finish or cancel it first.")
            return
        try:
            arguments = self._validated_arguments()
            if operation == "convert":
                if not self.analysis or not self._selected_meshes():
                    raise ValueError("Analyze the model and select at least one character part first.")
                selected = self._selected_meshes()
                for group in self.analysis.get("mesh_groups", []):
                    if not group.get("allow_blank", False) and not set(selected).intersection(group.get("meshes", [])):
                        raise ValueError("Choose a part for the " + str(group.get("name", "character")) + " group.")
                options = {"analysis_manifest": self.analysis.get("manifest_path"), "selected_meshes": selected}
                motion_text = self.motion_edit.text().strip()
                if motion_text:
                    motion = Path(motion_text).expanduser()
                    if not motion.is_file() or motion.suffix.lower() != ".vmd":
                        raise ValueError("Choose an existing .vmd file for the optional motion check.")
                    options["motion_path"] = str(motion)
                arguments["options"] = options
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._save_settings()
        self.log.clear()
        self.result = None
        self._result_paths.clear()
        self._result_paths["output"] = arguments["output_root"]
        if operation == "analyze":
            self.analysis = None
            self.meshes.clear()
        self.warnings.clear()
        self.validation_status.hide()
        if self.preview:
            self.preview.clear_model()
        self.preview_status.setText("Waiting for the exported model.")
        self.progress.setRange(0, 0 if operation == "analyze" else 100)
        self.progress.setValue(0)
        self.status.setText("Analyzing character…" if operation == "analyze" else "Converting character…")
        worker = SourceToMmdWorker(operation, arguments, self)
        self.worker = worker
        worker.log.connect(self.log.appendPlainText)
        worker.stage.connect(self._on_stage)
        worker.result.connect(self._on_result)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(self._on_finished)
        self._update_buttons()
        self.taskStarted.emit(worker)
        worker.start()

    def _on_stage(self, percent: int, label: str) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(max(0, min(100, percent)))
        if not self.worker or not self.worker.isInterruptionRequested():
            self.status.setText(label)

    def _on_result(self, result: dict) -> None:
        operation = self.worker.operation if self.worker else "convert"
        self.result = result
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.warnings.setPlainText("\n".join(str(value) for value in result.get("warnings", [])))
        run_dir = result.get("run_dir") or result.get("output_dir")
        for key, raw in (("output", result.get("output_dir") or run_dir), ("pmx", result.get("pmx_path")),
                         ("blend", result.get("blend_path")), ("motion", result.get("motion_blend_path")),
                         ("report", result.get("report_path") or result.get("manifest_path")),
                         ("log", result.get("log_path"))):
            if raw:
                self._result_paths[key] = Path(raw)
        if operation == "analyze":
            self.analysis = result
            self._updating_meshes = True
            try:
                self.meshes.clear()
                defaults = set(result.get("default_meshes", result.get("mesh_names", [])))
                mandatory = set(result.get("mandatory_meshes", []))
                groups = {name: (index, group.get("name", "Part")) for index, group in enumerate(result.get("mesh_groups", [])) for name in group.get("meshes", [])}
                for name in result.get("mesh_names", []):
                    group_id, group_name = groups.get(name, (None, "Required" if name in mandatory else ""))
                    item = QtWidgets.QTreeWidgetItem([str(name), str(group_name)])
                    item.setData(0, QtCore.Qt.ItemDataRole.UserRole, str(name))
                    item.setData(0, QtCore.Qt.ItemDataRole.UserRole + 1, group_id)
                    item.setData(0, QtCore.Qt.ItemDataRole.UserRole + 2, name in mandatory)
                    item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(0, QtCore.Qt.CheckState.Checked if name in defaults or name in mandatory else QtCore.Qt.CheckState.Unchecked)
                    if name in mandatory:
                        item.setToolTip(0, "Required character mesh")
                    self.meshes.addTopLevelItem(item)
                self.meshes.resizeColumnToContents(0)
            finally:
                self._updating_meshes = False
            self.analysis_summary.setText(f"{self.meshes.topLevelItemCount()} character parts · {len(result.get('materials', []))} materials. Choose one alternative per group.")
            self.status.setText("Analysis complete. Review the parts and notes, then convert to MMD.")
        else:
            self.status.setText("Conversion complete. Inspect the preview and report, then test the PMX in MMD.")
            validation = result.get("validation")
            if isinstance(validation, dict):
                structural = "passed" if validation.get("ok") else "did not pass"
                motion = validation.get("motion_validation")
                if isinstance(motion, dict):
                    motion_state = "passed" if motion.get("ok") else "did not pass"
                    motion_text = f"Blender geometry samples {motion_state} ({len(motion.get('samples', []))} frames). Playback quality still needs review."
                else:
                    motion_text = "No motion check was run."
                self.validation_status.setText(f"Structural checks {structural}. {motion_text}")
                self.validation_status.show()
            pmx = self._result_paths.get("pmx")
            if pmx and pmx.is_file():
                self.preview_status.setText(str(pmx))
                if self.preview:
                    try:
                        self.preview.load_model(pmx)
                    except Exception as exc:
                        self.preview_status.setText("Export saved; preview could not load: " + str(exc))
                        self.log.appendPlainText(traceback.format_exc())
            else:
                self.status.setText("The converter returned without a PMX file. See the log and report.")
        self._update_buttons()

    def _on_failed(self, message: str) -> None:
        self.progress.setRange(0, 100)
        self.status.setText("Could not finish: " + message)
        self.log.appendPlainText("ERROR: " + message)

    def _on_cancelled(self) -> None:
        self.progress.setRange(0, 100)
        self.status.setText("Cancelled. Any saved checkpoints remain in the output folder.")
        self.log.appendPlainText("Cancelled by user.")

    def _on_finished(self) -> None:
        worker = self.worker
        self.worker = None
        if worker:
            self.taskFinished.emit(worker)
            worker.deleteLater()
        self._update_buttons()
        callback = self._close_when_finished
        self._close_when_finished = None
        if callback:
            QtCore.QTimer.singleShot(0, callback)

    def cancel(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.status.setText("Cancelling… waiting for the active conversion tools to stop.")
            self._update_buttons()

    def request_shutdown(self, callback: Callable[[], None]) -> bool:
        """Return False while the parent must remain alive for worker cleanup."""
        self._save_settings()
        self.settings.sync()
        if not self.is_running():
            return True
        self._close_when_finished = callback
        self.cancel()
        return False

    def _open_result(self, name: str) -> None:
        path = self._result_paths.get(name)
        if path and path.exists():
            if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path.resolve()))):
                self.status.setText("Could not open " + str(path))

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if not self.request_shutdown(self.close):
            event.ignore()
            return
        super().closeEvent(event)
