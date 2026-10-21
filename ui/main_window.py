from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.database import MAX_PST_SOURCES, Database
from core.worker_thread import PSTWorker
from ui.email_detail_widget import EmailDetailWidget
from ui.email_list_widget import EmailListWidget
from ui.folder_tree_widget import FolderTreeWidget
from ui.themes import (
    THEMES,
    build_palette,
    build_stylesheet,
    theme_colors,
    theme_key,
)


class MainWindow(QMainWindow):
    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.worker: PSTWorker | None = None
        self.current_folder_id: int | None = None
        self.current_source_id: int | None = None
        self.current_folder_name = "Todos los correos"
        self._ultima_carpeta_pst = str(Path.home())
        self._recargar_tras_error = False
        self._tema_actual = theme_key(
            str(QSettings().value("apariencia/tema", "claro"))
        )

        self.setWindowTitle("PST Reader")
        self.resize(1420, 860)
        self.setMinimumSize(980, 620)

        self._crear_interfaz()
        self._crear_atajos()
        self._conectar_senales()
        self._aplicar_tema(self._tema_actual, guardar=False)
        self._cargar_carpetas()

    def _crear_interfaz(self) -> None:
        central = QWidget()
        central.setObjectName("centralWidget")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        barra = QWidget()
        barra.setObjectName("topBar")
        barra_layout = QHBoxLayout(barra)
        barra_layout.setContentsMargins(18, 11, 18, 11)
        barra_layout.setSpacing(12)

        titulo_app = QLabel("PST Reader")
        titulo_app.setObjectName("appTitle")

        self.open_button = QPushButton("Agregar PST")
        self.open_button.setObjectName("openButton")
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.setToolTip(
            f"Agregar un PST (máximo {MAX_PST_SOURCES})"
        )

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("searchEdit")
        self.search_edit.setPlaceholderText(
            "Buscar por asunto, remitente o cuerpo..."
        )
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(260)
        self.search_edit.setMaximumWidth(720)

        self.progress_label = QLabel("")
        self.progress_label.setObjectName("progressLabel")
        self.progress_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.progress_label.setMinimumWidth(90)
        self.progress_label.setMaximumWidth(300)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(150)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setVisible(False)

        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("themeCombo")
        self.theme_combo.setToolTip(
            "Cambiar el tema de colores de la aplicación"
        )
        self.theme_combo.setMinimumWidth(165)
        self.theme_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for clave, tema in THEMES.items():
            self.theme_combo.addItem(str(tema["label"]), clave)
        indice_tema = self.theme_combo.findData(self._tema_actual)
        self.theme_combo.setCurrentIndex(max(indice_tema, 0))

        barra_layout.addWidget(titulo_app)
        barra_layout.addWidget(self.open_button)
        barra_layout.addSpacing(10)
        barra_layout.addWidget(self.search_edit, 1)
        barra_layout.addWidget(self.progress_label)
        barra_layout.addWidget(self.progress_bar)
        barra_layout.addWidget(self.theme_combo)
        layout.addWidget(barra)

        self.folder_tree = FolderTreeWidget()
        self.email_list = EmailListWidget()
        self.email_detail = EmailDetailWidget()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.folder_tree)
        splitter.addWidget(self.email_list)
        splitter.addWidget(self.email_detail)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([230, 425, 765])
        layout.addWidget(splitter, 1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Listo")

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)

    def _crear_atajos(self) -> None:
        accion_abrir = QAction("Agregar archivo PST", self)
        accion_abrir.setShortcut(QKeySequence(QKeySequence.StandardKey.Open))
        accion_abrir.triggered.connect(self._abrir_pst)
        self.addAction(accion_abrir)

        accion_buscar = QAction("Buscar", self)
        accion_buscar.setShortcut(QKeySequence(QKeySequence.StandardKey.Find))
        accion_buscar.triggered.connect(self._enfocar_busqueda)
        self.addAction(accion_buscar)

    def _conectar_senales(self) -> None:
        self.open_button.clicked.connect(self._abrir_pst)
        self.folder_tree.folder_selected.connect(self._al_seleccionar_carpeta)
        self.folder_tree.source_remove_requested.connect(self._quitar_fuente)
        self.email_list.email_selected.connect(self._al_seleccionar_correo)
        self.search_edit.textChanged.connect(self._programar_busqueda)
        self.search_edit.returnPressed.connect(self._aplicar_busqueda)
        self.search_timer.timeout.connect(self._aplicar_busqueda)
        self.theme_combo.currentIndexChanged.connect(self._cambiar_tema)

    def _aplicar_tema(self, clave: str, guardar: bool = True) -> None:
        clave = theme_key(clave)
        self._tema_actual = clave
        self.setStyleSheet(build_stylesheet(clave))
        app = QApplication.instance()
        if app is not None:
            app.setPalette(build_palette(clave))
        if hasattr(self, "email_detail"):
            self.email_detail.aplicar_tema(theme_colors(clave))
        if guardar:
            QSettings().setValue("apariencia/tema", clave)

    def _cambiar_tema(self, _indice: int) -> None:
        clave = self.theme_combo.currentData()
        if isinstance(clave, str):
            self._aplicar_tema(clave)

    def _enfocar_busqueda(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _programar_busqueda(self, _texto: str) -> None:
        self.search_timer.start()

    def _aplicar_busqueda(self) -> None:
        self.search_timer.stop()
        self._cargar_correos()

    def _cargar_carpetas(
        self,
        preserve_id: int | None = None,
        preserve_source_id: int | None = None,
    ) -> None:
        try:
            carpetas = self.db.listar_carpetas()
            fuentes = self.db.listar_fuentes()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Error de base de datos",
                f"No se pudieron leer las carpetas:\n{exc}",
            )
            return
        self.folder_tree.cargar_carpetas(
            carpetas,
            fuentes,
            preserve_id,
            preserve_source_id,
        )

    def _al_seleccionar_carpeta(
        self, folder_id, folder_name: str, source_id
    ) -> None:
        self.current_folder_id = int(folder_id) if folder_id else None
        self.current_source_id = int(source_id) if source_id else None
        self.current_folder_name = folder_name or "Todos los correos"
        self._cargar_correos()

    def _cargar_correos(self) -> None:
        texto = self.search_edit.text().strip()
        try:
            if texto:
                correos = self.db.buscar_correos(
                    texto,
                    self.current_folder_id,
                    self.current_source_id,
                )
                titulo = f"Resultados en {self.current_folder_name}"
            else:
                correos = self.db.listar_correos(
                    self.current_folder_id,
                    self.current_source_id,
                )
                titulo = self.current_folder_name
        except Exception as exc:
            self.email_list.limpiar(self.current_folder_name)
            self.email_detail.mostrar_vacio("No se pudieron cargar los correos.")
            self.statusBar().showMessage(f"Error al consultar: {exc}")
            return

        self.email_list.cargar_correos(correos, titulo)
        self.email_detail.mostrar_vacio()
        if correos:
            self.statusBar().showMessage(
                f"{len(correos)} correos en {self.current_folder_name}"
            )
        else:
            self.statusBar().showMessage(
                "No hay correos que coincidan con la selección"
            )

    def _al_seleccionar_correo(self, email_id: int) -> None:
        correo = self.db.obtener_correo(email_id)
        if correo is None:
            self.email_detail.mostrar_vacio(
                "El correo ya no está disponible en la base local."
            )
            return
        adjuntos = self.db.obtener_adjuntos(email_id)
        self.email_detail.mostrar_correo(correo, adjuntos)

    def _abrir_pst(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return

        try:
            total_fuentes = self.db.contar_fuentes()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Error de base de datos",
                f"No se pudo consultar los PST importados:\n{exc}",
            )
            return
        if total_fuentes >= MAX_PST_SOURCES:
            QMessageBox.information(
                self,
                "Límite de PST alcanzado",
                f"Ya hay {MAX_PST_SOURCES} PST importados.\n"
                "Haz clic derecho sobre un PST del panel izquierdo "
                "y elige «Quitar PST» antes de agregar otro.",
            )
            return

        ruta, _ = QFileDialog.getOpenFileName(
            self,
            "Agregar archivo PST",
            self._ultima_carpeta_pst,
            "Archivos PST (*.pst);;Todos los archivos (*)",
        )
        if not ruta:
            return

        pst_path = Path(ruta)
        if not pst_path.is_file():
            QMessageBox.warning(
                self,
                "Archivo no encontrado",
                "El archivo PST seleccionado no existe.",
            )
            return
        self._ultima_carpeta_pst = str(pst_path.parent)

        try:
            existente = self.db.fuente_por_ruta(pst_path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Error de base de datos",
                f"No se pudo comprobar el PST:\n{exc}",
            )
            return
        if existente is not None:
            QMessageBox.information(
                self,
                "PST ya importado",
                "Este PST ya está importado como "
                f"«{existente.get('name', '')}».\n"
                "Para volver a importarlo, quítalo primero desde el "
                "panel izquierdo.",
            )
            return

        self.worker = PSTWorker(pst_path, self.db)
        self.worker.progress_updated.connect(self._actualizar_progreso)
        self.worker.import_finished.connect(self._importacion_terminada)
        self.worker.error.connect(self._importacion_error)
        self.worker.finished.connect(self._hilo_terminado)

        self.open_button.setEnabled(False)
        self.search_edit.setEnabled(False)
        self.folder_tree.setEnabled(False)
        self.email_list.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setText("Agregando PST...")
        self.statusBar().showMessage(
            f"Agregando PST ({total_fuentes + 1} de {MAX_PST_SOURCES})..."
        )
        self.worker.start()

    def _actualizar_progreso(self, porcentaje: int, mensaje: str) -> None:
        if porcentaje < 0:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(porcentaje)
        texto_corto = self.progress_label.fontMetrics().elidedText(
            mensaje, Qt.TextElideMode.ElideRight, 330
        )
        self.progress_label.setText(texto_corto)
        self.progress_label.setToolTip(mensaje)
        self.statusBar().showMessage(mensaje)

    def _importacion_terminada(self, importados: int, ruta: str) -> None:
        self.open_button.setEnabled(True)
        self.search_edit.setEnabled(True)
        self.folder_tree.setEnabled(True)
        self.email_list.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        self.progress_label.setToolTip("")
        self._cargar_carpetas(
            preserve_id=self.current_folder_id,
            preserve_source_id=self.current_source_id,
        )
        try:
            total_fuentes = self.db.contar_fuentes()
        except Exception:
            total_fuentes = 0
        self.statusBar().showMessage(
            f"Importación completada: {importados} correos desde "
            f"{Path(ruta).name} ({total_fuentes} de "
            f"{MAX_PST_SOURCES} PST)"
        )
        QMessageBox.information(
            self,
            "Importación completada",
            f"Se agregaron {importados} correos desde:\n{ruta}\n\n"
            f"PST importados: {total_fuentes} de {MAX_PST_SOURCES}.",
        )

    def _importacion_error(self, mensaje: str) -> None:
        self.open_button.setEnabled(True)
        self.search_edit.setEnabled(True)
        self.folder_tree.setEnabled(True)
        self.email_list.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        self.progress_label.setToolTip("")
        self._recargar_tras_error = True
        self.statusBar().showMessage("La importación no pudo completarse")
        QMessageBox.critical(
            self,
            "Error al importar el PST",
            mensaje or "Ocurrió un error desconocido.",
        )

    def _hilo_terminado(self) -> None:
        hilo = self.sender()
        if self.worker is hilo:
            self.worker = None
        if isinstance(hilo, PSTWorker):
            hilo.deleteLater()
        if self._recargar_tras_error:
            self._recargar_tras_error = False
            self._cargar_carpetas(
                preserve_id=self.current_folder_id,
                preserve_source_id=self.current_source_id,
            )

    def _quitar_fuente(self, source_id: int, source_name: str) -> None:
        if self.worker is not None and self.worker.isRunning():
            return

        respuesta = QMessageBox.question(
            self,
            "Quitar PST",
            f"¿Quitar el PST «{source_name}»?\n\n"
            "Se eliminarán de la base local sus correos y adjuntos. "
            "El archivo .pst original no se modifica.\n\n"
            "¿Quieres continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return

        try:
            eliminados = self.db.eliminar_fuente(int(source_id))
        except Exception as exc:
            QMessageBox.critical(
                self,
                "No se pudo quitar el PST",
                f"{exc}",
            )
            return

        if self.current_source_id == int(source_id):
            self.current_folder_id = None
            self.current_source_id = None
            self.current_folder_name = "Todos los correos"

        self._cargar_carpetas(
            preserve_id=self.current_folder_id,
            preserve_source_id=self.current_source_id,
        )
        self.statusBar().showMessage(
            f"PST quitado: {source_name} ({eliminados} correos eliminados)"
        )

    def closeEvent(self, event) -> None:  # noqa: N802 (API de Qt)
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(
                self,
                "Importación en curso",
                "Espera a que termine la importación antes de cerrar la aplicación.",
            )
            event.ignore()
            return
        self.db.cerrar()
        event.accept()
