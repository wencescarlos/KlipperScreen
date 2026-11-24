# Wences MK2: datos de las macros propias (repo wencescarlos/wences-mk2-macros) para la
# pantalla. Lo usan la barra superior (panels/base_panel.py), el panel Estado
# (panels/estado.py) y la pantalla de impresion (panels/job_status.py).
# Todo sale de objetos de Klipper suscritos (save_variables, macros) y de la lista de
# archivos de la config (fechas de config/historial/*.json, estudio de cama e imanes).
import json
import logging
import math
import threading
import time
import urllib.request
from datetime import datetime

from gi.repository import GLib

AMBAR = "#ffb300"
ROJO = "#ff5252"

# Objetos que hay que suscribir (screen.py los anade a los de KlipperScreen)
OBJETOS = {
    "save_variables": ["variables"],
    "gcode_macro MODO_SILENCIOSO": ["activo"],
    "gcode_macro _MANT": ["tareas"],
    "gcode_macro _FILAMENTOS": ["tipos", "pa"],
}

# Historiales que guardan las macros: archivo -> nombre en pantalla
HISTORIALES = {
    "historial/escuadra.json": "Escuadra XY",
    "historial/altura_z.json": "Altura Z",
    "historial/zoffset.json": "z_offset",
    "historial/tuercas_pom.json": "Topes de Z",
    "historial/tuercas_z.json": "Tuercas Z",
    "historial/sensorless.json": "Sensorless",
    "historial/pa.json": "Pressure advance",
    "historial/flujo.json": "Flujo",
    "estudio_cama.json": "Estudio de la cama",
}


def suscribir(requested_updates):
    for obj, campos in OBJETOS.items():
        requested_updates["objects"].setdefault(obj, campos)


def num(v, d=2, signo=False):
    """Numero con coma decimal (es_ES)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    txt = f"{v:+.{d}f}" if signo else f"{v:.{d}f}"
    return txt.replace(".", ",").replace("-", "−")


def variables(printer):
    return printer.get_stat("save_variables", "variables") or {}


def cfg(printer, seccion, clave, defecto=None):
    """Valor de printer.cfg (configfile.config da cadenas)."""
    sec = printer.get_config_section(seccion)
    if not sec or clave not in sec:
        return defecto
    try:
        return float(sec[clave])
    except (TypeError, ValueError):
        return sec[clave]


def mantenimiento(printer):
    """Horas, tareas pendientes y la proxima, como MANTENIMIENTO."""
    sv = variables(printer)
    m = sv.get("mant") or {}
    horas = float(m.get("horas", 0) or 0)
    hecho = m.get("hecho") or {}
    tareas = printer.get_stat("gcode_macro _MANT", "tareas") or {}
    pendientes, proxima = [], None
    for clave, t in tareas.items():
        try:
            desc, cada = t[0], float(t[1])
        except (TypeError, IndexError, ValueError):
            continue
        falta = cada - (horas - float(hecho.get(clave, 0) or 0))
        if falta <= 0:
            pendientes.append(desc)
        elif proxima is None or falta < proxima[1]:
            proxima = (desc, falta)
    return {"horas": horas, "pendientes": pendientes, "proxima": proxima,
            "filamento_m": float(m.get("filamento_m", 0) or 0)}


def lamina(printer):
    bs = variables(printer).get("bed_surfaces") or {}
    nombre = bs.get("active") or "default"
    off = ((bs.get("available") or {}).get(nombre) or {}).get("offset", 0.0)
    return nombre, off


def avisos(printer):
    """[(texto, color)] para la barra superior."""
    sv = variables(printer)
    res = []
    if sv.get("plr"):
        res.append(("RECUPERAR", ROJO))
    if mantenimiento(printer)["pendientes"]:
        res.append(("MANTENIMIENTO", AMBAR))
    return res


def pa(printer, tipo):
    """(valor, medido) del pressure advance guardado de un filamento."""
    v = variables(printer).get("pa_" + tipo.lower())
    if v is not None:
        return v, True
    return (printer.get_stat("gcode_macro _FILAMENTOS", "pa") or {}).get(tipo), False


def edad(ts):
    """'24/11 · hoy', '15/11 · hace 10 dias'... desde una marca de tiempo."""
    if not ts:
        return "nunca"
    dia = datetime.fromtimestamp(ts).strftime("%d/%m")
    dias = (datetime.now().date() - datetime.fromtimestamp(ts).date()).days
    if dias <= 0:
        return f"{dia} · hoy"
    if dias == 1:
        return f"{dia} · ayer"
    return f"{dia} · hace {dias} días"


def resumen(printer, fechas):
    """Secciones del panel Estado: [(titulo, [(etiqueta, valor, color|None)])]."""
    sv = variables(printer)
    secciones = []
    # --- Mantenimiento
    m = mantenimiento(printer)
    filas = [("Horas", f"{num(m['horas'], 1)} h", None),
             ("Filamento", f"{num(m['filamento_m'], 0)} m", None)]
    if m["pendientes"]:
        for p in m["pendientes"]:
            filas.append(("TOCA YA", p, AMBAR))
    elif m["proxima"]:
        filas.append(("Próxima", f"{m['proxima'][0]} (en {num(m['proxima'][1], 0)} h)", None))
    secciones.append(("Mantenimiento", filas))
    # --- Z y lamina
    nombre, off = lamina(printer)
    alto = sv.get("altura_z_medida")
    pmax = cfg(printer, "stepper_z", "position_max")
    filas = [("z_offset", f"{num(cfg(printer, 'probe', 'z_offset'), 3)} mm", None),
             ("Lámina", f"{nombre} ({num(off, 3, True)} mm)", None)]
    if alto is not None and isinstance(pmax, float):
        filas.append(("Altura / máx.", f"{num(alto, 2)} / {num(pmax, 1)} mm",
                      AMBAR if alto - pmax < 0.5 else None))
    if sv.get("tuercas_pom_topes") is not None:
        t = sv["tuercas_pom_topes"]
        filas.append(("Topes", f"{num(t, 2, True)} mm ({'der.' if t < 0 else 'izq.'} más alto)", None))
    if sv.get("tuercas_z_izq_max") is not None:
        mx = max(sv.get("tuercas_z_izq_max") or 0, sv.get("tuercas_z_der_max") or 0)
        filas.append(("Tuercas Z", f"{num(sv.get('tuercas_z_izq_max'), 2)} / {num(sv.get('tuercas_z_der_max'), 2)} mm",
                      AMBAR if mx > 0.10 else None))
    secciones.append(("Eje Z y lámina", filas))
    # --- Mecanica
    filas = []
    sk = cfg(printer, "skew_correction pinda_skew", "xy_skew")
    if isinstance(sk, float):
        filas.append(("Escuadra", f"{num(math.degrees(math.atan(sk)), 3, True)}° ({num(abs(sk) * 200, 2)} mm en 200)", None))
    sx, sy = cfg(printer, "tmc2209 stepper_x", "driver_sgthrs"), cfg(printer, "tmc2209 stepper_y", "driver_sgthrs")
    if isinstance(sx, float):
        filas.append(("Sensorless", f"{sx:.0f} / {sy:.0f}", None))
    zonas = sum(1 for k in (printer.get_config_section("bed_mesh") or {}) if k.endswith("_min") and k.startswith("faulty_region"))
    filas.append(("Imanes", f"{zonas} en la malla", None))
    secciones.append(("Mecánica", filas))
    # --- Filamentos
    tipos = list((printer.get_stat("gcode_macro _FILAMENTOS", "tipos") or {}).keys())
    filas = []
    for t in tipos:
        v, medido = pa(printer, t)
        flujo = sv.get("flujo_" + t.lower())
        txt = f"PA {num(v, 3)}" + ("" if medido else " (sin calibrar)")
        if flujo is not None:
            txt += f" · flujo {num(flujo, 0)} mm³/s"
        filas.append((t, txt, None if medido else "#9aa5ae"))
    secciones.append(("Filamentos", filas))
    # --- Ultimas medidas
    filas = []
    for arch, nombre in HISTORIALES.items():
        ts = fechas.get(arch)
        if ts:
            filas.append((nombre, edad(ts), None))
    if fechas.get("escaneo_imanes"):
        filas.append(("Escaneo de imanes", edad(fechas["escaneo_imanes"]), None))
    secciones.append(("Últimas medidas", filas or [("—", "Sin historial todavía", None)]))
    return secciones


def _ultima_fecha(datos):
    """Fecha de la ultima entrada de un historial ([{fecha: 'AAAA-MM-DD HH:MM', ...}])."""
    try:
        f = datos[-1]["fecha"]
        return datetime.strptime(f[:16], "%Y-%m-%d %H:%M").timestamp()
    except Exception:
        return None


def pedir_fechas(screen, callback):
    """Fecha de la ultima medida de cada historial. Pide la lista de la config por el
    websocket y lee en segundo plano la ultima entrada de cada JSON; si no puede, usa la
    fecha de modificacion del archivo. Llama callback({archivo: marca de tiempo})."""
    def leer(fechas):
        base = getattr(screen, "moonraker_endpoint", "http://127.0.0.1:7125")
        clave = getattr(screen, "moonraker_api_key", "")
        for arch in [a for a in fechas if a in HISTORIALES]:
            try:
                req = urllib.request.Request(f"{base}/server/files/config/{arch}")
                if clave:
                    req.add_header("X-Api-Key", clave)
                with urllib.request.urlopen(req, timeout=15) as r:
                    ts = _ultima_fecha(json.loads(r.read().decode("utf-8")))
                if ts:
                    fechas[arch] = ts
            except Exception as e:
                logging.info(f"wences: no se pudo leer {arch} de {base}: {e}")
        GLib.idle_add(callback, fechas)

    def recibido(respuesta, *args):
        fechas = {}
        try:
            lista = respuesta.get("result", []) if isinstance(respuesta, dict) else []
            if not isinstance(lista, list):
                lista = lista.get("files", []) if isinstance(lista, dict) else []
            for f in lista:
                p = f.get("path", "")
                if p in HISTORIALES:
                    fechas[p] = f.get("modified")
                elif p.startswith("escaneo_imanes/") and p.endswith(".json"):
                    fechas["escaneo_imanes"] = max(fechas.get("escaneo_imanes", 0), f.get("modified", 0))
        except Exception as e:
            logging.debug(f"wences fechas: {e}")
        callback(dict(fechas))
        threading.Thread(target=leer, args=(fechas,), daemon=True).start()
        return False

    try:
        if not screen._ws.send_method("server.files.list", {"root": "config"}, recibido):
            logging.info("wences: no se pudo pedir la lista de archivos (sin conexion)")
    except Exception as e:
        logging.debug(f"wences pedir_fechas: {e}")
