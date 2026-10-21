from __future__ import annotations

import logging
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser, Parser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from .database import ATTACHMENTS_DIR, MAX_PST_SOURCES, Database


logger = logging.getLogger(__name__)

try:
    import pypff
except ImportError:
    pypff = None
else:
    if not hasattr(pypff, "file"):
        logger.warning(
            "El módulo 'pypff' instalado no corresponde a los bindings de "
            "libpff; instala 'libpff-python'."
        )
        pypff = None

ProgressCallback = Callable[[int, int, str], None]
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


class ExtractionError(RuntimeError):
    """Error controlado durante la importación de un PST."""


class _EstadoImportacion:
    def __init__(self, total: int, callback: ProgressCallback | None) -> None:
        self.total = total
        self.callback = callback
        self.procesados = 0
        self.importados = 0
        self.errores = 0

    def progreso(self, mensaje: str) -> None:
        if self.callback:
            self.callback(self.procesados, self.total, mensaje)


class _HTMLATexto(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.partes: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4"}:
            self.partes.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "div", "tr", "li", "h1", "h2", "h3", "h4"}:
            self.partes.append("\n")

    def handle_data(self, data: str) -> None:
        self.partes.append(data)

    def texto(self) -> str:
        lineas = [" ".join(linea.split()) for linea in "".join(self.partes).splitlines()]
        return "\n".join(linea for linea in lineas if linea).strip()


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, bytes):
        return valor.decode("utf-8", errors="replace").replace("\x00", "")
    return str(valor).replace("\x00", "")


def _direccion(nombre: str, correo: str) -> str:
    if nombre and correo:
        return f"{nombre} <{correo}>"
    return correo or nombre


def _llamar(obj: Any, metodo: str, *args: Any, default: Any = None) -> Any:
    funcion = getattr(obj, metodo, None)
    if not callable(funcion):
        return default
    try:
        return funcion(*args)
    except Exception:
        return default


def _fecha_iso(valor: datetime | None) -> str:
    if not isinstance(valor, datetime):
        return ""
    if valor.tzinfo is not None:
        valor = valor.astimezone(timezone.utc).replace(tzinfo=None)
    return valor.isoformat(timespec="seconds")


def _fecha_de_cabecera(valor: Any) -> str:
    texto = _texto(valor).strip()
    if not texto:
        return ""
    try:
        return _fecha_iso(parsedate_to_datetime(texto))
    except (TypeError, ValueError, OverflowError):
        return ""


def _html_a_texto(html: str) -> str:
    parser = _HTMLATexto()
    try:
        parser.feed(html)
        return parser.texto()
    except Exception:
        return html


def _nombre_seguro(nombre: str, respaldo: str) -> str:
    nombre = re.split(r"[\\/]", _texto(nombre))[-1]
    nombre = _INVALID_FILENAME.sub("_", nombre).strip().rstrip(". ")
    if not nombre:
        nombre = respaldo
    if nombre.split(".")[0].upper() in _WINDOWS_RESERVED:
        nombre = "_" + nombre
    return nombre[:180]


def _ruta_adjunto_unica(directorio: Path, nombre: str) -> Path:
    destino = directorio / nombre
    if not destino.exists():
        return destino
    base = destino.stem
    sufijo = destino.suffix
    contador = 2
    while True:
        candidato = directorio / f"{base} ({contador}){sufijo}"
        if not candidato.exists():
            return candidato
        contador += 1


def _guardar_adjunto(
    db: Database,
    email_id: int,
    nombre: str,
    mime_type: str,
    datos: bytes,
    attachments_dir: Path,
) -> None:
    nombre_seguro = _nombre_seguro(nombre, f"adjunto_{email_id}")
    directorio = attachments_dir / str(email_id)
    directorio.mkdir(parents=True, exist_ok=True)
    destino = _ruta_adjunto_unica(directorio, nombre_seguro)
    destino.write_bytes(datos)
    db.insertar_attachment(
        email_id=email_id,
        filename=nombre or nombre_seguro,
        mime_type=mime_type or mimetypes.guess_type(nombre_seguro)[0] or "application/octet-stream",
        size_bytes=len(datos),
        stored_path=str(destino),
    )


def _mensaje_a_texto(obj: Any) -> str:
    return _texto(_llamar(obj, "get_name", default=""))


def _pypff_es_mensaje(elemento: Any) -> bool:
    return pypff is not None and isinstance(elemento, pypff.message)


def _pypff_clase_mensaje(message: Any) -> str:
    for indice in range(
        int(_llamar(message, "get_number_of_record_sets", default=0) or 0)
    ):
        record_set = _llamar(message, "get_record_set", indice)
        if record_set is None:
            continue
        try:
            entrada = record_set.get_entry_by_type(26)
            if entrada is not None:
                return _texto(entrada.get_data_as_string()).strip()
        except Exception:
            continue
    return ""


def _pypff_es_correo(elemento: Any) -> bool:
    if not _pypff_es_mensaje(elemento):
        return False
    clase = _pypff_clase_mensaje(elemento).upper()
    return not clase or clase.startswith("IPM.NOTE")


def _pypff_contar_mensajes(folder: Any) -> int:
    total = 0
    numero_mensajes = int(
        _llamar(folder, "get_number_of_sub_messages", default=0) or 0
    )
    for indice in range(numero_mensajes):
        mensaje = _llamar(folder, "get_sub_message", indice)
        if _pypff_es_correo(mensaje):
            total += 1

    numero_subcarpetas = int(
        _llamar(folder, "get_number_of_sub_folders", default=0) or 0
    )
    for indice in range(numero_subcarpetas):
        subcarpeta = _llamar(folder, "get_sub_folder", indice)
        if subcarpeta is not None:
            total += _pypff_contar_mensajes(subcarpeta)
    return total


def _pypff_cabeceras(message: Any) -> Any:
    crudo = _texto(_llamar(message, "get_transport_headers", default="")).strip()
    if not crudo:
        return None
    try:
        return Parser(policy=policy.default).parsestr(crudo)
    except Exception:
        logger.exception("No se pudieron interpretar las cabeceras del mensaje")
        return None


def _pypff_remitente(
    message: Any, cabeceras: Any
) -> tuple[str, str]:
    nombre = _texto(_llamar(message, "get_sender_name", default="")).strip()
    correo = ""
    if cabeceras is not None:
        pares = getaddresses([_texto(cabeceras.get("From", ""))])
        if pares:
            nombre_cabecera, correo_cabecera = pares[0]
            nombre = nombre_cabecera or nombre
            correo = correo_cabecera
    return nombre, correo


def _pypff_destinatarios(cabeceras: Any) -> str:
    if cabeceras is None:
        return ""
    pares = getaddresses(
        [
            _texto(cabeceras.get("To", "")),
            _texto(cabeceras.get("Cc", "")),
        ]
    )
    return ", ".join(
        _direccion(nombre, correo)
        for nombre, correo in pares
        if nombre or correo
    )


def _pypff_fecha(message: Any, cabeceras: Any) -> str:
    for metodo in (
        "get_delivery_time",
        "get_client_submit_time",
        "get_creation_time",
    ):
        fecha = _llamar(message, metodo)
        if isinstance(fecha, datetime):
            return _fecha_iso(fecha)
    if cabeceras is not None:
        return _fecha_de_cabecera(cabeceras.get("Date", ""))
    return ""


def _pypff_message_id(cabeceras: Any) -> str:
    if cabeceras is None:
        return ""
    return _texto(cabeceras.get("Message-ID", "")).strip().strip("<>")


def _pypff_leer_datos_adjunto(attachment: Any) -> bytes | None:
    datos = _llamar(attachment, "get_data")
    if datos is not None:
        if isinstance(datos, str):
            return datos.encode("utf-8", errors="replace")
        if isinstance(datos, bytes):
            return datos
        try:
            return bytes(datos)
        except TypeError:
            return None

    tamano = int(_llamar(attachment, "get_size", default=0) or 0)
    if tamano <= 0:
        return b""
    partes: list[bytes] = []
    restante = tamano
    while restante > 0:
        bloque = min(restante, 8 * 1024 * 1024)
        trozo = _llamar(attachment, "read_buffer", bloque)
        if not trozo:
            break
        if isinstance(trozo, str):
            trozo = trozo.encode("latin-1", errors="replace")
        partes.append(bytes(trozo))
        restante -= len(trozo)
        if len(trozo) < bloque:
            break
    if not partes:
        return None
    return b"".join(partes)


def _pypff_adjuntos(message: Any) -> list[dict[str, Any]]:
    adjuntos: list[dict[str, Any]] = []
    for indice in range(
        int(_llamar(message, "get_number_of_attachments", default=0) or 0)
    ):
        attachment = _llamar(message, "get_attachment", indice)
        if attachment is None:
            continue
        try:
            datos = _pypff_leer_datos_adjunto(attachment)
            if datos is None:
                continue

            nombre = (
                _texto(_llamar(attachment, "get_long_filename", default=""))
                or _texto(_llamar(attachment, "get_name", default=""))
                or _texto(_llamar(attachment, "get_filename", default=""))
                or f"adjunto_{indice + 1}"
            )
            mime_type = _texto(
                _llamar(attachment, "get_mime_type", default="")
            ) or (mimetypes.guess_type(nombre)[0] or "application/octet-stream")
            adjuntos.append(
                {
                    "filename": nombre,
                    "mime_type": mime_type,
                    "data": datos,
                }
            )
        except Exception:
            logger.exception("No se pudo leer un adjunto con pypff")
    return adjuntos


def _importar_mensaje_pypff(
    message: Any,
    folder_id: int,
    db: Database,
    attachments_dir: Path,
) -> None:
    cabeceras = _pypff_cabeceras(message)
    sender_name, sender_email = _pypff_remitente(message, cabeceras)
    subject = _texto(_llamar(message, "get_subject", default="")).strip()
    if not subject and cabeceras is not None:
        subject = _texto(cabeceras.get("Subject", "")).strip()
    body_text = _texto(_llamar(message, "get_plain_text_body", default=""))
    body_html = _texto(_llamar(message, "get_html_body", default=""))
    if not body_text.strip() and body_html.strip():
        body_text = _html_a_texto(body_html)

    adjuntos = _pypff_adjuntos(message)
    email_id = db.insertar_email(
        folder_id,
        message_id=_pypff_message_id(cabeceras),
        sender_name=sender_name,
        sender_email=sender_email,
        recipients=_pypff_destinatarios(cabeceras),
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        sent_at=_pypff_fecha(message, cabeceras),
        attachment_count=len(adjuntos),
    )

    for adjunto in adjuntos:
        try:
            _guardar_adjunto(
                db,
                email_id,
                adjunto["filename"],
                adjunto["mime_type"],
                adjunto["data"],
                attachments_dir,
            )
        except Exception:
            logger.exception("No se pudo guardar el adjunto %s", adjunto["filename"])


def _procesar_carpeta_pypff(
    folder: Any,
    folder_id: int,
    ruta: str,
    source_id: int,
    db: Database,
    attachments_dir: Path,
    estado: _EstadoImportacion,
) -> None:
    numero_mensajes = int(
        _llamar(folder, "get_number_of_sub_messages", default=0) or 0
    )
    for indice in range(numero_mensajes):
        message = _llamar(folder, "get_sub_message", indice)
        if not _pypff_es_correo(message):
            logger.debug("Se omite un elemento que no es un correo en %s", ruta)
            continue
        asunto = _texto(_llamar(message, "get_subject", default="")) or "correo"
        try:
            _importar_mensaje_pypff(message, folder_id, db, attachments_dir)
            estado.importados += 1
        except Exception:
            estado.errores += 1
            logger.exception("No se pudo importar un correo de %s", ruta)
        finally:
            estado.procesados += 1
            estado.progreso(asunto)

    numero_subcarpetas = int(
        _llamar(folder, "get_number_of_sub_folders", default=0) or 0
    )
    for indice in range(numero_subcarpetas):
        subcarpeta = _llamar(folder, "get_sub_folder", indice)
        if subcarpeta is None:
            continue
        nombre = _mensaje_a_texto(subcarpeta) or f"Carpeta {indice + 1}"
        ruta_hija = f"{ruta}/{nombre}" if ruta else nombre
        try:
            subfolder_id = db.insertar_folder(
                nombre, folder_id, ruta_hija, source_id
            )
            _procesar_carpeta_pypff(
                subcarpeta,
                subfolder_id,
                ruta_hija,
                source_id,
                db,
                attachments_dir,
                estado,
            )
        except Exception:
            estado.errores += 1
            logger.exception("No se pudo procesar la carpeta %s", ruta_hija)


def _extraer_con_pypff(
    pst: Any,
    pst_path: Path,
    source_id: int,
    db: Database,
    attachments_dir: Path,
    callback: ProgressCallback | None,
) -> int:
    if callback:
        callback(0, 0, "Analizando carpetas del PST...")

    root_folder = pst.get_root_folder()
    root_name = _mensaje_a_texto(root_folder) or pst_path.stem or "PST"
    total = _pypff_contar_mensajes(root_folder)
    root_id = db.insertar_folder(root_name, None, root_name, source_id)
    estado = _EstadoImportacion(total, callback)
    if callback:
        callback(0, total, f"{total} correos encontrados")

    _procesar_carpeta_pypff(
        root_folder,
        root_id,
        root_name,
        source_id,
        db,
        attachments_dir,
        estado,
    )
    if callback:
        callback(total, total, "Importación completada")
    logger.info(
        "PST importado con pypff: %s correos, %s errores",
        estado.importados,
        estado.errores,
    )
    return estado.importados


def _localizar_readpst() -> str | None:
    ruta_configurada = os.environ.get("READPST_PATH", "").strip()
    if ruta_configurada and Path(ruta_configurada).is_file():
        return ruta_configurada
    encontrado = shutil.which("readpst")
    if encontrado:
        return encontrado

    candidatos_empaquetado = [
        Path(sys.executable).resolve().parent / "readpst.exe",
        Path(sys.executable).resolve().parent / "readpst",
    ]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidatos_empaquetado.extend(
            [Path(meipass) / "readpst.exe", Path(meipass) / "readpst"]
        )
    for candidato in candidatos_empaquetado:
        if candidato.is_file():
            return str(candidato)

    if os.name == "nt":
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(variable)
            if not base:
                continue
            for candidato in (
                Path(base) / "libpst" / "readpst.exe",
                Path(base) / "libpst" / "bin" / "readpst.exe",
            ):
                if candidato.is_file():
                    return str(candidato)
    return None


def _datos_parte(part: Any) -> bytes | None:
    try:
        datos = part.get_payload(decode=True)
        if datos is not None:
            return datos
        if part.get_content_type() == "message/rfc822":
            payload = part.get_payload()
            if isinstance(payload, list) and payload:
                return payload[0].as_bytes(policy=policy.default)
    except Exception:
        logger.exception("No se pudo decodificar una parte MIME")
    return None


def _contenido_texto_parte(part: Any) -> str:
    try:
        contenido = part.get_content()
        if isinstance(contenido, bytes):
            charset = part.get_content_charset() or "utf-8"
            return contenido.decode(charset, errors="replace")
        return _texto(contenido)
    except Exception:
        datos = part.get_payload(decode=True)
        if datos is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        try:
            return datos.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            return datos.decode("utf-8", errors="replace")


def _partes_eml(message: Any) -> tuple[str, str, list[dict[str, Any]]]:
    textos: list[str] = []
    htmls: list[str] = []
    adjuntos: list[dict[str, Any]] = []

    for indice, part in enumerate(message.walk()):
        if part.is_multipart():
            continue

        content_type = part.get_content_type()
        disposicion = (part.get_content_disposition() or "").lower()
        nombre = part.get_filename()

        if nombre or disposicion == "attachment":
            datos = _datos_parte(part)
            if datos is not None:
                adjuntos.append(
                    {
                        "filename": _texto(nombre) or f"adjunto_{indice + 1}",
                        "mime_type": content_type or "application/octet-stream",
                        "data": datos,
                    }
                )
            continue

        if content_type == "text/plain":
            texto = _contenido_texto_parte(part)
            if texto.strip():
                textos.append(texto)
        elif content_type == "text/html":
            html = _contenido_texto_parte(part)
            if html.strip():
                htmls.append(html)

    body_text = "\n\n".join(textos).strip()
    body_html = "\n\n".join(htmls).strip()
    if not body_text and body_html:
        body_text = _html_a_texto(body_html)
    return body_text, body_html, adjuntos


def _importar_eml(
    ruta_eml: Path,
    folder_id: int,
    db: Database,
    attachments_dir: Path,
) -> str:
    with ruta_eml.open("rb") as archivo:
        message = BytesParser(policy=policy.default).parse(archivo)

    remitente = _texto(message.get("From", ""))
    pares_remitente = getaddresses([remitente]) if remitente else []
    sender_name, sender_email = (
        pares_remitente[0] if pares_remitente else ("", "")
    )
    if not sender_name and not sender_email and remitente:
        sender_name = remitente

    pares = getaddresses(
        [
            _texto(message.get("To", "")),
            _texto(message.get("Cc", "")),
        ]
    )
    destinatarios = [
        _direccion(nombre, correo)
        for nombre, correo in pares
        if nombre or correo
    ]

    sent_at = ""
    fecha_cabecera = _texto(message.get("Date", "")).strip()
    if fecha_cabecera:
        try:
            sent_at = _fecha_iso(parsedate_to_datetime(fecha_cabecera))
        except (TypeError, ValueError, OverflowError):
            sent_at = ""
    if not sent_at:
        sent_at = _fecha_iso(
            datetime.fromtimestamp(ruta_eml.stat().st_mtime, tz=timezone.utc)
        )

    subject = _texto(message.get("Subject", "")).strip()
    body_text, body_html, adjuntos = _partes_eml(message)
    email_id = db.insertar_email(
        folder_id,
        message_id=_texto(message.get("Message-ID", "")).strip().strip("<>"),
        sender_name=_texto(sender_name),
        sender_email=_texto(sender_email),
        recipients=", ".join(destinatarios),
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        sent_at=sent_at,
        attachment_count=len(adjuntos),
    )

    for adjunto in adjuntos:
        try:
            _guardar_adjunto(
                db,
                email_id,
                adjunto["filename"],
                adjunto["mime_type"],
                adjunto["data"],
                attachments_dir,
            )
        except Exception:
            logger.exception("No se pudo guardar el adjunto %s", adjunto["filename"])
    return subject


def _extraer_con_readpst(
    pst_path: Path,
    source_id: int,
    db: Database,
    attachments_dir: Path,
    callback: ProgressCallback | None,
) -> int:
    readpst = _localizar_readpst()
    if not readpst:
        raise ExtractionError(
            "pypff no está disponible y no se encontró el ejecutable readpst. "
            "Instala los bindings con 'pip install libpff-python' o agrega "
            "readpst al PATH (también puedes definir READPST_PATH)."
        )

    if callback:
        callback(0, 0, "Convirtiendo el PST a archivos EML con readpst...")

    with tempfile.TemporaryDirectory(prefix="pst_reader_") as temporal:
        salida = Path(temporal)
        comando = [readpst, "-e", "-o", str(salida), str(pst_path)]
        opciones: dict[str, Any] = {}
        if os.name == "nt":
            opciones["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            resultado = subprocess.run(
                comando,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                **opciones,
            )
        except OSError as exc:
            raise ExtractionError(f"No se pudo ejecutar readpst: {exc}") from exc

        archivos_eml = sorted(salida.rglob("*.eml"))
        if resultado.returncode != 0 and not archivos_eml:
            detalle = (resultado.stderr or resultado.stdout or "").strip()
            raise ExtractionError(
                "readpst falló al convertir el PST"
                + (f":\n{detalle[-2000:]}" if detalle else ".")
            )

        total = len(archivos_eml)
        root_name = pst_path.stem or "PST"
        root_id = db.insertar_folder(
            root_name, None, root_name, source_id
        )
        estado = _EstadoImportacion(total, callback)
        if callback:
            callback(0, total, f"Procesando {total} archivos EML...")

        ids_carpetas: dict[Path, int] = {salida: root_id}

        for dirpath, dirnames, filenames in os.walk(salida):
            dirnames.sort(key=str.lower)
            directorio = Path(dirpath)
            if directorio == salida:
                folder_id = root_id
            else:
                parent_id = ids_carpetas.get(directorio.parent, root_id)
                ruta_relativa = directorio.relative_to(salida).as_posix()
                folder_id = db.insertar_folder(
                    directorio.name,
                    parent_id,
                    ruta_relativa,
                    source_id,
                )
                ids_carpetas[directorio] = folder_id

            for filename in sorted(filenames, key=str.lower):
                if Path(filename).suffix.lower() != ".eml":
                    continue
                ruta_eml = directorio / filename
                asunto = filename
                try:
                    asunto = _importar_eml(
                        ruta_eml, folder_id, db, attachments_dir
                    ) or filename
                    estado.importados += 1
                except Exception:
                    estado.errores += 1
                    logger.exception("No se pudo importar el EML %s", ruta_eml)
                finally:
                    estado.procesados += 1
                    estado.progreso(asunto)

        if callback:
            callback(total, total, "Importación completada")
        logger.info(
            "PST importado con readpst: %s correos, %s errores",
            estado.importados,
            estado.errores,
        )
        return estado.importados


def extraer_pst(
    ruta_pst: str | Path,
    db: Database,
    attachments_dir: str | Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> int:
    """Agrega un PST a SQLite y devuelve la cantidad de correos importados.

    Usa pypff cuando está disponible. Si pypff no puede abrir el archivo o no
    está instalado, intenta la conversión a EML con readpst.
    """
    pst_path = Path(ruta_pst)
    if not pst_path.is_file():
        raise ExtractionError(f"No existe el archivo PST: {pst_path}")

    if db.contar_fuentes() >= MAX_PST_SOURCES:
        raise ExtractionError(
            f"Ya hay {MAX_PST_SOURCES} PST importados. "
            "Quita uno antes de agregar otro."
        )

    existente = db.fuente_por_ruta(pst_path)
    if existente is not None:
        raise ExtractionError(
            "Este PST ya está importado como "
            f"«{existente.get('name', '')}»."
        )

    directorio_adjuntos = (
        Path(attachments_dir) if attachments_dir else ATTACHMENTS_DIR
    )
    directorio_adjuntos.mkdir(parents=True, exist_ok=True)
    source_id = db.crear_fuente(pst_path)

    try:
        if pypff is not None:
            pst = None
            try:
                pst = pypff.file()
                pst.open(str(pst_path))
            except Exception as exc:
                logger.warning("pypff no pudo abrir el PST: %s", exc)
                if pst is not None:
                    try:
                        pst.close()
                    except Exception:
                        pass
                if not _localizar_readpst():
                    raise ExtractionError(
                        "pypff no pudo abrir el PST y readpst no está "
                        f"disponible. Detalle: {exc}"
                    ) from exc
                return _extraer_con_readpst(
                    pst_path,
                    source_id,
                    db,
                    directorio_adjuntos,
                    progress_callback,
                )
            try:
                return _extraer_con_pypff(
                    pst,
                    pst_path,
                    source_id,
                    db,
                    directorio_adjuntos,
                    progress_callback,
                )
            finally:
                try:
                    pst.close()
                except Exception:
                    logger.exception("No se pudo cerrar el archivo PST")

        logger.info("pypff no está instalado; se usará readpst")
        return _extraer_con_readpst(
            pst_path,
            source_id,
            db,
            directorio_adjuntos,
            progress_callback,
        )
    except Exception:
        try:
            db.eliminar_fuente(source_id, directorio_adjuntos)
        except Exception:
            logger.exception("No se pudo limpiar la importación fallida")
        raise
