from __future__ import annotations

import html
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QMarginsF, QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices, QPageLayout, QPageSize
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

_EXTENSIONES_BLOQUEADAS = {
    ".bat", ".cmd", ".com", ".cpl", ".dll", ".exe", ".hta", ".iso", ".jar",
    ".js", ".jse", ".lnk", ".msi", ".msp", ".pif", ".ps1", ".reg", ".scr",
    ".sys", ".vb", ".vbe", ".vbs", ".wsf", ".wsh",
}
_EXTENSIONES_CON_MACROS = {
    ".doc", ".docm", ".dot", ".dotm", ".pot", ".potm",
    ".ppt", ".pptm", ".xls", ".xlsm", ".xlt", ".xltm",
}
_NOMBRES_RESERVADOS = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


def _nombre_temporal(nombre: str, respaldo: str) -> str:
    nombre = Path(str(nombre or "")).name.strip().rstrip(". ")
    return nombre or respaldo


def _nombre_pdf(asunto: str) -> str:
    nombre = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", asunto or "")
    nombre = nombre.strip().rstrip(". ")[:120]
    if not nombre:
        nombre = "correo"
    if nombre.split(".")[0].upper() in _NOMBRES_RESERVADOS:
        nombre = "_" + nombre
    return nombre if nombre.lower().endswith(".pdf") else f"{nombre}.pdf"


def _extraer_parte_html(documento: str, etiqueta: str) -> str:
    coincidencia = re.search(
        rf"<{etiqueta}\b[^>]*>(.*?)</{etiqueta}\s*>",
        documento,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return coincidencia.group(1) if coincidencia else ""


def _quitar_scripts(documento: str) -> str:
    documento = re.sub(
        r"<script\b[^>]*>.*?</script\s*>",
        "",
        documento,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return re.sub(
        r"<meta\b[^>]*http-equiv\s*=\s*[\"']?refresh[\"']?[^>]*>",
        "",
        documento,
        flags=re.IGNORECASE,
    )


def _marcar_origen_internet(ruta: Path) -> None:
    """Marca la copia para que Office/Adobe la abran en Vista protegida."""
    if os.name != "nt":
        return
    contenido = "[ZoneTransfer]\r\nZoneId=3\r\nHostUrl=about:internet\r\n"
    try:
        with open(
            f"{ruta}:Zone.Identifier", "w", encoding="utf-8", newline=""
        ) as archivo:
            archivo.write(contenido)
    except OSError:
        logger.warning("No se pudo marcar el adjunto como descargado", exc_info=True)


def _copiar_adjunto_temporal(origen: Path, nombre: str) -> Path:
    base = Path(tempfile.gettempdir()) / "PSTReader" / "abiertos"
    base.mkdir(parents=True, exist_ok=True)
    carpeta = Path(tempfile.mkdtemp(prefix="adjunto_", dir=base))
    destino = carpeta / _nombre_temporal(nombre, origen.name)
    shutil.copy2(origen, destino)
    _marcar_origen_internet(destino)
    return destino


def _extension_bloqueada(nombre: str) -> bool:
    return Path(nombre).suffix.lower() in _EXTENSIONES_BLOQUEADAS


def _tiene_macros(nombre: str) -> bool:
    return Path(nombre).suffix.lower() in _EXTENSIONES_CON_MACROS

_ESTILO_BASE = """
html, body {
    margin: 0;
    padding: 0;
    background: #ffffff;
    color: #202124;
    color-scheme: light;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 14px;
    line-height: 1.45;
    overflow-wrap: anywhere;
}
body { padding: 16px 18px 28px 18px; }
pre.plain {
    margin: 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 14px;
    line-height: 1.5;
}
img { max-width: 100%; height: auto; }
table { max-width: 100%; }
a { color: #1a73e8; }
blockquote {
    margin-left: 0;
    padding-left: 12px;
    border-left: 2px solid #dadce0;
    color: #5f6368;
}
"""

_ESTILO_PDF = """
@page { margin: 0; }
* { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
html, body {
    margin: 0;
    padding: 0;
    background: #ffffff;
    color: #202124;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.45;
    overflow-wrap: anywhere;
}
.pdf-header {
    border-bottom: 1px solid #d7dce2;
    margin-bottom: 16px;
    padding-bottom: 12px;
}
.pdf-subject {
    margin-bottom: 10px;
    color: #202124;
    font-size: 20pt;
    font-weight: 700;
    line-height: 1.25;
}
.pdf-meta {
    color: #5f6368;
    font-size: 9pt;
    line-height: 1.5;
}
.pdf-meta b { color: #3c4043; }
.pdf-body img { max-width: 100%; height: auto; }
.pdf-body table { max-width: 100%; }
.pdf-attachments {
    margin-top: 18px;
    border-top: 1px solid #d7dce2;
    padding-top: 10px;
    color: #3c4043;
    font-size: 9pt;
}
.pdf-attachments ul { margin: 5px 0 0 18px; padding: 0; }
.pdf-footer {
    margin-top: 22px;
    color: #9aa0a6;
    font-size: 8pt;
    text-align: right;
}
pre.plain {
    margin: 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.5;
}
"""


class _BloquearRed(QWebEngineUrlRequestInterceptor):
    """Impide que el contenido HTML del correo solicite recursos externos."""

    def interceptRequest(self, info) -> None:  # noqa: N802 (API de Qt)
        esquema = info.requestUrl().scheme().lower()
        if esquema in {"http", "https", "ftp", "ws", "wss", "file"}:
            info.block(True)


class _PaginaLocal(QWebEnginePage):
    def acceptNavigationRequest(  # noqa: N802 (API de Qt)
        self, url: QUrl, navigation_type, is_main_frame: bool
    ) -> bool:
        if (
            navigation_type
            == QWebEnginePage.NavigationType.NavigationTypeLinkClicked
        ):
            return False
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)


class _VistaCorreo(QWebEngineView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profile = QWebEngineProfile(self)
        self._interceptor = _BloquearRed(self._profile)
        self._profile.setUrlRequestInterceptor(self._interceptor)
        self._page = _PaginaLocal(self._profile, self)
        self.setPage(self._page)

        settings = self._page.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled, False
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False
        )


class EmailDetailWidget(QWidget):
    """Cabecera, cuerpo HTML/texto y adjuntos de un correo."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._adjuntos: list[dict[str, Any]] = []
        self._correo_actual: dict[str, Any] | None = None
        self._pdf_pendiente = False
        self._pdf_destino: Path | None = None
        self._pdf_token = 0
        self._mensaje_vacio = "Selecciona un correo para verlo aquí."
        self._colores = {
            "surface": "#ffffff",
            "text": "#202124",
            "muted": "#80868b",
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        cabecera = QFrame()
        cabecera.setObjectName("emailHeader")
        cabecera_layout = QVBoxLayout(cabecera)
        cabecera_layout.setContentsMargins(20, 16, 20, 14)
        cabecera_layout.setSpacing(5)

        self.subject_label = QLabel("Ningún correo seleccionado")
        self.subject_label.setObjectName("subjectLabel")
        self.subject_label.setWordWrap(True)
        self.subject_label.setTextFormat(Qt.TextFormat.PlainText)
        self.subject_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.from_label = QLabel("")
        self.from_label.setObjectName("emailMeta")
        self.from_label.setWordWrap(True)
        self.from_label.setTextFormat(Qt.TextFormat.PlainText)
        self.from_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.to_label = QLabel("")
        self.to_label.setObjectName("emailMeta")
        self.to_label.setWordWrap(True)
        self.to_label.setTextFormat(Qt.TextFormat.PlainText)
        self.to_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.date_label = QLabel("")
        self.date_label.setObjectName("mutedLabel")
        self.date_label.setTextFormat(Qt.TextFormat.PlainText)

        self.location_label = QLabel("")
        self.location_label.setObjectName("mutedLabel")
        self.location_label.setWordWrap(True)
        self.location_label.setTextFormat(Qt.TextFormat.PlainText)

        fila_asunto = QHBoxLayout()
        fila_asunto.setContentsMargins(0, 0, 0, 0)
        fila_asunto.setSpacing(10)
        fila_asunto.addWidget(self.subject_label, 1)

        self.pdf_button = QPushButton("Descargar PDF")
        self.pdf_button.setObjectName("pdfButton")
        self.pdf_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pdf_button.setToolTip("Guardar este correo como archivo PDF")
        fila_asunto.addWidget(
            self.pdf_button, 0, Qt.AlignmentFlag.AlignTop
        )

        cabecera_layout.addLayout(fila_asunto)
        cabecera_layout.addWidget(self.from_label)
        cabecera_layout.addWidget(self.to_label)
        cabecera_layout.addWidget(self.date_label)
        cabecera_layout.addWidget(self.location_label)
        layout.addWidget(cabecera)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.web_view = _VistaCorreo()
        splitter.addWidget(self.web_view)

        self._pdf_page = _PaginaLocal(self.web_view.page().profile(), self)
        ajustes_pdf = self._pdf_page.settings()
        ajustes_pdf.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled, False
        )
        ajustes_pdf.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        ajustes_pdf.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False
        )
        self._pdf_page.loadFinished.connect(self._pdf_pagina_cargada)
        self.pdf_button.clicked.connect(self._descargar_pdf)

        self.attachments_group = QGroupBox("Adjuntos")
        self.attachments_group.setObjectName("attachmentsGroup")
        adjuntos_layout = QVBoxLayout(self.attachments_group)
        adjuntos_layout.setContentsMargins(10, 10, 10, 10)

        self.attachments_table = QTableWidget(0, 4)
        self.attachments_table.setHorizontalHeaderLabels(
            ["Archivo", "Tamaño", "Abrir", "Guardar"]
        )
        self.attachments_table.verticalHeader().setVisible(False)
        self.attachments_table.setShowGrid(False)
        self.attachments_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.attachments_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.attachments_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.attachments_table.verticalHeader().setDefaultSectionSize(32)
        header = self.attachments_table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.attachments_table.setColumnWidth(2, 90)
        self.attachments_table.setColumnWidth(3, 130)
        adjuntos_layout.addWidget(self.attachments_table)

        splitter.addWidget(self.attachments_group)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([560, 170])
        layout.addWidget(splitter, 1)

        self.mostrar_vacio()

    def mostrar_vacio(self, mensaje: str = "Selecciona un correo para verlo aquí.") -> None:
        self._mensaje_vacio = mensaje
        self._adjuntos = []
        self._correo_actual = None
        self.pdf_button.setVisible(False)
        self.subject_label.setText("Ningún correo seleccionado")
        self.from_label.setText("")
        self.to_label.setText("")
        self.date_label.setText("")
        self.location_label.setText("")
        self.attachments_table.setRowCount(0)
        self.attachments_group.setVisible(False)
        self.web_view.page().setBackgroundColor(
            QColor(self._colores["surface"])
        )
        self.web_view.setHtml(self._documento_placeholder(mensaje))

    def aplicar_tema(self, colores: dict[str, str]) -> None:
        self._colores = dict(colores)
        if self._correo_actual is None:
            self.web_view.page().setBackgroundColor(
                QColor(self._colores["surface"])
            )
            self.web_view.setHtml(
                self._documento_placeholder(self._mensaje_vacio)
            )

    def mostrar_correo(
        self, correo: dict[str, Any], adjuntos: list[dict[str, Any]]
    ) -> None:
        asunto = correo.get("subject") or "(Sin asunto)"
        remitente_nombre = correo.get("sender_name") or ""
        remitente_correo = correo.get("sender_email") or ""
        if remitente_nombre and remitente_correo:
            remitente = f"{remitente_nombre} <{remitente_correo}>"
        else:
            remitente = remitente_nombre or remitente_correo or "(Desconocido)"
        destinatarios = correo.get("recipients") or "(Sin destinatarios)"

        self.subject_label.setText(str(asunto))
        self.from_label.setText(f"De: {remitente}")
        self.to_label.setText(f"Para: {destinatarios}")
        self.date_label.setText(
            self._fecha_legible(correo.get("sent_at", ""))
        )
        fuente = str(correo.get("source_name") or "")
        carpeta = str(
            correo.get("folder_path") or correo.get("folder_name") or ""
        )
        ubicacion = " · ".join(
            valor
            for valor in (
                f"PST: {fuente}" if fuente else "",
                f"Carpeta: {carpeta}" if carpeta else "",
            )
            if valor
        )
        self.location_label.setText(ubicacion)

        self._adjuntos = list(adjuntos)
        self._correo_actual = dict(correo)
        self._cargar_adjuntos()
        self.pdf_button.setVisible(True)
        self.web_view.page().setBackgroundColor(QColor("#ffffff"))
        self.web_view.setHtml(
            self._documento_correo(correo),
            QUrl("about:blank"),
        )

    def _documento_correo(self, correo: dict[str, Any]) -> str:
        body_html = str(correo.get("body_html") or "").strip()
        if body_html:
            return self._inyectar_estilo(body_html)

        body_text = str(correo.get("body_text") or "").strip()
        if not body_text:
            body_text = "(Este correo no contiene cuerpo de texto visible.)"
        cuerpo = f'<pre class="plain">{html.escape(body_text)}</pre>'
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<style>{_ESTILO_BASE}</style></head><body>{cuerpo}</body></html>"
        )

    @staticmethod
    def _inyectar_estilo(documento: str) -> str:
        etiqueta = f'<meta charset="utf-8"><style>{_ESTILO_BASE}</style>'
        minusculas = documento.lower()
        if "<head" in minusculas and "</head>" in minusculas:
            posicion = minusculas.find("</head>")
            return documento[:posicion] + etiqueta + documento[posicion:]
        if "<body" in minusculas:
            posicion = minusculas.find("<body")
            if "<html" in minusculas:
                return documento[:posicion] + etiqueta + documento[posicion:]
            return (
                "<!doctype html><html><head>"
                + etiqueta
                + "</head>"
                + documento[posicion:]
                + "</html>"
            )
        return (
            "<!doctype html><html><head>"
            + etiqueta
            + "</head><body>"
            + documento
            + "</body></html>"
        )

    def _documento_placeholder(self, mensaje: str) -> str:
        fondo = self._colores["surface"]
        color = self._colores["text"]
        tenue = self._colores["muted"]
        esquema = (
            "dark" if QColor(fondo).lightness() < 128 else "light"
        )
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            "<style>"
            "html, body { margin: 0; padding: 0;"
            f" background: {fondo}; color: {color};"
            f" color-scheme: {esquema};"
            ' font-family: "Segoe UI", Arial, sans-serif;'
            " font-size: 14px; }"
            f".placeholder {{ color: {tenue}; text-align: center;"
            " margin-top: 60px; padding: 0 24px; }"
            "</style></head><body>"
            f'<div class="placeholder">{html.escape(mensaje)}</div>'
            "</body></html>"
        )

    def _documento_pdf(self) -> str:
        correo = self._correo_actual or {}
        asunto = str(correo.get("subject") or "(Sin asunto)")
        remitente_nombre = str(correo.get("sender_name") or "")
        remitente_correo = str(correo.get("sender_email") or "")
        if remitente_nombre and remitente_correo:
            remitente = f"{remitente_nombre} <{remitente_correo}>"
        else:
            remitente = remitente_nombre or remitente_correo or "(Desconocido)"
        destinatarios = str(correo.get("recipients") or "(Sin destinatarios)")
        fecha = self._fecha_legible(correo.get("sent_at", ""))

        body_html = str(correo.get("body_html") or "").strip()
        head = ""
        if body_html:
            head = _quitar_scripts(_extraer_parte_html(body_html, "head"))
            cuerpo = _quitar_scripts(
                _extraer_parte_html(body_html, "body") or body_html
            )
        else:
            cuerpo = ""

        if not cuerpo.strip():
            body_text = str(correo.get("body_text") or "").strip()
            if not body_text:
                body_text = "(Este correo no contiene cuerpo de texto visible.)"
            cuerpo = f'<pre class="plain">{html.escape(body_text)}</pre>'

        if self._adjuntos:
            elementos = "".join(
                "<li>{} <span>({})</span></li>".format(
                    html.escape(str(adjunto.get("filename") or "(Sin nombre)")),
                    html.escape(
                        self._tamano_legible(
                            int(adjunto.get("size_bytes", 0) or 0)
                        )
                    ),
                )
                for adjunto in self._adjuntos
            )
            adjuntos_html = (
                f"<div class=\"pdf-attachments\"><b>Adjuntos "
                f"({len(self._adjuntos)})</b><ul>{elementos}</ul></div>"
            )
        else:
            adjuntos_html = ""

        return (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(asunto)}</title>"
            f"{head}<style>{_ESTILO_PDF}</style></head><body>"
            "<div class=\"pdf-header\">"
            f"<div class=\"pdf-subject\">{html.escape(asunto)}</div>"
            f"<div class=\"pdf-meta\"><b>De:</b> {html.escape(remitente)}<br>"
            f"<b>Para:</b> {html.escape(destinatarios)}<br>"
            f"<b>Fecha:</b> {html.escape(fecha)}</div>"
            "</div>"
            f"<div class=\"pdf-body\">{cuerpo}</div>"
            f"{adjuntos_html}"
            "<div class=\"pdf-footer\">Exportado desde PST Reader</div>"
            "</body></html>"
        )

    def _descargar_pdf(self) -> None:
        if self._correo_actual is None or self._pdf_pendiente:
            return

        asunto = str(self._correo_actual.get("subject") or "correo")
        destino, _ = QFileDialog.getSaveFileName(
            self,
            "Descargar correo en PDF",
            str(Path.home() / _nombre_pdf(asunto)),
            "Archivos PDF (*.pdf)",
        )
        if not destino:
            return

        ruta = Path(destino)
        if ruta.suffix.lower() != ".pdf":
            ruta = Path(f"{ruta}.pdf")

        self._pdf_token += 1
        token = self._pdf_token
        self._pdf_destino = ruta
        self._pdf_pendiente = True
        self.pdf_button.setEnabled(False)
        self.pdf_button.setText("Generando PDF...")
        QTimer.singleShot(30000, lambda: self._pdf_agotado(token))
        self._pdf_page.setHtml(self._documento_pdf(), QUrl("about:blank"))

    def _pdf_pagina_cargada(self, correcto: bool) -> None:
        if not self._pdf_pendiente:
            return
        if not correcto:
            self._pdf_error("No se pudo preparar el contenido del correo.")
            return

        pagina = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(12, 12, 12, 12),
            QPageLayout.Unit.Millimeter,
        )
        try:
            self._pdf_page.printToPdf(self._pdf_generado, pagina)
        except Exception as exc:
            logger.exception("No se pudo iniciar la generación del PDF")
            self._pdf_error(str(exc))

    def _pdf_generado(self, datos: bytes) -> None:
        if not self._pdf_pendiente or self._pdf_destino is None:
            return
        destino = self._pdf_destino
        self._restablecer_boton_pdf()

        if not datos:
            QMessageBox.warning(
                self,
                "No se pudo generar el PDF",
                "El motor de impresión devolvió un archivo vacío.",
            )
            return
        try:
            destino.write_bytes(bytes(datos))
        except OSError as exc:
            QMessageBox.critical(
                self,
                "No se pudo guardar el PDF",
                f"No se pudo escribir el archivo:\n{exc}",
            )
            return

        QMessageBox.information(
            self,
            "PDF guardado",
            f"El correo se guardó correctamente en:\n{destino}",
        )

    def _pdf_agotado(self, token: int) -> None:
        if token != self._pdf_token or not self._pdf_pendiente:
            return
        self._pdf_error(
            "La generación del PDF tardó demasiado. Inténtalo de nuevo."
        )

    def _pdf_error(self, mensaje: str) -> None:
        self._restablecer_boton_pdf()
        QMessageBox.warning(
            self,
            "No se pudo generar el PDF",
            mensaje or "Ocurrió un error desconocido.",
        )

    def _restablecer_boton_pdf(self) -> None:
        self._pdf_pendiente = False
        self._pdf_destino = None
        self.pdf_button.setEnabled(True)
        self.pdf_button.setText("Descargar PDF")

    def _cargar_adjuntos(self) -> None:
        self.attachments_table.clearContents()
        self.attachments_table.setRowCount(len(self._adjuntos))
        self.attachments_group.setTitle(f"Adjuntos ({len(self._adjuntos)})")
        self.attachments_group.setVisible(bool(self._adjuntos))

        for fila, adjunto in enumerate(self._adjuntos):
            nombre = str(adjunto.get("filename") or "(Sin nombre)")
            item_nombre = QTableWidgetItem(nombre)
            item_nombre.setToolTip(
                f"{nombre}\n{adjunto.get('mime_type', '')}".strip()
            )
            item_tamano = QTableWidgetItem(
                self._tamano_legible(int(adjunto.get("size_bytes", 0) or 0))
            )
            item_tamano.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.attachments_table.setItem(fila, 0, item_nombre)
            self.attachments_table.setItem(fila, 1, item_tamano)

            boton_abrir = QPushButton("Abrir")
            boton_abrir.clicked.connect(
                lambda _checked=False, datos=adjunto: self._abrir_adjunto(datos)
            )
            self.attachments_table.setCellWidget(fila, 2, boton_abrir)

            boton_guardar = QPushButton("Guardar como")
            boton_guardar.clicked.connect(
                lambda _checked=False, datos=adjunto: self._guardar_adjunto(datos)
            )
            self.attachments_table.setCellWidget(fila, 3, boton_guardar)

    def _abrir_adjunto(self, adjunto: dict[str, Any]) -> None:
        origen = Path(str(adjunto.get("stored_path") or ""))
        if not origen.is_file():
            QMessageBox.warning(
                self,
                "Adjunto no disponible",
                "El archivo del adjunto ya no existe en la carpeta data/attachments.",
            )
            return

        nombre = str(adjunto.get("filename") or origen.name)
        if _extension_bloqueada(nombre):
            QMessageBox.warning(
                self,
                "Apertura bloqueada",
                "Por seguridad, este tipo de archivo ejecutable no se abre "
                "directamente desde la aplicación.",
            )
            return

        aviso = (
            "Se abrirá una copia temporal con la aplicación predeterminada de "
            "Windows:\n\n"
            f"{nombre}\n\n"
            "El adjunto original no se modificará."
        )
        if _tiene_macros(nombre):
            aviso += (
                "\n\nEste tipo de archivo puede contener macros. La copia se "
                "marcará como descargada para que Office la abra en Vista "
                "protegida, pero ábrela solo si confías en el remitente."
            )

        respuesta = QMessageBox.question(
            self,
            "Abrir adjunto",
            aviso,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return

        try:
            destino = _copiar_adjunto_temporal(origen, nombre)
        except OSError as exc:
            QMessageBox.critical(
                self,
                "No se pudo preparar el adjunto",
                f"No se pudo crear la copia temporal:\n{exc}",
            )
            return

        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(destino))):
            QMessageBox.warning(
                self,
                "No se pudo abrir el adjunto",
                "Windows no encontró una aplicación asociada para este tipo de "
                f"archivo.\n\nLa copia está en:\n{destino}",
            )

    def _guardar_adjunto(self, adjunto: dict[str, Any]) -> None:
        origen = Path(str(adjunto.get("stored_path") or ""))
        if not origen.is_file():
            QMessageBox.warning(
                self,
                "Adjunto no disponible",
                "El archivo del adjunto ya no existe en la carpeta data/attachments.",
            )
            return

        destino, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar adjunto",
            str(Path.home() / origen.name),
            "Todos los archivos (*)",
        )
        if not destino:
            return
        try:
            shutil.copy2(origen, destino)
        except OSError as exc:
            QMessageBox.critical(
                self, "No se pudo guardar el adjunto", str(exc)
            )

    @staticmethod
    def _fecha_legible(valor: str) -> str:
        if not valor:
            return ""
        try:
            fecha = datetime.fromisoformat(str(valor))
        except (TypeError, ValueError):
            return str(valor)
        return fecha.strftime("%d/%m/%Y %H:%M")

    @staticmethod
    def _tamano_legible(bytes_: int) -> str:
        if bytes_ < 1024:
            return f"{bytes_} B"
        if bytes_ < 1024 * 1024:
            return f"{bytes_ / 1024:.1f} KB"
        return f"{bytes_ / (1024 * 1024):.1f} MB"
