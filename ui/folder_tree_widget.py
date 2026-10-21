from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QMenu,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from core.database import MAX_PST_SOURCES

_ROLE_FOLDER = Qt.ItemDataRole.UserRole
_ROLE_NAME = Qt.ItemDataRole.UserRole + 1
_ROLE_SOURCE = Qt.ItemDataRole.UserRole + 2
_ROLE_SOURCE_NAME = Qt.ItemDataRole.UserRole + 3


class FolderTreeWidget(QWidget):
    """Árbol agrupado por PST, con una entrada global para ver todo."""

    folder_selected = Signal(object, str, object)
    source_remove_requested = Signal(int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: dict[int, QStandardItem] = {}
        self._source_items: dict[int, QStandardItem] = {}
        self._item_todos: QStandardItem | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(8)

        titulo = QLabel("PST y carpetas")
        titulo.setObjectName("panelTitle")
        layout.addWidget(titulo)

        self.tree = QTreeView()
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.tree.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.tree.setUniformRowHeights(True)
        self.tree.setAnimated(True)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.tree.customContextMenuRequested.connect(self._menu_contextual)

        self.model = QStandardItemModel(self)
        self.model.setHorizontalHeaderLabels(["PST y carpetas"])
        self.tree.setModel(self.model)
        self.tree.selectionModel().currentChanged.connect(
            self._al_cambiar_seleccion
        )

        layout.addWidget(self.tree, 1)

        self.hint_label = QLabel("")
        self.hint_label.setObjectName("mutedLabel")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

    def cargar_carpetas(
        self,
        carpetas: list[dict[str, Any]],
        fuentes: list[dict[str, Any]],
        preserve_id: int | None = None,
        preserve_source_id: int | None = None,
    ) -> None:
        seleccion_modelo = self.tree.selectionModel()
        bloqueo = seleccion_modelo.blockSignals(True)
        try:
            self.model.clear()
            self.model.setHorizontalHeaderLabels(["PST y carpetas"])
            self._items.clear()
            self._source_items.clear()

            total = sum(
                int(fuente.get("email_count", 0)) for fuente in fuentes
            )
            self._item_todos = QStandardItem(
                self._texto_carpeta("Todos los correos", total)
            )
            self._item_todos.setData(0, _ROLE_FOLDER)
            self._item_todos.setData(
                "Todos los correos", _ROLE_NAME
            )
            self._item_todos.setToolTip(
                "Todos los correos de todos los PST importados"
            )
            self.model.appendRow(self._item_todos)

            for fuente in fuentes:
                source_id = int(fuente["id"])
                source_name = str(fuente.get("name") or "PST")
                source_count = int(fuente.get("email_count", 0))
                item = QStandardItem(
                    self._texto_carpeta(source_name, source_count)
                )
                item.setData(0, _ROLE_FOLDER)
                item.setData(source_name, _ROLE_NAME)
                item.setData(source_id, _ROLE_SOURCE)
                item.setData(source_name, _ROLE_SOURCE_NAME)
                item.setToolTip(str(fuente.get("path") or source_name))
                self.model.appendRow(item)
                self._source_items[source_id] = item

            for carpeta in carpetas:
                folder_id = int(carpeta["id"])
                parent_id = carpeta.get("parent_id")
                source_id = int(carpeta.get("source_id") or 0)
                fuente_item = self._source_items.get(source_id)
                if fuente_item is None:
                    continue
                source_name = str(
                    carpeta.get("source_name")
                    or fuente_item.data(_ROLE_NAME)
                    or "PST"
                )

                if parent_id:
                    padre = self._items.get(int(parent_id))
                    if padre is None:
                        padre = fuente_item
                else:
                    padre = fuente_item

                item = QStandardItem(
                    self._texto_carpeta(
                        str(carpeta.get("name") or "(Sin nombre)"),
                        int(carpeta.get("email_count", 0)),
                    )
                )
                item.setData(folder_id, _ROLE_FOLDER)
                item.setData(
                    str(carpeta.get("name") or "(Sin nombre)"),
                    _ROLE_NAME,
                )
                item.setData(source_id, _ROLE_SOURCE)
                item.setData(source_name, _ROLE_SOURCE_NAME)
                item.setToolTip(
                    f"{source_name}\n{carpeta.get('path') or ''}".strip()
                )
                padre.appendRow(item)
                self._items[folder_id] = item

            self.tree.expandAll()

            item_seleccionado = (
                self._items.get(preserve_id) if preserve_id else None
            )
            if item_seleccionado is None and preserve_source_id:
                item_seleccionado = self._source_items.get(
                    preserve_source_id
                )
            if item_seleccionado is None:
                item_seleccionado = self._item_todos
            self.tree.setCurrentIndex(item_seleccionado.index())
            self.tree.scrollTo(item_seleccionado.index())
        finally:
            seleccion_modelo.blockSignals(bloqueo)

        self.hint_label.setText(
            f"{len(fuentes)} de {MAX_PST_SOURCES} PST · "
            "clic derecho para quitar"
            if fuentes
            else f"0 de {MAX_PST_SOURCES} PST · usa «Agregar PST»"
        )

        if self._item_todos is not None:
            indice = self.tree.currentIndex()
            item = self.model.itemFromIndex(indice) if indice.isValid() else None
            if item is None:
                item = self._item_todos
            self._emitir_seleccion(item)

    @staticmethod
    def _texto_carpeta(nombre: str, cantidad: int) -> str:
        return f"{nombre}  ({cantidad})" if cantidad else nombre

    def _al_cambiar_seleccion(self, actual, anterior) -> None:
        if not actual.isValid():
            return
        item = self.model.itemFromIndex(actual)
        if item is not None:
            self._emitir_seleccion(item)

    def _emitir_seleccion(self, item: QStandardItem) -> None:
        folder_id = item.data(_ROLE_FOLDER)
        nombre = item.data(_ROLE_NAME) or "Todos los correos"
        source_data = item.data(_ROLE_SOURCE)
        source_id = int(source_data) if source_data else None
        self.folder_selected.emit(folder_id, str(nombre), source_id)

    def _menu_contextual(self, posicion) -> None:
        indice = self.tree.indexAt(posicion)
        if not indice.isValid():
            return
        item = self.model.itemFromIndex(indice)
        if item is None:
            return
        source_data = item.data(_ROLE_SOURCE)
        if not source_data:
            return
        source_id = int(source_data)
        source_name = str(
            item.data(_ROLE_SOURCE_NAME) or "PST"
        )

        menu = QMenu(self)
        accion = menu.addAction(f"Quitar PST «{source_name}»")
        elegida = menu.exec(self.tree.viewport().mapToGlobal(posicion))
        if elegida is accion:
            self.source_remove_requested.emit(source_id, source_name)
