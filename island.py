#!/usr/bin/env python3
"""omarchy-island: "dynamic island" para Wayland (layer-shell) no lugar do relógio do painel.

Mostra hora, data, clima, horário mundial, agenda, água e mídia em todos os monitores.
"""
import json
import os
import socket
import sys
from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell
except (ValueError, ImportError):
    sys.exit("gtk-layer-shell não encontrado. Rode pelo run.sh ou instale "
             "gir1.2-gtklayershell-0.1")

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from pages import TRANSITION_MS, PagesMixin  # noqa: E402
from pointer import InputMixin, log  # noqa: E402
import i18n  # noqa: E402
from i18n import _  # noqa: E402
from config import Config, accent_tuple, build_css, rgba  # noqa: E402
from settings import Settings  # noqa: E402
from players import Players  # noqa: E402
from notifications import parse_ignore as parse_names  # noqa: E402
from spotify_web import SpotifyWeb  # noqa: E402
from notifications import NotificationWatcher  # noqa: E402
from views import Compact, Expanded, NotifPill, label  # noqa: E402
from water import Notifier, Water, play_sound  # noqa: E402
from water_view import DropIcon, WaterPage  # noqa: E402
from agenda import Agenda  # noqa: E402
from agenda_view import AgendaPage, MeetingPill  # noqa: E402
from world_clock import WorldClockPage  # noqa: E402
from weather import Weather  # noqa: E402
from widgets import accent_from_pixbuf  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
APP_ID = "io.github.mrlazarias.LinuxIsland"
PEEK_MS = 4000         # quanto tempo a pílula mostra a faixa nova
SHELL_JSON = os.path.join(GLib.get_user_config_dir(), "omarchy", "shell.json")


class Island(PagesMixin, InputMixin, Gtk.Window):
    def __init__(self, app, cfg, monitor=None):
        super().__init__(title="linux-island")
        self.app = app
        self.cfg = cfg
        self.monitor = monitor
        self._art_accent = app.last_art_accent
        self._setup_surface()
        self.expanded = False
        self.pinned = False
        self.hovered = False
        self._timers = {}
        self._resize_tick = None
        self._last_click = None
        self._closed_by_click = False
        self._minute = None
        self._last_scroll = None
        self._scroll_acc = 0.0
        self._last_discrete = None
        self._press = None
        self._hscroll = 0.0

        # serviços compartilhados no App (sincronizados entre todos os monitores)
        self.player = app.player
        self.water = app.water
        self.agenda = app.agenda
        self.weather = app.weather
        self.web = app.web
        self._notif_queue, self._notif_current = [], None

        self._build()
        self._apply()
        self.show_all()
        self._sync_page_dots()

        # hidrata estado atual se o monitor foi conectado depois
        if app.last_fc:
            self._on_weather(app.last_fc)
        if app.last_art_pb is not None:
            self.compact.art.set_source(app.last_art_pb)
            self.full.art.set_source(app.last_art_pb)
            self._apply_accent()
        if self.player.track:
            self._on_track(self.player.track, initial=True)
        if app.last_pb:
            self._on_playback(app.last_pb)
        if self.player.volume is not None:
            self.full.set_volume(self.player.volume)

    # --- superfície layer-shell ----------------------------------------
    def _setup_surface(self):
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "linux-island")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        if self.monitor is not None:
            GtkLayerShell.set_monitor(self, self.monitor)
        # -1: ignora a zona exclusiva do painel e fica por cima dele, no lugar do relógio
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)

        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.get_style_context().add_class("island-window")

    # --- configuração ---------------------------------------------------
    def _apply(self, key=None):
        """Aplica a configuração inteira (key=None) ou só o que mudou."""
        cfg = self.cfg
        look = ("bg_color", "text_color", "border", "radius_expanded")
        if key is None or key in look:
            fg = rgba(cfg["text_color"])
            for bar in (self.full.progress, self.full.vol_bar):
                bar.fg = (fg.red, fg.green, fg.blue)
                bar.queue_draw()
            self.water_page.set_fg((fg.red, fg.green, fg.blue))
        if key is None or key in ("accent_auto", "accent_color"):
            self._apply_accent()
        if key is None or key in ("clock_24h", "world_clock_mode", "world_cities"):
            self._minute = None
            self._tick_clock()
            self.world_page.update(cfg)
            self._sync_page_dots()
        if key is None or key in ("show_date", "show_weather"):
            self.compact.set_visibility(cfg["show_date"], cfg["show_weather"])
        if key is None or (key or "").startswith("agenda_") or key in (
                "week_start", "birth_year", "life_expectancy"):
            self._on_agenda_change()
        if key is None or (key or "").startswith("water_"):
            self._on_water_change()
        if key is None or key == "margin_top":
            self._update_top_margin()
        self._follow_size()

    def _update_top_margin(self):
        top = self.cfg["margin_top"]
        if self.expanded:
            top += Compact.HEIGHT + 4
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, top)

    def _apply_accent(self):
        if self.cfg["accent_auto"] and self._art_accent:
            accent = self._art_accent
        elif self.cfg["accent_auto"]:
            accent = accent_from_pixbuf(None)
        else:
            accent = accent_tuple(self.cfg["accent_color"])
        for w in (self.compact.eq, self.full.eq, self.full.progress, self.full.vol_bar):
            w.accent = accent
            w.queue_draw()

    # --- layout ---------------------------------------------------------
    def _build(self):
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
                        | Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.connect("button-release-event", self._release)
        self.connect("scroll-event", self._scroll)
        self.connect("enter-notify-event", self._enter)
        self.connect("leave-notify-event", self._leave)
        self.connect("button-press-event", self._click)

        self.shell = Gtk.Box()
        self.shell.get_style_context().add_class("island")
        self.add(self.shell)

        self.stack = Gtk.Stack()
        self.stack.set_homogeneous(False)
        self.stack.set_interpolate_size(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(TRANSITION_MS)
        self.shell.pack_start(self.stack, True, True, 0)

        self.compact = Compact()
        self.full = Expanded(self.player)
        self.world_page = WorldClockPage(lambda: self.app.open_settings("info"))
        self.water_page = WaterPage(self.water)
        self.agenda_page = AgendaPage(self.agenda, lambda: self.app.open_settings("agenda"))
        self.stack.add_named(self.compact, "compact")
        self.stack.add_named(self._build_pages(), "expanded")
        self.stack.set_visible_child_name("compact")

        # alerta de água no miolo da pílula
        alert = Gtk.Box(spacing=8)
        alert.pack_start(DropIcon(15), False, False, 0)
        msg = label("clock")
        msg.set_text(_("Hora de beber água"))
        self.alert_amount = label("dim")
        alert.pack_start(msg, False, False, 0)
        alert.pack_start(self.alert_amount, False, False, 0)
        self.compact.middle.add_named(alert, "water")
        self.meeting_pill = MeetingPill()
        self.compact.middle.add_named(self.meeting_pill, "meeting")
        self.notif_pill = NotifPill()
        self.compact.middle.add_named(self.notif_pill, "notif")

    # --- tamanho --------------------------------------------------------
    def _follow_size(self):
        """Janelas GTK3 não encolhem sozinhas: acompanha as animações de tamanho."""
        if self._resize_tick is not None:
            self.remove_tick_callback(self._resize_tick)
        start = GLib.get_monotonic_time()

        def step(_w, _clock):
            self.resize(1, 1)
            if GLib.get_monotonic_time() - start > (TRANSITION_MS + 120) * 1000:
                self._resize_tick = None
                if not self.expanded:
                    w = self.get_allocated_width()
                    if w > 40:
                        self.app.schedule_spacer_sync(w)
                return False
            return True

        self._resize_tick = self.add_tick_callback(step)

    def set_expanded(self, value):
        if value == self.expanded:
            return
        self.expanded = value
        if not value and getattr(self, "pinned", False):
            self.set_pinned(False)
        log("expanded", value)
        self._update_top_margin()
        ctx = self.shell.get_style_context()
        (ctx.add_class if value else ctx.remove_class)("expanded")
        self.stack.set_visible_child_name("expanded" if value else "compact")
        if value:  # ao expandir, a pílula volta ao relógio para quando fechar
            self._cancel("track_peek")
            self._cancel("notif_peek")
            self._notif_queue, self._notif_current = [], None
            self._refresh_middle()
            if self._alert_page() != "home":
                self.set_page(self._alert_page())
            elif self.pages.get_visible_child_name() == "agenda":
                self.agenda_page.update(self.cfg)
        else:
            self.set_page(self._alert_page())
        self._follow_size()
        if value:
            self._tick_music()

    def _peek(self):
        """Faixa nova: a pílula se estica na horizontal com título · artista e volta."""
        if self.expanded or not self.cfg["peek_on_track"]:
            return
        self._later("track_peek", PEEK_MS, self._refresh_middle)
        self._refresh_middle()

    # --- relógio e clima ------------------------------------------------
    def _tick_clock(self):
        now = datetime.now()
        if now.minute != self._minute:
            self._minute = now.minute
            self.compact.set_clock(now, self.cfg["clock_24h"])
            self.full.set_clock(now, self.cfg["clock_24h"])
            self.full.set_world_clock(self.cfg, now)
            if self.pages.get_visible_child_name() == "world":
                self.world_page.update(self.cfg, now)
            if self.agenda.alert:  # atualiza a contagem regressiva da reunião
                self._refresh_middle()
            self._on_agenda_change()
            self._follow_size()
        return True

    def _on_weather(self, fc):
        self.compact.set_weather(fc)
        self.full.set_weather(fc)
        self._follow_size()

    # --- Spotify --------------------------------------------------------
    def _on_presence(self, present):
        if not present:
            self._on_track(None)
            self._on_status(False)

    def _on_track(self, track, initial=False):
        prev = self.full.title.get_text() if self.full.music_rev.get_reveal_child() else ""
        self.full.set_track(track)
        if track:
            self.compact.set_track_text(track.title, track.artist)
        self.compact.set_music(track is not None, self.player.playing)
        self._follow_size()
        if not initial and track and prev and prev != track.title:
            self._peek()

    def _on_status(self, playing):
        self.compact.set_music(self.player.track is not None, playing)
        self.full.set_playing(playing)
        self._follow_size()

    def _on_player_switch(self, p):
        if p is None or not p.is_spotify:
            self.full.set_playback(None)
            self.compact.set_remote_device(None)
        self._follow_size()

    def _on_playback(self, pb):
        if not self.player.is_spotify:
            pb = None
        self.full.set_playback(pb)
        remote = pb is not None and pb.is_playing and not self._is_this_computer(pb)
        self.compact.set_remote_device(pb.device_icon if remote else None)
        self._follow_size()

    @staticmethod
    def _is_this_computer(pb):
        return pb.device_type == "computer" and pb.device.lower() == socket.gethostname().lower()

    def _on_art(self, pb, accent):
        self.compact.art.set_source(pb)
        self.full.art.set_source(pb)
        self._art_accent = accent
        self._apply_accent()

    def _tick_music(self):
        p = self.player
        if p.track and self.expanded:
            self.full.set_position(p.position(), p.track.length)
        return True


class App(Gtk.Application):
    """Instância única: gerencia uma janela Island por monitor conectado."""

    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.cfg = None
        self.islands = {}  # Gdk.Monitor -> Island
        self.settings = None
        self.dyn_css = None
        self._theme_mon = None
        self._sync_counter = 0
        self._spacer_timer = None
        self._last_spacer_size = None

        self.last_fc = None
        self.last_pb = None
        self.last_art_pb = None
        self.last_art_accent = None
        self.web_status = (_("Não conectado"), False)

        self.add_main_option("settings", ord("s"), GLib.OptionFlags.NONE,
                             GLib.OptionArg.NONE, _("Abre as configurações"), None)
        self.add_main_option("city", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             _("Cidade do clima só nesta execução"), "CIDADE")
        self.add_main_option("margin", 0, GLib.OptionFlags.NONE, GLib.OptionArg.INT,
                             _("Distância do topo só nesta execução"), "PX")
        self.add_main_option("reload-theme", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             _("Recarrega o tema do Omarchy"), None)
        self.add_main_option("restart", ord("r"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             _("Reinicia a ilha"), None)
        self.notifier = Notifier(self._notif_action)

    @property
    def island(self):
        """Retorna a primeira Island ativa (compatibilidade)."""
        return next(iter(self.islands.values()), None)

    def notify_water(self, consumed, goal):
        self.notifier.notify(consumed, goal)

    def withdraw_water(self):
        self.notifier.close()

    def _notif_action(self, action):
        if self.cfg is None:
            return
        if action == "drink":
            self.water.drink()
        elif action == "snooze":
            self.water.snooze()

    # --- inicialização e monitores --------------------------------------
    def _init_services(self, cfg):
        self.cfg = cfg
        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(HERE, "style.css"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.dyn_css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.dyn_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.dyn_css.load_from_data(build_css(cfg).encode())

        self.player = Players(self._on_presence, self._on_track, self._on_status,
                              self._on_art, self._on_volume, on_switch=self._on_player_switch,
                              ignored=self._player_ignored)
        self.water = Water(cfg, self._on_water_change, self._on_water_alert)
        self.agenda = Agenda(cfg, self._on_agenda_change, self._on_agenda_alert,
                             self._on_agenda_status, play_sound)
        self.weather = Weather(self._on_weather, cfg["city"], cfg["units"])
        self.web_status = ("Conectado", True)
        self.web = SpotifyWeb(cfg["spotify_client_id"], self._on_playback, self._on_web_status)
        if not self.web.connected:
            self.web_status = (_("Não conectado"), False)
        self.notifications = NotificationWatcher(self._on_notification)

        cfg.connect(self._on_cfg_change)
        self._watch_omarchy_theme()

        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            self._add_monitor(display.get_monitor(i))
        display.connect("monitor-added", lambda _d, m: self._add_monitor(m))
        display.connect("monitor-removed", lambda _d, m: self._remove_monitor(m))

        GLib.timeout_add(250, self._tick_music)
        GLib.timeout_add(1000, self._tick_clock)

    def _add_monitor(self, monitor):
        if monitor in self.islands:
            return
        isl = Island(self, self.cfg, monitor=monitor)
        self.islands[monitor] = isl
        self.add_window(isl)

    def _remove_monitor(self, monitor):
        isl = self.islands.pop(monitor, None)
        if isl is not None:
            isl.destroy()

    def _for_each(self, fn):
        for isl in list(self.islands.values()):
            fn(isl)

    # --- eventos globais distribuídos para todas as ilhas ----------------
    def _on_cfg_change(self, key=None):
        cfg = self.cfg
        if key is None or key in ("bg_color", "text_color", "border", "radius_expanded",
                                  "accent_color"):
            self.dyn_css.load_from_data(build_css(cfg).encode())
        if key == "player_ignore":
            self.player.refresh_choice()
        if key in ("city", "units"):
            self.weather.configure(cfg["city"], cfg["units"])
        if key == "spotify_client_id":
            self.web.set_client_id(cfg["spotify_client_id"])
        if key in ("agenda_enabled", "agenda_days"):
            self.agenda.refresh()
        if (key or "").startswith("agenda_"):
            self.agenda.tick()
        if (key or "").startswith("water_"):
            self.water.tick()
        self._for_each(lambda isl: isl._apply(key))

    def _watch_omarchy_theme(self):
        gen_path = os.path.join(GLib.get_user_state_dir(), "omarchy", "current", "theme.generation")
        if not os.path.exists(os.path.dirname(gen_path)):
            return
        try:
            self._theme_mon = Gio.File.new_for_path(gen_path).monitor_file(
                Gio.FileMonitorFlags.NONE, None)
            self._theme_mon.connect("changed", self._on_omarchy_theme_changed)
        except GLib.Error as e:
            log("theme monitor erro:", e.message)

    def _on_omarchy_theme_changed(self, _mon, _file, _other, event):
        if event in (Gio.FileMonitorEvent.CHANGED,
                     Gio.FileMonitorEvent.CREATED,
                     Gio.FileMonitorEvent.CHANGES_DONE_HINT):
            GLib.timeout_add(150, self._reload_omarchy_theme)

    def _reload_omarchy_theme(self):
        self.cfg.sync_omarchy_theme(notify=True)
        self._on_cfg_change()
        return False

    def _player_ignored(self, p):
        names = parse_names(self.cfg["player_ignore"])
        ident = (p.identity or "").lower()
        return any(n == p.short or n in ident for n in names)

    def _on_presence(self, present):
        self._for_each(lambda isl: isl._on_presence(present))

    def _on_track(self, track):
        self.web.kick()
        self._for_each(lambda isl: isl._on_track(track))

    def _on_status(self, playing):
        self.web.kick()
        self._for_each(lambda isl: isl._on_status(playing))

    def _on_player_switch(self, p):
        log("player ativo", p and p.identity)
        if p is not None and p.is_spotify:
            self.web.kick()
        self._for_each(lambda isl: isl._on_player_switch(p))

    def _on_playback(self, pb):
        self.last_pb = pb
        self._for_each(lambda isl: isl._on_playback(pb))

    def _on_web_status(self, text, ok):
        self.web_status = (text, ok)
        if self.settings:
            self.settings.set_spotify_status(text, ok)

    def _on_art(self, path):
        pb = None
        if path:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file(path)
            except GLib.Error as e:
                print(f"[island] capa inválida: {e.message}")
        self.last_art_pb = pb
        self.last_art_accent = accent_from_pixbuf(pb) if pb else None
        self._for_each(lambda isl: isl._on_art(pb, self.last_art_accent))

    def _on_volume(self, v, from_user=False):
        self._for_each(lambda isl: isl._on_volume(v, from_user=from_user))

    def _on_weather(self, fc):
        self.last_fc = fc
        self._for_each(lambda isl: isl._on_weather(fc))

    def _on_water_change(self):
        self._for_each(lambda isl: isl._on_water_change())

    def _on_water_alert(self, alerting):
        self._for_each(lambda isl: isl._on_water_alert(alerting))
        if alerting and self.cfg["water_sound"]:
            play_sound(self.cfg["water_sound_name"], self.cfg["water_sound_volume"])
        if alerting and self.cfg["water_notify"]:
            self.notify_water(self.water.consumed, self.cfg["water_goal_ml"])
        elif not alerting:
            self.withdraw_water()

    def _on_agenda_change(self):
        self._for_each(lambda isl: isl._on_agenda_change())

    def _on_agenda_alert(self, ev):
        self._for_each(lambda isl: isl._on_agenda_alert(ev))

    def _on_agenda_status(self, text, ok):
        self._for_each(lambda isl: isl._on_agenda_status(text, ok))

    def _on_notification(self, n):
        self._for_each(lambda isl: isl._on_notification(n))

    def _tick_music(self):
        p = self.player
        if p.track and p.playing:
            self._sync_counter += 1
            if self._sync_counter % 12 == 0:
                p.sync_position()
        self._for_each(lambda isl: isl._tick_music())
        return True

    def _tick_clock(self):
        self._for_each(lambda isl: isl._tick_clock())
        return True

    # --- ajuste dinâmico do espaçador na barra do Omarchy ----------------
    def schedule_spacer_sync(self, compact_width):
        if not self.cfg or not self.cfg["bar_spacer_sync"]:
            return
        target = max(80, int(compact_width) + 2)
        if self._last_spacer_size is not None and abs(target - self._last_spacer_size) < 4:
            return
        if self._spacer_timer is not None:
            GLib.source_remove(self._spacer_timer)
        self._spacer_timer = GLib.timeout_add(220, self._apply_spacer_size, target)

    def _apply_spacer_size(self, target):
        self._spacer_timer = None
        if not os.path.exists(SHELL_JSON):
            return False
        try:
            with open(SHELL_JSON) as f:
                data = json.load(f)
            center = data.get("bar", {}).get("layout", {}).get("center", [])
            changed = False
            for item in center:
                if isinstance(item, dict) and item.get("id") == "omarchy.spacer":
                    if item.get("size") != target:
                        item["size"] = target
                        changed = True
            if changed:
                tmp = SHELL_JSON + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                os.replace(tmp, SHELL_JSON)
            self._last_spacer_size = target
        except (OSError, ValueError) as e:
            log("spacer sync erro:", e)
        return False

    def do_command_line(self, cmdline):
        opts = cmdline.get_options_dict().end().unpack()
        log("command line", opts, "remota" if cmdline.get_is_remote() else "local")
        if self.cfg is None:
            margin = opts.get("margin")
            cfg = Config({"city": opts.get("city"),
                          "margin_top": margin if margin is not None and 0 <= margin <= 200
                          else None})
            self._init_services(cfg)
        elif opts.get("restart"):
            GLib.idle_add(self.restart)
            return 0
        elif opts.get("reload-theme"):
            self._reload_omarchy_theme()
            return 0
        if opts.get("settings"):
            self.open_settings()
        return 0

    def apply_all(self):
        """Força atualização imediata de tema, clima, layout e espaçador."""
        if self.cfg["omarchy_theme"]:
            self.cfg.sync_omarchy_theme(notify=True)
        self._on_cfg_change(None)
        self.weather.configure(self.cfg["city"], self.cfg["units"])
        self.agenda.refresh()
        self.water.tick()

    def restart(self):
        """Reabre a ilha (ex.: para trocar o idioma). O ambiente do run.sh é herdado."""
        log("reiniciando")
        if self.cfg:
            self.cfg.flush()
        sys.stdout.flush()
        os.execv(sys.executable, [sys.executable, os.path.join(HERE, "island.py")])

    def open_settings(self, page=None):
        log("open_settings", self.settings)
        if self.settings is None:
            self.settings = Settings(self.cfg, self, self.web, self.water, self.agenda)
            self.settings.set_spotify_status(*self.web_status)
            self.settings.set_agenda_status(*self.agenda.status)
            self.settings.connect("destroy", lambda *_a: setattr(self, "settings", None))
        if page:
            self.settings.show_page(page)
        self.settings.present()


def main():
    i18n.setup(Config()["language"])
    app = App()
    for sig in (2, 15):  # SIGINT, SIGTERM
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: app.quit() or False)
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
