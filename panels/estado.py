# Panel Estado de la impresora (Wences MK2): resumen de lo que miden y guardan las macros
# propias (mantenimiento, eje Z y lamina, mecanica, filamentos y fecha de las ultimas
# medidas). Datos en ks_includes/wences.py. Se abre desde el menu principal (boton Estado),
# tocando los avisos de la barra superior o con RESPOND TYPE=command MSG="action:ks_show estado".
import logging

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango

from ks_includes import wences
from ks_includes.screen_panel import ScreenPanel


class Panel(ScreenPanel):
    def __init__(self, screen, title):
        title = title or "Estado de la impresora"
        super().__init__(screen, title)
        self.fechas = {}
        self._firma = None

        self.cols = Gtk.Grid(column_homogeneous=True, column_spacing=12, row_spacing=6,
                             hexpand=True, vexpand=True)
        scroll = self._gtk.ScrolledWindow()
        scroll.add(self.cols)

        botones = Gtk.Box(spacing=6, homogeneous=True, vexpand=False)
        for icono, texto, accion in (("info", "Mantenimiento", "MANTENIMIENTO"),
                                     ("filament", "Consumo", "CONSUMO"),
                                     ("refresh", "Actualizar", None)):
            b = self._gtk.Button(icono, texto, "color2" if accion else "color3", self.bts,
                                 Gtk.PositionType.LEFT, 1)
            if accion:
                b.connect("clicked", self.macro, accion)
            else:
                b.connect("clicked", self.actualizar)
            botones.add(b)

        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        caja.pack_start(scroll, True, True, 0)
        caja.pack_end(botones, False, False, 0)
        self.content.add(caja)
        self.actualizar()

    def macro(self, widget, nombre):
        self._screen._send_action(widget, "printer.gcode.script", {"script": nombre})

    def activate(self):
        self.actualizar()

    def actualizar(self, *args):
        self.pintar()
        wences.pedir_fechas(self._screen, self.fechas_recibidas)

    def fechas_recibidas(self, fechas):
        self.fechas = fechas
        self.pintar()
        return False

    def process_update(self, action, data):
        if action != "notify_status_update":
            return
        if "save_variables" in data or "configfile" in data:
            self.pintar()

    def seccion(self, titulo, filas):
        g = Gtk.Grid(column_spacing=10, row_spacing=2, hexpand=True)
        cab = Gtk.Label(halign=Gtk.Align.START)
        cab.set_markup(f"<b>{GLib.markup_escape_text(titulo)}</b>")
        cab.get_style_context().add_class("printing-status")
        g.attach(cab, 0, 0, 2, 1)
        for i, (etiqueta, valor, color) in enumerate(filas, 1):
            e = Gtk.Label(label=etiqueta, halign=Gtk.Align.START, valign=Gtk.Align.START)
            v = Gtk.Label(halign=Gtk.Align.END, hexpand=True, xalign=1, wrap=True,
                          wrap_mode=Pango.WrapMode.WORD_CHAR)
            txt = GLib.markup_escape_text(str(valor))
            v.set_markup(f'<span foreground="{color}"><b>{txt}</b></span>' if color else txt)
            g.attach(e, 0, i, 1, 1)
            g.attach(v, 1, i, 1, 1)
        return g

    def pintar(self):
        try:
            secciones = wences.resumen(self._printer, self.fechas)
        except Exception as e:
            logging.exception(f"estado: {e}")
            return
        firma = repr(secciones)
        if firma == self._firma:
            return
        self._firma = firma
        for hijo in self.cols.get_children():
            self.cols.remove(hijo)
        # dos columnas: reparto por numero de filas para que queden parejas
        izq, der, n_izq, n_der = [], [], 0, 0
        for t, filas in secciones:
            if n_izq <= n_der:
                izq.append((t, filas)); n_izq += len(filas) + 1
            else:
                der.append((t, filas)); n_der += len(filas) + 1
        for col, lista in ((0, izq), (1, der)):
            caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.START)
            for t, filas in lista:
                caja.add(self.seccion(t, filas))
            self.cols.attach(caja, col, 0, 1, 1)
        self.cols.show_all()
