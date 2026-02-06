import os
import socket
import urllib.parse
import time
import shutil
import mimetypes
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO

PORT = 8000

def get_dir_size(path):
    """Calcula el tamaÃ±o total de un directorio de forma recursiva."""
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
    for unit in ['B','KB','MB','GB','TB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return "âˆž"

class FileServer(BaseHTTPRequestHandler):

    def do_POST(self):
        """Maneja la subida de archivos."""
        try:
            content_type = self.headers.get('Content-Type')
            if not content_type or 'multipart/form-data' not in content_type:
                self.send_error(400, "Bad Request: Content-Type must be multipart/form-data")
                return

            # Extraer el path actual del referrer o de la URL
            path = urllib.parse.unquote(self.path).lstrip('/')
            if not path or path == ".": path = os.getcwd()
            
            # Procesamiento simplificado de multipart para evitar dependencias externas
            content_length = int(self.headers.get('Content-Length'))
            body = self.rfile.read(content_length)
            
            # Buscar el nombre del archivo y los datos
            # Nota: Esto es una implementaciÃ³n bÃ¡sica. En producciÃ³n se usarÃ­a cgi.FieldStorage
            boundary = content_type.split("boundary=")[1].encode()
            parts = body.split(boundary)
            
            for part in parts:
                if b'filename="' in part:
                    # Extraer nombre de archivo
                    fn_start = part.find(b'filename="') + 10
                    fn_end = part.find(b'"', fn_start)
                    filename = part[fn_start:fn_end].decode('utf-8')
                    
                    # Extraer contenido (despuÃ©s de \r\n\r\n)
                    data_start = part.find(b'\r\n\r\n') + 4
                    data_end = part.rfind(b'\r\n')
                    file_content = part[data_start:data_end]
                    
                    with open(os.path.join(path, filename), 'wb') as f:
                        f.write(file_content)

            self.send_response(303) # Redirect back
            self.send_header('Location', self.path)
            self.end_headers()
        except Exception as e:
            self.send_error(500, f"Error subiendo archivo: {e}")

    def do_GET(self):
        path = urllib.parse.unquote(self.path).lstrip('/')
        if path == "" or path == ".":
            path = os.getcwd()

        if os.path.isdir(path):
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()

            try:
                files = os.listdir(path)
            except PermissionError:
                self.wfile.write(b"Acceso denegado")
                return

            files.sort(key=lambda x: (not os.path.isdir(os.path.join(path, x)), x.lower()))

            # Generar Breadcrumbs
            parts = path.replace(os.getcwd(), "Raiz").split(os.sep)
            breadcrumb_html = ""
            curr_link = "/"
            for p in parts:
                breadcrumb_html += f'<span>/</span><a href="{curr_link}">{p}</a>'

            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <title>ðŸ“‚ Servidor LAN Pro</title>
                <style>
                    :root {{ 
                        --primary: #00ff88; 
                        --bg: #0f172a; 
                        --surface: #1e293b; 
                        --text: #f8fafc;
                        --accent: #38bdf8;
                    }}
                    body {{ font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text); padding: 20px; margin: 0; }}
                    .container {{ max-width: 1100px; margin: auto; background: var(--surface); padding: 25px; border-radius: 16px; box-shadow: 0 20px 50px rgba(0,0,0,0.3); }}
                    
                    /* Header & Nav */
                    .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }}
                    .breadcrumbs {{ font-size: 0.9em; color: #94a3b8; margin-bottom: 20px; }}
                    .breadcrumbs a {{ color: var(--accent); text-decoration: none; margin: 0 5px; }}
                    
                    /* Upload Area */
                    .upload-zone {{ border: 2px dashed #475569; padding: 20px; border-radius: 10px; text-align: center; margin-bottom: 20px; transition: 0.3s; }}
                    .upload-zone:hover {{ border-color: var(--primary); background: #1e293b; }}
                    .upload-zone input[type="file"] {{ display: none; }}
                    .btn-upload {{ background: var(--primary); color: #000; padding: 8px 20px; border-radius: 6px; cursor: pointer; font-weight: bold; border: none; }}
                    
                    input#search {{ width: 100%; padding: 12px; margin-bottom: 20px; background: #0f172a; border: 1px solid #334155; color: white; border-radius: 8px; box-sizing: border-box; }}
                    
                    table {{ width: 100%; border-collapse: collapse; }}
                    th {{ text-align: left; color: #94a3b8; border-bottom: 2px solid #334155; padding: 12px; font-size: 0.85em; text-transform: uppercase; }}
                    td {{ padding: 12px; border-bottom: 1px solid #334155; transition: 0.2s; }}
                    tr:hover td {{ background: #2d3e5a; }}
                    
                    a {{ color: #e2e8f0; text-decoration: none; }}
                    .folder {{ color: #fbbf24; font-weight: 600; }}
                    .file-link {{ display: flex; align-items: center; gap: 10px; }}
                    
                    .badge {{ font-size: 0.75em; padding: 2px 6px; border-radius: 4px; background: #334155; color: #cbd5e1; }}
                    
                    @media (max-width: 600px) {{
                        .hide-mobile {{ display: none; }}
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2 style="margin:0">ðŸš€ LAN Pro</h2>
                        <div class="badge">Puerto: {PORT}</div>
                    </div>

                    <div class="breadcrumbs">
                        {breadcrumb_html}
                    </div>

                    <form class="upload-zone" method="POST" enctype="multipart/form-data">
                        <p style="margin:0 0 10px 0; color: #94a3b8;">ðŸ“¤ Arrastra archivos o haz clic aquÃ­ para subir</p>
                        <label class="btn-upload">
                            Seleccionar Archivos
                            <input type="file" name="file" multiple onchange="this.form.submit()">
                        </label>
                    </form>

                    <input type="text" id="search" placeholder="ðŸ” Filtrar en este directorio..." onkeyup="filterFiles()">
                    
                    <table id="fileTable">
                        <thead>
                            <tr>
                                <th>Nombre</th>
                                <th style="text-align: right;">TamaÃ±o</th>
                                <th class="hide-mobile" style="text-align: right;">Modificado</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td>ðŸ”™ <a href="../" style="color:var(--accent)">.. (Volver atrÃ¡s)</a></td>
                                <td></td>
                                <td class="hide-mobile"></td>
                            </tr>
            """

            for f in files:
                full_path = os.path.join(path, f)
                try:
                    stat = os.stat(full_path)
                    mtime = time.strftime("%d/%m/%Y %H:%M", time.localtime(stat.st_mtime))
                    
                    if os.path.isdir(full_path):
                        # Nota: get_dir_size puede ser lento en discos muy grandes
                        # Puedes comentar la lÃ­nea de abajo y poner "---" si prefieres velocidad
                        size_str = format_size(get_dir_size(full_path))
                        icon = "ðŸ“"
                        link = f"{f}/"
                        cls = "folder"
                    else:
                        size_str = format_size(stat.st_size)
                        # Iconos por extensiÃ³n
                        ext = os.path.splitext(f)[1].lower()
                        if ext in ['.jpg', '.png', '.gif', '.webp']: icon = "ðŸ–¼ï¸"
                        elif ext in ['.mp4', '.mkv', '.avi']: icon = "ðŸŽ¬"
                        elif ext in ['.mp3', '.wav']: icon = "ðŸŽµ"
                        elif ext in ['.zip', '.rar', '.7z']: icon = "ðŸ“¦"
                        elif ext in ['.pdf']: icon = "ðŸ“•"
                        else: icon = "ðŸ“„"
                        link = f"{f}"
                        cls = "file"

                    html += f"""
                    <tr>
                        <td>
                            <div class="file-link">
                                <span>{icon}</span>
                                <a class="{cls}" href="{link}">{f}</a>
                            </div>
                        </td>
                        <td style="text-align: right; font-family: 'JetBrains Mono', monospace; font-size: 0.9em;">{size_str}</td>
                        <td class="hide-mobile" style="text-align: right; font-size: 0.85em; color: #64748b;">{mtime}</td>
                    </tr>
                    """
                except Exception:
                    continue

            html += """
                        </tbody>
                    </table>
                    <div style="margin-top: 20px; font-size: 0.8em; color: #475569; text-align: center;">
                        Hecho con ðŸ Python â€¢ Servidor Multihilo Activo
                    </div>
                </div>
                <script>
                    function filterFiles() {
                        let input = document.getElementById('search').value.toLowerCase();
                        let rows = document.querySelectorAll('#fileTable tbody tr');
                        rows.forEach((row, index) => {
                            if (index === 0) return; // Saltarse el "Volver atrÃ¡s"
                            let name = row.querySelector('td').innerText.toLowerCase();
                            row.style.display = name.includes(input) ? '' : 'none';
                        });
                    }
                </script>
            </body>
            </html>
            """
            self.wfile.write(html.encode("utf-8"))

        elif os.path.isfile(path):
            # DetecciÃ³n dinÃ¡mica de MIME para que el navegador sepa quÃ© hacer (reproducir video, ver imagen, etc)
            mime_type, _ = mimetypes.guess_type(path)
            if not mime_type: mime_type = "application/octet-stream"
            
            self.send_response(200)
            self.send_header("Content-type", mime_type)
            self.send_header("Content-Length", str(os.path.getsize(path)))
            self.end_headers()
            
            with open(path, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
        else:
            self.send_error(404, "No encontrado")

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

local_ip = get_ip()


if __name__ == "__main__":
    print(f"\n" + "="*40)
    print(f"ðŸš€ SERVIDOR LAN PRO INICIADO")
    print(f"URL: http://localhost:{PORT}")
    print(f"En tu red: http://{local_ip}:{PORT}")
    print("="*40 + "\n")
    
    # ThreadingHTTPServer permite mÃºltiples conexiones concurrentes (descargas paralelas)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), FileServer)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nðŸ›‘ Servidor detenido.")
        server.server_close()
