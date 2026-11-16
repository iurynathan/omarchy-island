"""Páginas da ilha expandida e prioridade do miolo da pílula (inclui o lembrete de água).

Mixin da janela Island; usa self.full, self.water, self.water_page, self.compact,
self.shell, self.cfg, self.app, self._timers e self._follow_size dela.
"""
from datetime import datetime

from gi.repository import Gio, Gtk

from i18n import _
from notifications import OWN_APP, parse_ignore

from pointer import log
from views import icon
from water_view import DropIcon

TRANSITION_MS = 320
PAGES = ("home", "world", "agenda", "water")  # páginas da ilha expandida, na ordem das abas
TAB_DEFS = {  # página -> (ícone, rótulo)
    "home": ("go-home-symbolic", "Início"),
    "world": ("preferences-system-time-symbolic", "Mundo"),
    "agenda": ("x-office-calendar-symbolic", "Agenda"),
    "water": (None, "Água"),
}


class PagesMixin:
    def _active_pages(self):
        pages = ["home"]
        if self.cfg["world_clock_mode"] in ("page", "both"):
            pages.append("world")
        pages.extend(["agenda", "water"])
        return pages

    def _build_pages(self):
        """Ilha expandida: abas fixas no topo (não se movem quando a altura muda) + páginas."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        bar = Gtk.Box(spacing=4)
        bar.get_style_context().add_class("tabbar")
        for side in ("top", "start", "end"):
            getattr(bar, f"set_margin_{side}")(12 if side == "top" else 14)
        self.tabs = {}
        for name in PAGES:
            icon_name, text = TAB_DEFS[name]
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.set_can_focus(False)
            btn.set_tooltip_text(_(text))
            btn.get_style_context().add_class("tab")
            inner = Gtk.Box(spacing=6)
            inner.pack_start(icon(icon_name, 14) if icon_name else DropIcon(14), False, False, 0)
            lb = Gtk.Label(label=_(text))
            rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_RIGHT,
                               transition_duration=180)
            rev.add(lb)
            inner.pack_start(rev, False, False, 0)
            btn.add(inner)
            btn.connect("clicked", lambda _b, n=name: self.set_page(n))
            bar.pack_start(btn, False, False, 0)
            self.tabs[name] = (btn, rev)

        self.pin_btn = Gtk.ToggleButton()
        self.pin_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.pin_btn.set_can_focus(False)
        self.pin_btn.add(icon("view-pin-symbolic", 13))
        self.pin_btn.get_style_context().add_class("tab")
        self.pin_btn.get_style_context().add_class("pin")
        self.pin_btn.connect("toggled", self._on_pin_toggled)
        self._on_pin_toggled(self.pin_btn)

        prev_btn = Gtk.Button()
        prev_btn.add(icon("go-previous-symbolic", 13))
        prev_btn.set_relief(Gtk.ReliefStyle.NONE)
        prev_btn.set_can_focus(False)
        prev_btn.set_tooltip_text(_("Página anterior"))
        prev_btn.get_style_context().add_class("tab")
        prev_btn.connect("clicked", lambda *_a: self.turn_page(-1, wrap=True))

        next_btn = Gtk.Button()
        next_btn.add(icon("go-next-symbolic", 13))
        next_btn.set_relief(Gtk.ReliefStyle.NONE)
        next_btn.set_can_focus(False)
        next_btn.set_tooltip_text(_("Próxima página"))
        next_btn.get_style_context().add_class("tab")
        next_btn.connect("clicked", lambda *_a: self.turn_page(1, wrap=True))

        cfg_btn = Gtk.Button()
        cfg_btn.add(icon("emblem-system-symbolic", 13))
        cfg_btn.set_relief(Gtk.ReliefStyle.NONE)
        cfg_btn.set_can_focus(False)
        cfg_btn.set_tooltip_text(_("Configurações…"))
        cfg_btn.get_style_context().add_class("tab")
        cfg_btn.connect("clicked", lambda *_a: self.app.open_settings())

        bar.pack_end(cfg_btn, False, False, 0)
        bar.pack_end(self.pin_btn, False, False, 0)
        bar.pack_end(next_btn, False, False, 0)
        bar.pack_end(prev_btn, False, False, 0)
        box.pack_start(bar, False, False, 0)

        self.pages = Gtk.Stack()
        self.pages.set_homogeneous(False)
        self.pages.set_interpolate_size(True)
        self.pages.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.pages.set_transition_duration(TRANSITION_MS)
        self.pages.add_named(self.full, "home")
        self.pages.add_named(self.world_page, "world")
        self.pages.add_named(self.agenda_page, "agenda")
        self.pages.add_named(self.water_page, "water")
        box.pack_start(self.pages, False, False, 0)
        self._mark_tab("home")
        return box

    # --- fixar aberta -----------------------------------------------------
    def _on_pin_toggled(self, btn):
        self.pinned = btn.get_active()
        btn.set_tooltip_text(_("Desafixar") if self.pinned else _("Fixar aberta"))
        if self.pinned:
            self._cancel("collapse")
        else:
            self._later("hover", 30, self._recheck_hover)

    def set_pinned(self, value):
        if self.pin_btn.get_active() != value:
            self.pin_btn.set_active(value)

    def _sync_page_dots(self):
        active = set(self._active_pages())
        for name, (btn, _rev) in self.tabs.items():
            btn.set_visible(name in active)
            btn.set_no_show_all(name not in active)
        cur = self.pages.get_visible_child_name()
        if cur not in active:
            self.set_page("home")

    def _mark_tab(self, name):
        for n, (btn, rev) in self.tabs.items():
            ctx = btn.get_style_context()
            (ctx.add_class if n == name else ctx.remove_class)("active")
            rev.set_reveal_child(n == name)

    def set_page(self, name):
        if name == self.pages.get_visible_child_name():
            return
        if name == "world":
            self.world_page.update(self.cfg)
        elif name == "water":
            self.water_page.update(self.cfg)
        elif name == "agenda":
            self.agenda_page.update(self.cfg)
        log("page", name)
        self.pages.set_visible_child_name(name)
        self._mark_tab(name)
        self._follow_size()

    def turn_page(self, step, wrap=False):
        """step=+1 próxima página, -1 anterior. wrap=True cicla nas extremidades."""
        active = self._active_pages()
        cur = self.pages.get_visible_child_name()
        try:
            idx = active.index(cur)
        except ValueError:
            idx = 0
        nxt = idx + step
        if wrap and active:
            nxt %= len(active)
        if 0 <= nxt < len(active):
            self.set_page(active[nxt])

    def _alert_page(self):
        """Página do alerta mais importante (reunião > água), ou a inicial."""
        if self.agenda.alert:
            return "agenda"
        return "water" if self.water.alerting else "home"

    def _refresh_middle(self):
        """Miolo da pílula: notificação > faixa nova > reunião > água > relógio."""
        if "notif_peek" in self._timers:
            name = "notif"
        elif "track_peek" in self._timers:
            name = "track"
        elif self.agenda.alert:
            self.meeting_pill.update(self.agenda.alert, datetime.now().astimezone())
            name = "meeting"
        elif self.water.alerting:
            name = "water"
        else:
            name = "info"
        self.compact.middle.set_visible_child_name(name)
        self._follow_size()

    # --- notificações de outros apps ----------------------------------------
    def _on_notification(self, n):
        cfg = self.cfg
        if (not cfg["notif_enabled"] or cfg["notif_dnd"] or self.expanded
                or n.app.lower() == OWN_APP
                or n.app.lower() in parse_ignore(cfg["notif_ignore"])):
            return
        log("notificação", n.app)
        last = self._notif_queue[-1] if self._notif_queue else self._notif_current
        if last and (last.app, last.summary, last.body) == (n.app, n.summary, n.body):
            return  # repetida
        self._notif_queue = (self._notif_queue + [n])[-5:]
        if "notif_peek" not in self._timers:
            self._show_next_notification()

    def _show_next_notification(self):
        if not self._notif_queue or self.expanded:
            self._notif_queue = []
            self._notif_current = None
            self._refresh_middle()
            return
        self._notif_current = self._notif_queue.pop(0)
        self.notif_pill.update(self._notif_current, self.cfg["notif_show_body"])
        self._later("notif_peek", self.cfg["notif_duration_s"] * 1000,
                    self._show_next_notification)
        self._refresh_middle()

    def open_notification_app(self):
        """Clique na pílula durante uma notificação: abre o app, se der para saber qual."""
        n = self._notif_current if "notif_peek" in self._timers else None
        if not n or not n.desktop_entry:
            return False
        try:
            info = Gio.DesktopAppInfo.new(n.desktop_entry + ".desktop")
        except TypeError:
            info = None
        if info is None:
            return False
        info.launch([], None)
        self._cancel("notif_peek")
        self._show_next_notification()
        return True

    # --- agenda ---------------------------------------------------------
    def _on_agenda_change(self):
        if self.pages.get_visible_child_name() == "agenda":
            self.agenda_page.update(self.cfg)
            self._follow_size()

    def _on_agenda_alert(self, ev):
        log("meeting alert", ev and ev["title"])
        ctx = self.shell.get_style_context()
        (ctx.add_class if ev else ctx.remove_class)("meeting-alert")
        self._refresh_middle()
        self._on_agenda_change()
        if self.expanded and not ev and self.pages.get_visible_child_name() == "agenda":
            return  # o usuário está olhando a agenda: não troca de página
        if not self.expanded:
            self.set_page(self._alert_page())

    def _on_agenda_status(self, text, ok):
        self._on_agenda_change()
        if self.app.settings:
            self.app.settings.set_agenda_status(text, ok)

    # --- água -----------------------------------------------------------
    def _on_water_change(self):
        goal = self.cfg["water_goal_ml"]
        self.alert_amount.set_text(f"{self.water.consumed}/{goal} ml")
        self.water_page.update(self.cfg)
        if self.app.settings:
            self.app.settings._water_refresh()
        self._follow_size()

    def _on_water_alert(self, alerting):
        """Só a parte visual: som e notificação são disparados uma vez pelo App."""
        log("water alert", alerting)
        ctx = self.shell.get_style_context()
        (ctx.add_class if alerting else ctx.remove_class)("water-alert")
        self._on_water_change()
        self._refresh_middle()

