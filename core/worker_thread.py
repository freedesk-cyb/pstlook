from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .database import Database
from .pst_extractor import extraer_pst

logger = logging.getLogger(__name__)


class PSTWorker(QThread):
    """Importa un PST fuera del hilo de la interfaz.

    QThread ya define una señal ``finished`` sin argumentos. Para transportar
    el resultado de la importación se usa ``import_finished``, que se emite
    justo antes de que el hilo termine.
    """

    progress_updated = Signal(int, str)
    import_finished = Signal(int, str)
    error = Signal(str)

    def __init__(
        self,
        pst_path: str | Path,
        db: Database,
        attachments_dir: str | Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.pst_path = Path(pst_path)
        self.db = db
        self.attachments_dir = Path(attachments_dir) if attachments_dir else None

    def _progreso(self, procesados: int, total: int, mensaje: str) -> None:
        if total > 0:
            porcentaje = max(0, min(100, int(procesados * 100 / total)))
        else:
            porcentaje = -1
        self.progress_updated.emit(porcentaje, mensaje)

    def run(self) -> None:
        try:
            self.db.crear_tablas()
            importados = extraer_pst(
                self.pst_path,
                self.db,
                attachments_dir=self.attachments_dir,
                progress_callback=self._progreso,
            )
        except Exception as exc:
            logger.exception("Falló la importación del PST")
            self.error.emit(str(exc))
            return
        else:
            self.import_finished.emit(importados, str(self.pst_path))
        finally:
            self.db.cerrar()
