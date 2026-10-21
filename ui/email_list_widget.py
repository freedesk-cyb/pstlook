from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class EmailListWidget(QWidget):
    """Lista de correos de la carpeta seleccionada."""

    email_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._emails: list[dict[str, Any]] = []
        self._cargando = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(6)

        cabecera = QHBoxLayout()
        self.title_label = QLabel("Todos los correos")
        self.title_label.setObjectName("panelTitle")
        self.count_label = QLabel("0")
        self.count_label.setObjectName("mutedLabel")
        cabecera.addWidget(self.title_label, 1)
        cabecera.addWidget(self.count_label)
        layout.addLayout(cabecera)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Remitente", "Asunto", "Fecha"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setWordWrap(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.table.verticalHeader().setDefaultSectionSize(34)

        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 205)
        self.table.setColumnWidth(2, 125)

        self.table.itemSelectionChanged.connect(self._al_seleccionar)
        layout.addWidget(self.table, 1)

    def cargar_correos(
        self, emails: list[dict[str, Any]], titulo: str = "Todos los correos"
    ) -> None:
        self._cargando = True
        self._emails = list(emails)
        self.title_label.setText(titulo)
        self.count_label.setText(str(len(emails)))
        self.table.clearSelection()
        self.table.clearContents()
        self.table.setRowCount(len(emails))

        for fila, correo in enumerate(emails):
            remitente = (
                correo.get("sender_name")
                or correo.get("sender_email")
                or "(Desconocido)"
            )
            asunto = correo.get("subject") or "(Sin asunto)"
            fecha = self._fecha_legible(correo.get("sent_at", ""))

            item_remitente = QTableWidgetItem(str(remitente))
            item_remitente.setToolTip(
                f"{remitente}\n{correo.get('sender_email', '')}".strip()
            )
            item_remitente.setData(Qt.ItemDataRole.UserRole, correo.get("id"))

            item_asunto = QTableWidgetItem(str(asunto))
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
            item_asunto.setToolTip(
                f"{asunto}\n{ubicacion}".strip()
            )
            item_asunto.setData(Qt.ItemDataRole.UserRole, correo.get("id"))

            item_fecha = QTableWidgetItem(fecha)
            item_fecha.setData(Qt.ItemDataRole.UserRole, correo.get("id"))
            item_fecha.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

            self.table.setItem(fila, 0, item_remitente)
            self.table.setItem(fila, 1, item_asunto)
            self.table.setItem(fila, 2, item_fecha)

        self._cargando = False

    def limpiar(self, titulo: str = "Todos los correos") -> None:
        self.cargar_correos([], titulo)

    @staticmethod
    def _fecha_legible(valor: str) -> str:
        if not valor:
            return ""
        try:
            fecha = datetime.fromisoformat(str(valor))
        except (TypeError, ValueError):
            return str(valor)
        ahora = datetime.now()
        if fecha.date() == ahora.date():
            return fecha.strftime("%H:%M")
        if fecha.year == ahora.year:
            return fecha.strftime("%d/%m")
        return fecha.strftime("%d/%m/%Y")

    def _al_seleccionar(self) -> None:
        if self._cargando:
            return
        fila = self.table.currentRow()
        if fila < 0:
            return
        item = self.table.item(fila, 0)
        if item is None:
            return
        email_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(email_id, int):
            self.email_selected.emit(email_id)
