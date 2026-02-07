# -*- coding: utf-8 -*-

import os
import socket
import urllib.parse
import time
import shutil
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8000
ROOT_DIR = os.getcwd()


def get_dir_size(path):
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
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return "∞"


class FileServer(BaseHTTPRequestHandler):

    def do_POST(self):
        try:
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                self.send_error(400, "Content-Type inválido")
                return

            boundary = content_type.split("boundary=")[1].encode()
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)

            path = urllib.parse.unquote(self.path).lstrip("/")
            if not path:
                path = ROOT_DIR

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
                    with open(os.path.join(path, filename), "wb") as f:
                        f.write(data)

            self.send_response(303)
            self.send_header("Location", self.path)
            self.end_headers()

        except Exception as e:
            self.send_error(500, f"Error subiendo archivo: {e}")

    def do_GET(self):
        path = urllib.parse.unquote(self.path).lstrip("/")
        if not path:
            path = ROOT_DIR

        if os.path.isdir(path):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

            try:
                files = os.listdir(path)
            except PermissionError:
                self.wfile.write("Acceso denegado".encode("utf-8"))
                return

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
<title>📂 Servidor LAN Pro</title>
<style>
:root {{
--primary:#00ff88;--bg:#0f172a;--surface:#1e293b;--text:#f8fafc;--accent:#38bdf8;
}}
body {{background:var(--bg);color:var(--text);font-family:system-ui;margin:0;padding:20px}}
.container {{max-width:1100px;margin:auto;background:var(--surface);padding:25px;border-radius:16px}}
a {{color:var(--accent);text-decoration:none}}
table {{width:100%;border-collapse:collapse}}
th,td {{padding:12px;border-bottom:1px solid #334155}}
tr:hover td {{background:#2d3e5a}}
.upload {{border:2px dashed #475569;padding:20px;text-align:center;border-radius:10px}}
</style>
</head>
<body>
<div class="container">
<h2>🚀 LAN Pro</h2>
<div>{breadcrumb_html}</div>

<form class="upload" method="POST" enctype="multipart/form-data">
<input type="file" name="file" multiple onchange="this.form.submit()">
<p>📤 Arrastra archivos o haz clic para subir</p>
</form>

<table>
<tr><th>Nombre</th><th style="text-align:right">Tamaño</th><th style="text-align:right">Modificado</th></tr>
<tr><td>🔙 <a href="../">.. (Volver)</a></td><td></td><td></td></tr>
"""

            for f in files:
                full = os.path.join(path, f)
                try:
                    stat = os.stat(full)
                    mtime = time.strftime("%d/%m/%Y %H:%M", time.localtime(stat.st_mtime))

                    if os.path.isdir(full):
                        size = format_size(get_dir_size(full))
                        icon = "📁"
                        link = f"{f}/"
                    else:
                        size = format_size(stat.st_size)
                        ext = os.path.splitext(f)[1].lower()
                        icon = {
                            ".jpg": "🖼️", ".png": "🖼️", ".gif": "🖼️",
                            ".mp4": "🎬", ".mp3": "🎵",
                            ".zip": "📦", ".rar": "📦",
                            ".pdf": "📕"
                        }.get(ext, "📄")
                        link = f

                    html += f"""
<tr>
<td>{icon} <a href="{link}">{f}</a></td>
<td style="text-align:right">{size}</td>
<td style="text-align:right">{mtime}</td>
</tr>
"""
                except Exception:
                    pass

            html += """
</table>
<p style="text-align:center;color:#64748b">Hecho con 🐍 Python • Servidor multihilo</p>
</div>
</body>
</html>
"""
            self.wfile.write(html.encode("utf-8"))

        elif os.path.isfile(path):
            mime, _ = mimetypes.guess_type(path)
            self.send_response(200)
            self.send_header("Content-Type", mime or "application/octet-stream")
            self.send_header("Content-Length", str(os.path.getsize(path)))
            self.end_headers()
            with open(path, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
        else:
            self.send_error(404, "No encontrado")


def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


if __name__ == "__main__":
    ip = get_ip()
    print("=" * 40)
    print("🚀 SERVIDOR LAN PRO INICIADO")
    print(f"Local: http://localhost:{PORT}")
    print(f"Red  : http://{ip}:{PORT}")
    print("=" * 40)

    server = ThreadingHTTPServer(("0.0.0.0", PORT), FileServer)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Servidor detenido")
        server.server_close()
