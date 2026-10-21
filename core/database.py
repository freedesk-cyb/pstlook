from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_PST_SOURCES = 5


def _directorio_datos() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PSTReader"
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "data"


DATA_DIR = _directorio_datos()
ATTACHMENTS_DIR = DATA_DIR / "attachments"
DEFAULT_DB_PATH = DATA_DIR / "pst_data.db"


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, bytes):
        return valor.decode("utf-8", errors="replace").replace("\x00", "")
    return str(valor).replace("\x00", "")


def _ruta_normalizada(ruta: str | Path) -> str:
    try:
        return str(Path(ruta).resolve())
    except OSError:
        return str(ruta)


class Database:
    """Acceso a la base SQLite local.

    Cada hilo obtiene su propia conexión, de modo que el hilo de extracción
    puede escribir mientras la interfaz mantiene sus propias lecturas.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

    def _conexion(self) -> sqlite3.Connection:
        conexion = getattr(self._local, "conexion", None)
        if conexion is None:
            conexion = sqlite3.connect(str(self.db_path), timeout=30.0)
            conexion.row_factory = sqlite3.Row
            conexion.execute("PRAGMA foreign_keys = ON")
            conexion.execute("PRAGMA journal_mode = WAL")
            conexion.execute("PRAGMA synchronous = NORMAL")
            conexion.execute("PRAGMA busy_timeout = 5000")
            self._local.conexion = conexion
        return conexion

    def crear_tablas(self) -> None:
        conexion = self._conexion()
        try:
            conexion.executescript(
                """
                CREATE TABLE IF NOT EXISTS pst_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL DEFAULT '',
                    imported_at TEXT NOT NULL DEFAULT ''
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_pst_sources_path
                    ON pst_sources(path COLLATE NOCASE)
                    WHERE path <> '';

                CREATE TABLE IF NOT EXISTS folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
                    path TEXT NOT NULL DEFAULT '',
                    source_id INTEGER
                        REFERENCES pst_sources(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_folders_parent
                    ON folders(parent_id);

                CREATE TABLE IF NOT EXISTS emails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder_id INTEGER NOT NULL
                        REFERENCES folders(id) ON DELETE CASCADE,
                    message_id TEXT NOT NULL DEFAULT '',
                    sender_name TEXT NOT NULL DEFAULT '',
                    sender_email TEXT NOT NULL DEFAULT '',
                    recipients TEXT NOT NULL DEFAULT '',
                    subject TEXT NOT NULL DEFAULT '',
                    body_text TEXT NOT NULL DEFAULT '',
                    body_html TEXT NOT NULL DEFAULT '',
                    sent_at TEXT NOT NULL DEFAULT '',
                    attachment_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_emails_folder_date
                    ON emails(folder_id, sent_at DESC);

                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email_id INTEGER NOT NULL
                        REFERENCES emails(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL DEFAULT '',
                    mime_type TEXT NOT NULL DEFAULT '',
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    stored_path TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_attachments_email
                    ON attachments(email_id);

                CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
                    subject,
                    sender_name,
                    sender_email,
                    recipients,
                    body_text,
                    content='emails',
                    content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                );

                CREATE TRIGGER IF NOT EXISTS emails_fts_ai
                AFTER INSERT ON emails BEGIN
                    INSERT INTO emails_fts(
                        rowid, subject, sender_name, sender_email,
                        recipients, body_text
                    ) VALUES (
                        new.id, new.subject, new.sender_name, new.sender_email,
                        new.recipients, new.body_text
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS emails_fts_ad
                AFTER DELETE ON emails BEGIN
                    INSERT INTO emails_fts(
                        emails_fts, rowid, subject, sender_name, sender_email,
                        recipients, body_text
                    ) VALUES (
                        'delete', old.id, old.subject, old.sender_name,
                        old.sender_email, old.recipients, old.body_text
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS emails_fts_au
                AFTER UPDATE ON emails BEGIN
                    INSERT INTO emails_fts(
                        emails_fts, rowid, subject, sender_name, sender_email,
                        recipients, body_text
                    ) VALUES (
                        'delete', old.id, old.subject, old.sender_name,
                        old.sender_email, old.recipients, old.body_text
                    );
                    INSERT INTO emails_fts(
                        rowid, subject, sender_name, sender_email,
                        recipients, body_text
                    ) VALUES (
                        new.id, new.subject, new.sender_name, new.sender_email,
                        new.recipients, new.body_text
                    );
                END;
                """
            )
            self._migrar_multipst(conexion)
        except sqlite3.OperationalError as exc:
            raise RuntimeError(
                "No se pudo inicializar SQLite con soporte FTS5. "
                "Comprueba que tu instalación de Python incluya FTS5."
            ) from exc

    def _migrar_multipst(self, conexion: sqlite3.Connection) -> None:
        columnas = {
            str(fila[1])
            for fila in conexion.execute("PRAGMA table_info(folders)")
        }
        falta_columna = "source_id" not in columnas
        if falta_columna:
            self._respaldar_antes_migracion(conexion)

        with conexion:
            if falta_columna:
                conexion.execute(
                    "ALTER TABLE folders ADD COLUMN source_id INTEGER"
                )
            conexion.execute(
                "CREATE INDEX IF NOT EXISTS idx_folders_source "
                "ON folders(source_id)"
            )
            self._asignar_fuente_legacy(conexion)

    def _respaldar_antes_migracion(
        self, conexion: sqlite3.Connection
    ) -> None:
        destino = self.db_path.with_name(
            f"{self.db_path.name}.pre-multipst.bak"
        )
        if destino.exists():
            return
        temporal = destino.with_suffix(f"{destino.suffix}.tmp")
        respaldo = None
        try:
            respaldo = sqlite3.connect(str(temporal))
            conexion.backup(respaldo)
            respaldo.close()
            respaldo = None
            temporal.replace(destino)
            logger.info("Respaldo de la base creado en %s", destino)
        except Exception:
            logger.warning(
                "No se pudo crear el respaldo previo a la migración",
                exc_info=True,
            )
        finally:
            if respaldo is not None:
                respaldo.close()
            if temporal.exists():
                temporal.unlink(missing_ok=True)

    @staticmethod
    def _asignar_fuente_legacy(conexion: sqlite3.Connection) -> None:
        pendientes = conexion.execute(
            "SELECT COUNT(*) FROM folders WHERE source_id IS NULL"
        ).fetchone()
        if not pendientes or int(pendientes[0]) == 0:
            return

        existente = conexion.execute(
            "SELECT id FROM pst_sources ORDER BY id LIMIT 1"
        ).fetchone()
        if existente is not None:
            source_id = int(existente[0])
        else:
            raiz = conexion.execute(
                """
                SELECT name FROM folders
                WHERE source_id IS NULL AND parent_id IS NULL
                ORDER BY id
                LIMIT 1
                """
            ).fetchone()
            nombre = (
                _texto(raiz[0]).strip() if raiz is not None else ""
            ) or "PST importado"
            cursor = conexion.execute(
                """
                INSERT INTO pst_sources(name, path, imported_at)
                VALUES (?, '', ?)
                """,
                (
                    nombre,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )
            source_id = int(cursor.lastrowid)

        conexion.execute(
            "UPDATE folders SET source_id = ? WHERE source_id IS NULL",
            (source_id,),
        )

    def reset(self) -> None:
        """Vacía el contenido importado de todos los PST."""
        conexion = self._conexion()
        with conexion:
            emails = conexion.execute("SELECT id FROM emails").fetchall()
            conexion.execute("DELETE FROM attachments")
            conexion.execute("DELETE FROM emails")
            conexion.execute("DELETE FROM folders")
            conexion.execute("DELETE FROM pst_sources")
            conexion.execute(
                "DELETE FROM sqlite_sequence "
                "WHERE name IN ('pst_sources', 'folders', 'emails', 'attachments')"
            )
            conexion.execute("INSERT INTO emails_fts(emails_fts) VALUES('rebuild')")
        for fila in emails:
            self._eliminar_directorio_adjuntos(int(fila[0]))

    def contar_fuentes(self) -> int:
        conexion = self._conexion()
        fila = conexion.execute("SELECT COUNT(*) FROM pst_sources").fetchone()
        return int(fila[0]) if fila else 0

    def listar_fuentes(self) -> list[dict[str, Any]]:
        conexion = self._conexion()
        filas = conexion.execute(
            """
            SELECT s.id, s.name, s.path, s.imported_at,
                   COUNT(DISTINCT f.id) AS folder_count,
                   COUNT(DISTINCT e.id) AS email_count
            FROM pst_sources s
            LEFT JOIN folders f ON f.source_id = s.id
            LEFT JOIN emails e ON e.folder_id = f.id
            GROUP BY s.id, s.name, s.path, s.imported_at
            ORDER BY s.id
            """
        ).fetchall()
        return [dict(fila) for fila in filas]

    def fuente_por_ruta(self, ruta: str | Path) -> dict[str, Any] | None:
        conexion = self._conexion()
        fila = conexion.execute(
            """
            SELECT id, name, path, imported_at
            FROM pst_sources
            WHERE path = ? COLLATE NOCASE
            """,
            (_ruta_normalizada(ruta),),
        ).fetchone()
        return dict(fila) if fila else None

    def crear_fuente(
        self, ruta: str | Path, nombre: str | None = None
    ) -> int:
        conexion = self._conexion()
        base = _texto(nombre or Path(ruta).stem or "PST").strip() or "PST"
        candidato = base
        contador = 2
        with conexion:
            total = conexion.execute(
                "SELECT COUNT(*) FROM pst_sources"
            ).fetchone()
            if total is not None and int(total[0]) >= MAX_PST_SOURCES:
                raise RuntimeError(
                    f"Ya hay {MAX_PST_SOURCES} PST importados."
                )
            while conexion.execute(
                "SELECT 1 FROM pst_sources WHERE name = ? COLLATE NOCASE",
                (candidato,),
            ).fetchone():
                candidato = f"{base} ({contador})"
                contador += 1
            cursor = conexion.execute(
                """
                INSERT INTO pst_sources(name, path, imported_at)
                VALUES (?, ?, ?)
                """,
                (
                    candidato,
                    _ruta_normalizada(ruta),
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )
        return int(cursor.lastrowid)

    def eliminar_fuente(
        self,
        source_id: int,
        attachments_dir: str | Path | None = None,
    ) -> int:
        conexion = self._conexion()
        with conexion:
            emails = conexion.execute(
                """
                SELECT e.id
                FROM emails e
                JOIN folders f ON f.id = e.folder_id
                WHERE f.source_id = ?
                """,
                (source_id,),
            ).fetchall()
            conexion.execute(
                "DELETE FROM folders WHERE source_id = ?", (source_id,)
            )
            cursor = conexion.execute(
                "DELETE FROM pst_sources WHERE id = ?", (source_id,)
            )
            eliminada = cursor.rowcount
        for fila in emails:
            self._eliminar_directorio_adjuntos(
                int(fila[0]), attachments_dir
            )
        return len(emails) if eliminada else 0

    def _eliminar_directorio_adjuntos(
        self,
        email_id: int,
        attachments_dir: str | Path | None = None,
    ) -> None:
        base = (
            Path(attachments_dir) if attachments_dir else ATTACHMENTS_DIR
        )
        directorio = base / str(email_id)
        try:
            if directorio.is_dir():
                shutil.rmtree(directorio)
        except OSError:
            logger.warning(
                "No se pudieron eliminar los adjuntos de %s",
                directorio,
                exc_info=True,
            )

    def insertar_folder(
        self,
        name: str,
        parent_id: int | None,
        path: str,
        source_id: int | None = None,
    ) -> int:
        conexion = self._conexion()
        with conexion:
            cursor = conexion.execute(
                """
                INSERT INTO folders(name, parent_id, path, source_id)
                VALUES (?, ?, ?, ?)
                """,
                (_texto(name), parent_id, _texto(path), source_id),
            )
        return int(cursor.lastrowid)

    def insertar_email(
        self,
        folder_id: int,
        *,
        message_id: str = "",
        sender_name: str = "",
        sender_email: str = "",
        recipients: str = "",
        subject: str = "",
        body_text: str = "",
        body_html: str = "",
        sent_at: str = "",
        attachment_count: int = 0,
    ) -> int:
        conexion = self._conexion()
        with conexion:
            cursor = conexion.execute(
                """
                INSERT INTO emails(
                    folder_id, message_id, sender_name, sender_email,
                    recipients, subject, body_text, body_html, sent_at,
                    attachment_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    folder_id,
                    _texto(message_id),
                    _texto(sender_name),
                    _texto(sender_email),
                    _texto(recipients),
                    _texto(subject),
                    _texto(body_text),
                    _texto(body_html),
                    _texto(sent_at),
                    max(0, int(attachment_count)),
                ),
            )
        return int(cursor.lastrowid)

    def insertar_attachment(
        self,
        email_id: int,
        filename: str,
        mime_type: str = "",
        size_bytes: int = 0,
        stored_path: str = "",
    ) -> int:
        conexion = self._conexion()
        with conexion:
            cursor = conexion.execute(
                """
                INSERT INTO attachments(
                    email_id, filename, mime_type, size_bytes, stored_path
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    email_id,
                    _texto(filename),
                    _texto(mime_type),
                    max(0, int(size_bytes)),
                    _texto(stored_path),
                ),
            )
        return int(cursor.lastrowid)

    def listar_carpetas(self) -> list[dict[str, Any]]:
        conexion = self._conexion()
        filas = conexion.execute(
            """
            SELECT f.id, f.name, f.parent_id, f.path, f.source_id,
                   s.name AS source_name, COUNT(e.id) AS email_count
            FROM folders f
            JOIN pst_sources s ON s.id = f.source_id
            LEFT JOIN emails e ON e.folder_id = f.id
            GROUP BY f.id, f.name, f.parent_id, f.path, f.source_id,
                     s.name
            ORDER BY s.id, f.path COLLATE NOCASE, f.id
            """
        ).fetchall()
        return [dict(fila) for fila in filas]

    def _filas_a_correos(self, filas: list[sqlite3.Row]) -> list[dict[str, Any]]:
        return [dict(fila) for fila in filas]

    @staticmethod
    def _filtro_ubicacion(
        folder_id: int | None, source_id: int | None
    ) -> tuple[str, list[Any]]:
        if folder_id:
            return "WHERE e.folder_id = ?", [folder_id]
        if source_id:
            return "WHERE f.source_id = ?", [source_id]
        return "", []

    def listar_correos(
        self,
        folder_id: int | None = None,
        source_id: int | None = None,
    ) -> list[dict[str, Any]]:
        conexion = self._conexion()
        filtro, parametros = self._filtro_ubicacion(folder_id, source_id)
        filas = conexion.execute(
            f"""
            SELECT e.id, e.folder_id, e.sender_name, e.sender_email,
                   e.recipients, e.subject, e.sent_at, e.attachment_count,
                   f.name AS folder_name, f.path AS folder_path,
                   f.source_id, s.name AS source_name
            FROM emails e
            JOIN folders f ON f.id = e.folder_id
            JOIN pst_sources s ON s.id = f.source_id
            {filtro}
            ORDER BY e.sent_at DESC, e.id DESC
            """,
            parametros,
        ).fetchall()
        return self._filas_a_correos(filas)

    @staticmethod
    def _consulta_fts(texto: str) -> str | None:
        tokens = re.findall(r"\w+", texto, flags=re.UNICODE)
        if not tokens:
            return None
        return " AND ".join(f'"{token}"*' for token in tokens)

    def buscar_correos(
        self,
        texto: str,
        folder_id: int | None = None,
        source_id: int | None = None,
    ) -> list[dict[str, Any]]:
        texto = (texto or "").strip()
        if not texto:
            return self.listar_correos(folder_id, source_id)

        consulta_fts = self._consulta_fts(texto)
        if consulta_fts is None:
            return []

        conexion = self._conexion()
        parametros: list[Any] = [consulta_fts]
        if folder_id:
            filtro = "AND e.folder_id = ?"
            parametros.append(folder_id)
        elif source_id:
            filtro = "AND f.source_id = ?"
            parametros.append(source_id)
        else:
            filtro = ""

        filas = conexion.execute(
            f"""
            SELECT e.id, e.folder_id, e.sender_name, e.sender_email,
                   e.recipients, e.subject, e.sent_at, e.attachment_count,
                   f.name AS folder_name, f.path AS folder_path,
                   f.source_id, s.name AS source_name
            FROM emails_fts
            JOIN emails e ON e.id = emails_fts.rowid
            JOIN folders f ON f.id = e.folder_id
            JOIN pst_sources s ON s.id = f.source_id
            WHERE emails_fts MATCH ?
            {filtro}
            ORDER BY e.sent_at DESC, e.id DESC
            """,
            parametros,
        ).fetchall()
        return self._filas_a_correos(filas)

    def obtener_correo(self, email_id: int) -> dict[str, Any] | None:
        conexion = self._conexion()
        fila = conexion.execute(
            """
            SELECT e.*, f.name AS folder_name, f.path AS folder_path,
                   f.source_id, s.name AS source_name
            FROM emails e
            JOIN folders f ON f.id = e.folder_id
            JOIN pst_sources s ON s.id = f.source_id
            WHERE e.id = ?
            """,
            (email_id,),
        ).fetchone()
        return dict(fila) if fila else None

    def obtener_adjuntos(self, email_id: int) -> list[dict[str, Any]]:
        conexion = self._conexion()
        filas = conexion.execute(
            """
            SELECT id, email_id, filename, mime_type, size_bytes, stored_path
            FROM attachments
            WHERE email_id = ?
            ORDER BY id
            """,
            (email_id,),
        ).fetchall()
        return [dict(fila) for fila in filas]

    def contar_correos(self, source_id: int | None = None) -> int:
        conexion = self._conexion()
        if source_id:
            fila = conexion.execute(
                """
                SELECT COUNT(*)
                FROM emails e
                JOIN folders f ON f.id = e.folder_id
                WHERE f.source_id = ?
                """,
                (source_id,),
            ).fetchone()
        else:
            fila = conexion.execute("SELECT COUNT(*) FROM emails").fetchone()
        return int(fila[0]) if fila else 0

    def cerrar(self) -> None:
        conexion = getattr(self._local, "conexion", None)
        if conexion is not None:
            conexion.close()
            self._local.conexion = None
