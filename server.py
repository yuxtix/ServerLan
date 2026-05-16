# -*- coding: utf-8 -*-
import os
import socket
import urllib.parse
import urllib.request
import time
import shutil
import mimetypes
import json
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8000
ROOT_DIR = os.getcwd()

def get_dir_size(path):
    """Calcula el tamaño total de un directorio de forma recursiva."""
    total_size = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total_size += entry.stat().st_size
            elif entry.is_dir(follow_symlinks=False):
                total_size += get_dir_size(entry.path)
    except PermissionError:
        return 0
    return total_size

def format_size(size):
    """Formatea el tamaño en bytes a un formato legible (KB, MB, etc.)."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return "∞"

def safe_remove(path):
    """Elimina de forma segura un archivo o directorio."""
    try:
        if os.path.isfile(path) or os.path.islink(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        return True, "Eliminado correctamente"
    except Exception as e:
        return False, str(e)

class FileServer(BaseHTTPRequestHandler):

    def do_POST(self):
        """Maneja las peticiones POST: subida de archivos, descarga por URL, crear carpetas y borrar."""
        try:
            content_type = self.headers.get("Content-Type", "")
            path = urllib.parse.unquote(self.path).lstrip("/")
            if not path:
                path = ROOT_DIR

            # 1. Manejo de subida de archivos (multipart/form-data)
            if "multipart/form-data" in content_type:
                boundary = content_type.split("boundary=")[1].encode()
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)

                parts = body.split(b"--" + boundary)
                for part in parts:
                    if b'filename="' not in part:
                        continue

                    header_end = part.find(b"\r\n\r\n")
                    if header_end == -1:
                        continue

                    headers = part[:header_end]
                    data = part[header_end + 4:-2]

                    filename_start = headers.find(b'filename="') + 10
                    filename_end = headers.find(b'"', filename_start)
                    filename = headers[filename_start:filename_end].decode("utf-8")

                    if filename:
                        # Prevenir Directory Traversal
                        safe_filename = os.path.basename(filename)
                        with open(os.path.join(path, safe_filename), "wb") as f:
                            f.write(data)

                self.send_response(303)
                self.send_header("Location", self.path)
                self.end_headers()
                return

            # 2. Manejo de acciones vía JSON (AJAX desde el frontend)
            if "application/json" in content_type:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode('utf-8')
                data = json.loads(body)
                action = data.get('action')

                response_data = {"success": False, "message": "Acción desconocida"}

                if action == 'download_url':
                    url = data.get('url')
                    if url:
                        try:
                            # Contexto SSL para ignorar errores de certificados si es necesario
                            ctx = ssl.create_default_context()
                            ctx.check_hostname = False
                            ctx.verify_mode = ssl.CERT_NONE

                            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                            with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
                                # Intentar obtener el nombre del archivo de las cabeceras o la URL
                                file_name = ""
                                if 'Content-Disposition' in response.headers:
                                    cd = response.headers['Content-Disposition']
                                    if 'filename=' in cd:
                                        file_name = cd.split('filename=')[1].strip('"\'')
                                
                                if not file_name:
                                    parsed_url = urllib.parse.urlparse(url)
                                    file_name = os.path.basename(parsed_url.path)
                                    if not file_name:
                                        file_name = "descarga_" + str(int(time.time()))

                                safe_filename = os.path.basename(file_name)
                                dest_path = os.path.join(path, safe_filename)

                                with open(dest_path, 'wb') as out_file:
                                    shutil.copyfileobj(response, out_file)
                                
                            response_data = {"success": True, "message": f"Descargado: {safe_filename}"}
                        except Exception as e:
                            response_data = {"success": False, "message": f"Error descargando URL: {e}"}

                elif action == 'create_folder':
                    folder_name = data.get('folder_name')
                    if folder_name:
                        safe_folder_name = os.path.basename(folder_name)
                        new_dir = os.path.join(path, safe_folder_name)
                        try:
                            os.makedirs(new_dir, exist_ok=False)
                            response_data = {"success": True, "message": "Carpeta creada"}
                        except FileExistsError:
                            response_data = {"success": False, "message": "La carpeta ya existe"}
                        except Exception as e:
                            response_data = {"success": False, "message": str(e)}

                elif action == 'delete_item':
                    item_name = data.get('item_name')
                    if item_name:
                        # Evitar subir en el arbol de directorios
                        safe_item_name = os.path.basename(item_name)
                        target_path = os.path.join(path, safe_item_name)
                        
                        # Medida de seguridad extra: asegurarse que target_path está dentro de ROOT_DIR
                        if os.path.abspath(target_path).startswith(os.path.abspath(ROOT_DIR)):
                            success, msg = safe_remove(target_path)
                            response_data = {"success": success, "message": msg}
                        else:
                            response_data = {"success": False, "message": "Ruta inválida"}


                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response_data).encode('utf-8'))
                return

            self.send_error(400, "Content-Type inválido")

        except Exception as e:
            print(f"Error en POST: {e}")
            self.send_error(500, f"Error interno: {e}")

    def do_GET(self):
        """Maneja las peticiones GET: sirve archivos o genera el listado HTML del directorio."""
        path = urllib.parse.unquote(self.path).lstrip("/")
        if not path:
            path = ROOT_DIR

        # Si es un directorio, generamos el HTML
        if os.path.isdir(path):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

            try:
                files = os.listdir(path)
            except PermissionError:
                self.wfile.write("Acceso denegado".encode("utf-8"))
                return

            # Ordenar: primero carpetas, luego archivos alfabéticamente
            files.sort(key=lambda x: (not os.path.isdir(os.path.join(path, x)), x.lower()))

            rel = os.path.relpath(path, ROOT_DIR)
            parts = ["Raíz"] if rel == "." else ["Raíz"] + rel.split(os.sep)

            breadcrumb_html = ""
            acc = ""
            for p in parts:
                breadcrumb_html += f'<a href="/{acc}">{p}</a> / '
                acc = f"{acc}/{p}" if acc else ""

            html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>📂 LAN Pro Server</title>
    <style>
        :root {{
            --primary: #10b981; --primary-hover: #059669;
            --bg: #0f172a; --surface: #1e293b; --surface-hover: #334155;
            --text: #f8fafc; --text-muted: #94a3b8;
            --accent: #38bdf8; --danger: #ef4444; --danger-hover: #dc2626;
            --border: #334155;
        }}
        * {{ box-sizing: border-box; }}
        body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; margin: 0; padding: 20px; line-height: 1.5; }}
        .container {{ max-width: 1200px; margin: auto; background: var(--surface); padding: 30px; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
        
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 15px; }}
        .header h2 {{ margin: 0; display: flex; align-items: center; gap: 10px; }}
        .breadcrumb {{ font-size: 1.1em; margin-bottom: 20px; padding: 10px; background: rgba(0,0,0,0.2); border-radius: 8px; }}
        a {{ color: var(--accent); text-decoration: none; transition: color 0.2s; }}
        a:hover {{ color: #7dd3fc; text-decoration: underline; }}
        
        /* Controles (Subir, URL, Carpeta, Buscar) */
        .controls-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px; margin-bottom: 25px; }}
        
        .control-card {{ border: 1px solid var(--border); padding: 15px; border-radius: 10px; background: rgba(0,0,0,0.1); }}
        .control-card h3 {{ margin-top: 0; font-size: 1em; color: var(--text-muted); margin-bottom: 10px; }}
        
        .upload-area {{ border: 2px dashed var(--border); padding: 20px; text-align: center; border-radius: 8px; cursor: pointer; transition: all 0.2s; position: relative; }}
        .upload-area:hover {{ border-color: var(--primary); background: rgba(16, 185, 129, 0.05); }}
        .upload-area input[type="file"] {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; }}
        
        .input-group {{ display: flex; gap: 10px; }}
        .input-group input[type="text"] {{ flex: 1; padding: 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--bg); color: var(--text); outline: none; }}
        .input-group input[type="text"]:focus {{ border-color: var(--accent); }}
        
        button {{ padding: 10px 15px; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; transition: background 0.2s; }}
        button.btn-primary {{ background: var(--primary); color: white; }}
        button.btn-primary:hover {{ background: var(--primary-hover); }}
        button.btn-danger {{ background: var(--danger); color: white; padding: 5px 10px; font-size: 0.9em; }}
        button.btn-danger:hover {{ background: var(--danger-hover); }}

        /* Tabla */
        .search-bar {{ width: 100%; padding: 12px; margin-bottom: 15px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg); color: var(--text); font-size: 1em; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 12px 15px; border-bottom: 1px solid var(--border); text-align: left; }}
        th {{ color: var(--text-muted); font-weight: 600; background: rgba(0,0,0,0.2); position: sticky; top: 0; }}
        tr.item-row:hover td {{ background: var(--surface-hover); }}
        .item-name-cell {{ display: flex; align-items: center; gap: 10px; }}
        .actions-cell {{ text-align: right; width: 80px; }}
        
        /* Notificaciones */
        #toast {{ visibility: hidden; min-width: 250px; background-color: #333; color: #fff; text-align: center; border-radius: 8px; padding: 16px; position: fixed; z-index: 1; left: 50%; bottom: 30px; transform: translateX(-50%); font-size: 17px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }}
        #toast.show {{ visibility: visible; animation: fadein 0.5s, fadeout 0.5s 2.5s; }}
        @keyframes fadein {{ from {{bottom: 0; opacity: 0;}} to {{bottom: 30px; opacity: 1;}} }}
        @keyframes fadeout {{ from {{bottom: 30px; opacity: 1;}} to {{bottom: 0; opacity: 0;}} }}
        
        @media (max-width: 768px) {{
            th:nth-child(3), td:nth-child(3) {{ display: none; }} /* Ocultar fecha en móvil */
        }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h2>🚀 LAN Pro</h2>
    </div>
    
    <div class="breadcrumb">{breadcrumb_html}</div>

    <div class="controls-grid">
        <!-- Subir Archivo Local -->
        <div class="control-card">
            <h3>📤 Subir Archivo</h3>
            <form id="uploadForm" class="upload-area" method="POST" enctype="multipart/form-data">
                <input type="file" name="file" multiple onchange="showUploadProgress(); this.form.submit()">
                <div id="uploadText">Arrastra archivos aquí o haz clic</div>
            </form>
        </div>

        <!-- Descargar desde URL -->
        <div class="control-card">
            <h3>🔗 Descargar desde URL</h3>
            <div class="input-group">
                <input type="text" id="urlInput" placeholder="https://ejemplo.com/archivo.zip">
                <button class="btn-primary" onclick="downloadUrl()">Descargar</button>
            </div>
        </div>

        <!-- Crear Carpeta -->
        <div class="control-card">
            <h3>📁 Nueva Carpeta</h3>
            <div class="input-group">
                <input type="text" id="folderInput" placeholder="Nombre de la carpeta">
                <button class="btn-primary" onclick="createFolder()">Crear</button>
            </div>
        </div>
    </div>

    <input type="text" id="searchInput" class="search-bar" placeholder="🔍 Filtrar archivos..." onkeyup="filterFiles()">

    <table id="filesTable">
        <thead>
            <tr>
                <th>Nombre</th>
                <th style="text-align:right">Tamaño</th>
                <th style="text-align:right">Modificado</th>
                <th style="text-align:center">Acción</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><div class="item-name-cell">🔙 <a href="../">.. (Volver)</a></div></td>
                <td></td>
                <td></td>
                <td></td>
            </tr>
"""
            for f in files:
                full = os.path.join(path, f)
                try:
                    stat = os.stat(full)
                    mtime = time.strftime("%d/%m/%Y %H:%M", time.localtime(stat.st_mtime))
                    is_dir = os.path.isdir(full)

                    if is_dir:
                        size = format_size(get_dir_size(full))
                        icon = "📁"
                        link = f"{f}/"
                    else:
                        size = format_size(stat.st_size)
                        ext = os.path.splitext(f)[1].lower()
                        icon = {
                            ".jpg": "🖼️", ".jpeg": "🖼️", ".png": "🖼️", ".gif": "🖼️", ".webp": "🖼️",
                            ".mp4": "🎬", ".mkv": "🎬", ".avi": "🎬",
                            ".mp3": "🎵", ".wav": "🎵", ".flac": "🎵",
                            ".zip": "📦", ".rar": "📦", ".7z": "📦", ".tar": "📦", ".gz": "📦",
                            ".pdf": "📕", ".doc": "📘", ".docx": "📘", ".xls": "📗", ".xlsx": "📗",
                            ".txt": "📄", ".py": "🐍", ".js": "🟨", ".html": "🌐", ".css": "🎨"
                        }.get(ext, "📄")
                        link = f

                    html += f"""
            <tr class="item-row">
                <td>
                    <div class="item-name-cell">
                        <span>{icon}</span> 
                        <a href="{link}" class="file-name">{f}</a>
                    </div>
                </td>
                <td style="text-align:right">{size}</td>
                <td style="text-align:right; color: var(--text-muted); font-size: 0.9em;">{mtime}</td>
                <td class="actions-cell">
                    <button class="btn-danger" onclick="deleteItem('{f}')" title="Eliminar">🗑️</button>
                </td>
            </tr>
"""
                except Exception as e:
                    print(f"Error procesando {f}: {e}")
                    pass

            html += """
        </tbody>
    </table>
    
    <p style="text-align:center;color:var(--text-muted); margin-top: 30px; font-size: 0.9em;">
        Servidor LAN Pro v2.0 • Python Multi-hilo
    </p>
</div>

<div id="toast">Notificación</div>

<script>
    // Mostrar notificaciones flotantes (Toasts)
    function showToast(msg, isError = false) {
        const toast = document.getElementById("toast");
        toast.textContent = msg;
        toast.style.backgroundColor = isError ? "#ef4444" : "#10b981";
        toast.className = "show";
        setTimeout(function(){ toast.className = toast.className.replace("show", ""); }, 3000);
    }

    // Cambiar texto al subir archivo
    function showUploadProgress() {
        document.getElementById('uploadText').innerHTML = '⏳ Subiendo archivo(s)...<br><small>Por favor, espere.</small>';
    }

    // Filtrar tabla
    function filterFiles() {
        let input = document.getElementById('searchInput');
        let filter = input.value.toUpperCase();
        let table = document.getElementById('filesTable');
        let tr = table.getElementsByClassName('item-row');

        for (let i = 0; i < tr.length; i++) {
            let td = tr[i].getElementsByClassName('file-name')[0];
            if (td) {
                let txtValue = td.textContent || td.innerText;
                if (txtValue.toUpperCase().indexOf(filter) > -1) {
                    tr[i].style.display = "";
                } else {
                    tr[i].style.display = "none";
                }
            }
        }
    }

    // Enviar peticiones JSON al backend
    async function sendAction(action, data) {
        try {
            const response = await fetch('', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: action, ...data })
            });
            const result = await response.json();
            
            showToast(result.message, !result.success);
            
            if (result.success) {
                setTimeout(() => window.location.reload(), 1000);
            }
        } catch (error) {
            showToast("Error de conexión", true);
        }
    }

    // Acciones de botones
    function downloadUrl() {
        const url = document.getElementById('urlInput').value.trim();
        if (!url) return showToast("Introduce una URL válida", true);
        showToast("⏳ Iniciando descarga desde URL...");
        sendAction('download_url', { url: url });
    }

    function createFolder() {
        const name = document.getElementById('folderInput').value.trim();
        if (!name) return showToast("Introduce un nombre", true);
        sendAction('create_folder', { folder_name: name });
    }

    function deleteItem(name) {
        if (confirm(`¿Estás seguro de que quieres eliminar '${name}'? Esta acción no se puede deshacer.`)) {
            sendAction('delete_item', { item_name: name });
        }
    }
</script>
</body>
</html>
"""
            self.wfile.write(html.encode("utf-8"))

        elif os.path.isfile(path):
            try:
                mime, _ = mimetypes.guess_type(path)
                self.send_response(200)
                self.send_header("Content-Type", mime or "application/octet-stream")
                self.send_header("Content-Length", str(os.path.getsize(path)))
                # Forzar descarga para ciertos tipos de archivos si se desea
                # self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
                self.end_headers()
                with open(path, "rb") as f:
                    shutil.copyfileobj(f, self.wfile)
            except Exception as e:
                self.send_error(500, f"Error leyendo el archivo: {e}")
        else:
            self.send_error(404, "No encontrado")

def get_ip():
    """Obtiene la IP local de la máquina en la red."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No necesita conectar realmente, solo determina la interfaz correcta
        s.connect(("8.8.8.8", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

if __name__ == "__main__":
    ip = get_ip()
    print("=" * 50)
    print("🚀 SERVIDOR LAN PRO v2.0 INICIADO")
    print("=" * 50)
    print(f"📁 Directorio Raíz: {ROOT_DIR}")
    print(f"🏠 Acceso Local   : http://localhost:{PORT}")
    print(f"🌍 Acceso en Red  : http://{ip}:{PORT}")
    print("=" * 50)
    print("Presiona Ctrl+C para detener el servidor.")

    # Asegurar que el servidor soporta múltiples hilos para que una descarga pesada no bloquee la interfaz
    server = ThreadingHTTPServer(("0.0.0.0", PORT), FileServer)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Servidor detenido de forma segura.")
        server.server_close()
