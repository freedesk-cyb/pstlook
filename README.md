# PST Reader

Aplicación de escritorio local para abrir hasta cinco archivos PST de Outlook,
explorar sus carpetas y correos, buscar con SQLite FTS5 y guardar adjuntos. Usa
PySide6 y QWebEngineView para mostrar el HTML de los mensajes.

No necesita servidor ni conexión a internet. El contenido HTML se renderiza con
JavaScript deshabilitado y con las peticiones de red bloqueadas.

## Requisitos

- Python 3.11 o superior
- Windows para el empaquetado inicial con PyInstaller
- SQLite con FTS5 (incluido en las distribuciones oficiales de Python)
- Backend de extracción:
  - `libpff-python` (recomendado), que se importa como `pypff`, o
  - `readpst` del proyecto libpst como alternativa
- Para desarrollo: `PySide6`, `libpff-python` (opcional) y `pyinstaller`
- Para generar el instalador: Inno Setup 6

Importante: el paquete de PyPI llamado `pypff` no son los bindings de libpff.
El paquete correcto es `libpff-python`; el módulo Python resultante sí se llama
`pypff`.

## Instalación en modo desarrollo

Desde la carpeta `pst_reader_app`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Si `libpff-python` no tiene una rueda compatible con tu versión de Python o
falla su instalación, la aplicación puede funcionar con `readpst`:

1. Instala una distribución de libpst que incluya `readpst.exe`.
2. Agrega la carpeta de `readpst.exe` al `PATH`, o define la variable de entorno
   `READPST_PATH` con la ruta completa al ejecutable.
3. Instala el resto de dependencias con `pip install PySide6`.
4. Ejecuta la aplicación; el fallback se activa automáticamente si `pypff` no
   está disponible o no puede abrir el archivo.

## Ejecutar

```powershell
python main.py
```

Al agregar un PST, la aplicación:

1. Lo procesa en un `QThread` para no bloquear la interfaz.
2. Extrae carpetas, correos, cuerpos de texto/HTML y adjuntos.
3. Guarda los metadatos y cuerpos en `data/pst_data.db`.
4. Guarda los adjuntos en `data/attachments/<id_correo>/`.

Se pueden importar hasta **5 PST** y consultarlos juntos. Cada archivo aparece
como un grupo independiente en el árbol, sin reemplazar los anteriores.

## Uso

- **Agregar PST**: botón superior o `Ctrl+O`. El límite es de 5 archivos.
- **Quitar PST**: clic derecho sobre un PST o una de sus carpetas y elige
  `Quitar PST`. Solo se borran los datos locales; el archivo `.pst` original no
  se modifica.
- **Carpetas**: panel izquierdo, agrupadas por PST. La entrada
  `Todos los correos` muestra los correos de todos los PST importados.
- **Lista**: panel central, ordenada por fecha descendente.
- **Detalle**: panel derecho, con cuerpo HTML/texto y adjuntos.
- **Descargar PDF**: guarda el correo actual en PDF con asunto, remitente,
  destinatarios, fecha, cuerpo y lista de adjuntos.
- **Abrir adjunto**: crea una copia temporal y la abre con la aplicación
  predeterminada de Windows (Excel, Word, Adobe Reader, etc.).
- **Guardar como**: guarda una copia permanente del adjunto donde elijas.
- **Buscar**: filtro FTS5 sobre asunto, remitente, destinatarios y cuerpo. Se
  aplica a la carpeta o PST seleccionado; usa `Todos los correos` para buscar en
  todos los archivos. `Ctrl+F` enfoca la búsqueda.
- **Tema**: selector en la barra superior con cinco paletas profesionales:
  Claro, Oscuro grafito, Azul corporativo, Verde ejecutivo y Vino ejecutivo.
  La elección se guarda y se aplica al volver a abrir la aplicación.

La búsqueda admite varias palabras y coincidencias por prefijo. Por ejemplo,
`factura enero` busca correos que contengan ambas palabras.

## Estructura

```text
pst_reader_app/
├── main.py
├── core/
│   ├── __init__.py
│   ├── database.py
│   ├── pst_extractor.py
│   └── worker_thread.py
├── ui/
│   ├── __init__.py
│   ├── main_window.py
│   ├── themes.py
│   ├── folder_tree_widget.py
│   ├── email_list_widget.py
│   └── email_detail_widget.py
├── data/
│   ├── attachments/
│   └── pst_data.db          # se crea al ejecutar
├── requirements.txt
└── README.md
```

`core/database.py` usa conexiones SQLite por hilo. La tabla `pst_sources`
registra los PST importados y agrupa sus carpetas. La tabla FTS5 `emails_fts`
indexa asunto, remitente, destinatarios y cuerpo, y se mantiene sincronizada con
triggers.

## Datos y privacidad

- Todo se procesa localmente.
- No se envía telemetría ni se contacta ningún servidor.
- Las imágenes, CSS y otros recursos remotos de los correos se bloquean.
- JavaScript está deshabilitado en el visor HTML.
- Al abrir un adjunto se usa una copia temporal en
  `%TEMP%\PSTReader\abiertos`, nunca el archivo almacenado en `data`.
- La copia se marca con `Zone.Identifier` para que Office/Adobe la traten como
  descargada de internet y la abran en Vista protegida cuando corresponda.
- Los archivos ejecutables o scripts peligrosos no se abren desde la aplicación.
  Los formatos con macros muestran una advertencia adicional.
- La exportación a PDF usa el mismo perfil sin JavaScript ni acceso a recursos
  remotos que el visor HTML.
- En desarrollo, los datos viven en `./data`.
- En una versión empaquetada con `sys.frozen`, los datos se guardan en
  `%LOCALAPPDATA%\PSTReader\data`, porque la carpeta temporal de `--onefile` no
  es un lugar persistente.
- Al actualizar desde la versión de un solo PST se crea automáticamente
  `data/pst_data.db.pre-multipst.bak` antes de migrar el esquema.
- Los archivos importados pueden contener información sensible: protege la
  carpeta `data` y los respaldos. El respaldo previo a la migración también
  contiene datos personales.

## Generar la aplicación de escritorio

Desde `pst_reader_app`, con el entorno virtual activo:

```powershell
.\build.ps1
```

El script usa `PSTReader.spec` y genera `dist\PSTReader.exe`. Es un ejecutable
autocontenido: incluye Python, Qt, Qt WebEngine y, si está instalado, el módulo
`pypff`. No necesita Python instalado en el equipo de destino.

El icono y los metadatos de versión están en `assets\pstlook.ico` y
`packaging\version_info.txt`.

La aplicación empaquetada guarda sus datos en
`%LOCALAPPDATA%\PSTReader\data`, no dentro de `dist`. Para distribuirla
manualmente, copia solo `PSTReader.exe`; no incluyas la carpeta `data` del
proyecto.

Si se desea usar el backend alternativo, copia `readpst.exe` junto a
`PSTReader.exe` o define `READPST_PATH`. `readpst` puede necesitar DLLs
adicionales de libpst.

Notas:

- El primer arranque de un ejecutable `--onefile` con Qt WebEngine puede tardar
  mientras Windows descomprime los archivos temporales.
- El ejecutable no está firmado digitalmente. Windows SmartScreen puede mostrar
  una advertencia; se puede omitir con "Más información" > "Ejecutar de todos
  modos".
- Para un arranque más rápido y menos falsos positivos de antivirus, se puede
  cambiar el empaquetado a `--onedir` en el archivo `.spec`.

### Instalador para Windows

El instalador requiere Inno Setup 6. Una vez instalado:

```powershell
.\build_installer.ps1
```

El resultado es `dist\PSTReader-1.0.0-Setup.exe`. El instalador:

- Se instala por usuario en `%LOCALAPPDATA%\Programs\PST Reader`, sin requerir
  permisos de administrador.
- Crea accesos directos en el menú Inicio y, opcionalmente, en el escritorio.
- Incluye un desinstalador.
- No incluye datos personales. Al desinstalar, conserva la base y los adjuntos
  en `%LOCALAPPDATA%\PSTReader\data`.

El script `installer.iss` contiene la configuración de Inno Setup y
`build_installer.ps1` localiza automáticamente el compilador.

## Limitaciones del MVP

- Máximo 5 PST importados a la vez.
- Sin exportación a formatos editables como MSG o EML.
- Búsqueda deliberadamente simple (sin operadores avanzados de Gmail).
- El HTML se muestra con recursos remotos bloqueados; algunas imágenes de
  correos no se verán.
- Se omiten los elementos que no son correos, como calendario, contactos y
  tareas.
- Abrir un adjunto requiere que Windows tenga una aplicación asociada a ese
  formato. Las copias temporales no se eliminan automáticamente.
- El PDF exportado incluye una lista de los adjuntos, pero no incrusta sus
  archivos. Los correos HTML muy complejos pueden perder parte del formato.
