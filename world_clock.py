"""Horário mundial: faixa na página inicial e página dedicada na ilha expandida."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from gi.repository import Gtk

from agenda_view import pill_button
from i18n import _
from views import clock_text, icon, label

GLOBE_ICON = "preferences-system-time-symbolic"
MAX_HOME_CITIES = 4
MAX_PAGE_CITIES = 8


def parse_cities(spec):
    """Converte 'Maceió|America/Maceio, London|Europe/London' em [(nome, tz), ...]."""
    items = []
    for raw in (spec or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        if "|" in raw:
            name, zone = (p.strip() for p in raw.split("|", 1))
        else:
            zone = raw
            name = zone.rsplit("/", 1)[-1].replace("_", " ")
        if not zone:
            continue
        try:
            tz = ZoneInfo(zone)
        except (ZoneInfoNotFoundError, KeyError, ValueError):
            continue
        items.append((name or zone, tz, zone))
    return items


def _offset_diff_text(local_now, target_now):
    local_off = local_now.utcoffset() or timedelta(0)
    target_off = target_now.utcoffset() or timedelta(0)
    diff_min = round((target_off - local_off).total_seconds() / 60)
    if diff_min == 0:
        return _("local")
    sign = "+" if diff_min > 0 else "-"
    diff_min = abs(diff_min)
    h, m = divmod(diff_min, 60)
    return f"{sign}{h}h{m:02d}" if m else f"{sign}{h}h"


def _day_text(local_now, target_now):
    d_diff = (target_now.date() - local_now.date()).days
    if d_diff > 0:
        return _("Amanhã")
    if d_diff < 0:
        return _("Ontem")
    return _("Hoje")


def resolve_clocks(spec, h24=True, now=None):
    """Retorna lista de dicts: name, zone, time, offset, day, subtitle."""
    local_now = (now or datetime.now()).astimezone()
    result = []
    for name, tz, zone in parse_cities(spec):
        target_now = local_now.astimezone(tz)
        off = _offset_diff_text(local_now, target_now)
        day = _day_text(local_now, target_now)
        result.append({
            "name": _(name),
            "zone": zone,
            "time": clock_text(target_now, h24),
            "offset": off,
            "day": day,
            "subtitle": f"{day} · {off}",
        })
    return result


class WorldClockHome(Gtk.Box):
    """Faixa compacta de fuso horário exibida na página inicial (abaixo do clima)."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_margin_top(12)

        head = Gtk.Box(spacing=6)
        head.pack_start(icon(GLOBE_ICON, 13), False, False, 0)
        self.title_lb = label("dim small")
        head.pack_start(self.title_lb, False, False, 0)
        self.pack_start(head, False, False, 0)

        self.cards = Gtk.Box(homogeneous=True, spacing=6)
        self.pack_start(self.cards, False, False, 0)

    def update(self, cfg, now=None):
        self.title_lb.set_text(_("Horário mundial"))
        for c in self.cards.get_children():
            self.cards.remove(c)
        clocks = resolve_clocks(cfg["world_cities"], cfg["clock_24h"], now)[:MAX_HOME_CITIES]
        if not clocks:
            return False
        for item in clocks:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            col.get_style_context().add_class("day")
            city_lb = label("dim small", 0.5, ellipsize=True)
            city_lb.set_text(item["name"])
            time_lb = label("clock", 0.5)
            time_lb.set_text(item["time"])
            off_lb = label("dim small", 0.5)
            off_lb.set_text(item["offset"])
            col.pack_start(city_lb, False, False, 0)
            col.pack_start(time_lb, False, False, 0)
            col.pack_start(off_lb, False, False, 0)
            self.cards.pack_start(col, True, True, 0)
        self.show_all()
        return True


class WorldClockPage(Gtk.Box):
    """Página dedicada 'Horário mundial' no carrossel da ilha expandida."""

    WIDTH = 420

    def __init__(self, open_settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.open_settings = open_settings
        self.set_size_request(self.WIDTH, -1)
        for side in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{side}")(18 if side in ("start", "end") else 14)

        head = Gtk.Box(spacing=8)
        head.pack_start(icon(GLOBE_ICON, 16), False, False, 0)
        self.title_lb = label("title")
        self.title_lb.set_text(_("Horário mundial"))
        head.pack_start(self.title_lb, False, False, 0)
        self.local_lb = label("dim small", 1.0)
        head.pack_end(self.local_lb, True, True, 0)
        self.pack_start(head, False, False, 0)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.pack_start(self.body, False, False, 0)

    def update(self, cfg, now=None):
        self.title_lb.set_text(_("Horário mundial"))
        local_now = (now or datetime.now()).astimezone()
        self.local_lb.set_text(clock_text(local_now, cfg["clock_24h"]))
        for c in self.body.get_children():
            self.body.remove(c)
        clocks = resolve_clocks(cfg["world_cities"], cfg["clock_24h"], local_now)[:MAX_PAGE_CITIES]
        if not clocks:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            box.set_margin_top(10)
            box.set_margin_bottom(6)
            lb = label("dim", 0.5)
            lb.set_text(_("Nenhuma cidade configurada."))
            box.pack_start(lb, False, False, 0)
            btn = pill_button(_("Configurar"), "preferences-system-symbolic",
                              self.open_settings, "water-snooze")
            btn.set_halign(Gtk.Align.CENTER)
            box.pack_start(btn, False, False, 0)
            self.body.pack_start(box, False, False, 0)
        else:
            for item in clocks:
                row = Gtk.Box(spacing=12)
                row.get_style_context().add_class("day")
                for side in ("top", "bottom", "start", "end"):
                    getattr(row, f"set_margin_{side}")(2)
                left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                left.set_valign(Gtk.Align.CENTER)
                city_lb = label("title")
                city_lb.set_text(item["name"])
                sub_lb = label("dim small")
                sub_lb.set_text(f"{item['subtitle']} ({item['zone']})")
                left.pack_start(city_lb, False, False, 0)
                left.pack_start(sub_lb, False, False, 0)

                time_lb = label("big-temp", 1.0)
                time_lb.set_valign(Gtk.Align.CENTER)
                time_lb.set_text(item["time"])

                row.pack_start(left, True, True, 6)
                row.pack_end(time_lb, False, False, 6)
                self.body.pack_start(row, False, False, 0)
        self.body.show_all()
