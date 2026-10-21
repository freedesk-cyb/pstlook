from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox


def _configurar_logging() -> None:
    from core.database import DATA_DIR

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(
                DATA_DIR / "pst_reader.log", encoding="utf-8"
            ),
            logging.StreamHandler(),
        ],
    )


def main() -> int:
    QApplication.setAttribute(
        Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True
    )

    app = QApplication(sys.argv)
    app.setApplicationName("PST Reader")
    app.setApplicationDisplayName("PST Reader")
    app.setOrganizationName("PSTReader")
    app.setStyle("Fusion")

    _configurar_logging()

    from core.database import Database
    from ui.main_window import MainWindow

    db = Database()
    try:
        db.crear_tablas()
    except Exception as exc:
        QMessageBox.critical(
            None,
            "PST Reader",
            f"No se pudo inicializar la base de datos local:\n{exc}",
        )
        return 1

    window = MainWindow(db)
    window.show()
    codigo = app.exec()
    db.cerrar()
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
