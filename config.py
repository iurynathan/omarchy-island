"""Configurações persistentes em ~/.config/linux-island/config.json."""
import json
import os
import re

from gi.repository import Gdk, GLib

PATH = os.path.join(GLib.get_user_config_dir(), "linux-island", "config.json")
OMARCHY_COLORS = os.path.join(GLib.get_user_state_dir(), "omarchy", "current", "theme", "colors.toml")


def _hex_to_rgb_tuple(value):
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", value.strip())
    if not m:
        return None
    h = m.group(1)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def read_omarchy_colors():
    """Lê background, foreground e accent do colors.toml do tema ativo do Omarchy."""
    try:
        with open(OMARCHY_COLORS) as f:
            content = f.read()
    except OSError:
        return None
    found = {}
    for line in content.splitlines():
        m = re.match(r'^\s*(background|foreground|accent)\s*=\s*"([^"]+)"', line)
        if m:
            rgb = _hex_to_rgb_tuple(m.group(2))
            if rgb:
                found[m.group(1)] = rgb
    out = {}
    if "background" in found:
        r, g, b = found["background"]
        out["bg_color"] = f"rgba({r},{g},{b},1)"
    if "foreground" in found:
        r, g, b = found["foreground"]
        out["text_color"] = f"rgb({r},{g},{b})"
    if "accent" in found:
        r, g, b = found["accent"]
        out["accent_color"] = f"rgb({r},{g},{b})"
    return out or None

# chave -> (padrão, validador). Validadores recebem o valor lido do JSON e
# devolvem True se ele for aceitável; senão vale o padrão.
_is_bool = lambda v: isinstance(v, bool)  # noqa: E731


def _is_color(v):
    return isinstance(v, str) and Gdk.RGBA().parse(v)


def _int_range(lo, hi):
    return lambda v: isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _choice(*opts):
    return lambda v: v in opts


SCHEMA = {
    # aparência
    "omarchy_theme": (True, _is_bool),
    "bg_color": ("rgba(0,0,0,1)", _is_color),
    "text_color": ("rgb(255,255,255)", _is_color),
    "accent_auto": (True, _is_bool),          # cor de destaque tirada da capa
    "accent_color": ("rgb(30,215,96)", _is_color),
    "border": (True, _is_bool),
    "radius_expanded": (30, _int_range(8, 48)),
    # relógio
    "clock_24h": (True, _is_bool),
    "show_date": (True, _is_bool),
    "world_clock_mode": ("both", _choice("both", "page", "home", "off")),
    "world_cities": (
        "Maceió|America/Maceio, London|Europe/London, Los Angeles|America/Los_Angeles",
        lambda v: isinstance(v, str) and len(v) <= 1000,
    ),
    # clima
    "city": ("", lambda v: isinstance(v, str) and len(v) <= 100),
    "units": ("celsius", _choice("celsius", "fahrenheit")),
    "show_weather": (True, _is_bool),
    # Spotify Web API (playlist e dispositivo); vazio = desligado
    "spotify_client_id": ("", lambda v: isinstance(v, str)
                          and (v == "" or re.fullmatch(r"[0-9a-fA-F]{32}", v) is not None)),
    # lembrete de água
    "water_enabled": (True, _is_bool),
    "water_goal_ml": (2000, _int_range(250, 8000)),
    "water_cup_ml": (250, _int_range(50, 1500)),
    "water_interval_min": (60, _int_range(5, 360)),
    "water_start_h": (8, _int_range(0, 23)),
    "water_end_h": (22, _int_range(1, 24)),
    "water_snooze_min": (10, _int_range(1, 120)),
    "water_notify": (False, _is_bool),
    "water_sound": (True, _is_bool),
    "water_sound_name": ("message-new-instant", _choice(
        "message-new-instant", "complete", "bell", "dialog-information",
        "window-attention", "alarm-clock-elapsed")),
    "water_sound_volume": (70, _int_range(0, 100)),
    # agenda (Google Calendar, agenda principal)
    "agenda_enabled": (True, _is_bool),
    "agenda_alert": (True, _is_bool),
    "agenda_lead_min": (10, _int_range(0, 60)),
    "agenda_days": (3, _int_range(1, 7)),
    "agenda_sound": (True, _is_bool),
    "agenda_sound_name": ("bell", _choice(
        "message-new-instant", "complete", "bell", "dialog-information",
        "window-attention", "alarm-clock-elapsed")),
    "agenda_sound_volume": (70, _int_range(0, 100)),
    # notificações de outros apps na pílula
    "notif_enabled": (False, _is_bool),
    "notif_dnd": (False, _is_bool),
    "notif_duration_s": (5, _int_range(2, 15)),
    "notif_show_body": (True, _is_bool),
    "notif_ignore": ("Spotify", lambda v: isinstance(v, str) and len(v) <= 500),
    # idioma da interface ("auto" segue o sistema)
    "language": ("auto", _choice("auto", "pt", "en", "es")),
    # players de mídia a ignorar (nomes separados por vírgula)
    "player_ignore": ("", lambda v: isinstance(v, str) and len(v) <= 300),
    # comportamento
    "hover_expand": (True, _is_bool),
    "peek_on_track": (True, _is_bool),
    "scroll_volume": (True, _is_bool),
    "hover_delay_ms": (120, _int_range(0, 2000)),
    "margin_top": (0, _int_range(0, 200)),
}


class Config:
    def __init__(self, overrides=None):
        self._values = {k: d for k, (d, _) in SCHEMA.items()}
        self._listeners = []
        self._save_id = None
        self._load()
        # overrides da linha de comando valem só para esta execução
        self._overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
        self.sync_omarchy_theme(notify=False)

    def sync_omarchy_theme(self, notify=False):
        if not self["omarchy_theme"]:
            return
        colors = read_omarchy_colors()
        if not colors:
            return
        for key, value in colors.items():
            if notify:
                self.set(key, value)
            else:
                self._values[key] = value

    def _load(self):
        try:
            with open(PATH) as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            print(f"[island] config inválida, usando padrões: {e}")
            return
        if not isinstance(data, dict):
            return
        for key, value in data.items():
            if key in SCHEMA and SCHEMA[key][1](value):
                self._values[key] = value

    def __getitem__(self, key):
        return self._overrides.get(key, self._values[key])

    def set(self, key, value):
        if key not in SCHEMA or not SCHEMA[key][1](value):
            raise ValueError(f"valor inválido para {key}: {value!r}")
        self._overrides.pop(key, None)  # mexeu na UI: vale o que foi escolhido
        if self._values[key] == value:
            return
        self._values[key] = value
        self._schedule_save()
        for fn in self._listeners:
            fn(key)

    def reset(self):
        for key, (default, _) in SCHEMA.items():
            self.set(key, default)

    def connect(self, fn):
        self._listeners.append(fn)

    def disconnect(self, fn):
        if fn in self._listeners:
            self._listeners.remove(fn)

    def _schedule_save(self):
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(400, self._save)

    def _save(self):
        self._save_id = None
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        tmp = PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._values, f, indent=2, ensure_ascii=False)
        os.replace(tmp, PATH)
        return False


def rgba(spec):
    c = Gdk.RGBA()
    c.parse(spec)
    return c


def css_color(c, alpha=None):
    a = c.alpha if alpha is None else c.alpha * alpha
    return f"rgba({round(c.red * 255)},{round(c.green * 255)},{round(c.blue * 255)},{a:.3f})"


def build_css(cfg):
    """CSS gerado a partir da configuração (cores e arredondamento)."""
    bg, fg = rgba(cfg["bg_color"]), rgba(cfg["text_color"])
    border = f"1px solid {css_color(fg, 0.07)}" if cfg["border"] else "1px solid transparent"
    return f"""
.island {{ background-color: {css_color(bg)}; color: {css_color(fg)}; border: none; border-radius: 0px; }}
.island.expanded {{ border-radius: {cfg['radius_expanded']}px; border: {border}; }}
.island .dim, .island .artist {{ color: {css_color(fg, 0.6)}; }}
.island .time {{ color: {css_color(fg, 0.55)}; }}
.island .control {{ color: {css_color(fg)}; }}
.island .control:hover {{ background-color: {css_color(fg, 0.12)}; }}
.island .control:active {{ background-color: {css_color(fg, 0.22)}; }}
.island .day {{ background-color: {css_color(fg, 0.05)}; }}
.island separator {{ background-color: {css_color(fg, 0.1)}; }}
.island.water-alert {{ border: 1px solid rgb(41,158,245); border-radius: 12px; }}
.island.meeting-alert {{ border: 1px solid rgb(167,139,250); border-radius: 12px; }}
.island button.agenda-row {{
  background: transparent; border: none; box-shadow: none; padding: 6px 8px;
  border-radius: 12px; color: {css_color(fg)};
}}
.island button.agenda-row:hover {{ background: {css_color(fg, 0.07)}; }}
.island button.page-dot {{
  min-width: 6px; min-height: 6px; padding: 0; border: none; box-shadow: none;
  border-radius: 999px; background: {css_color(fg, 0.25)};
}}
.island button.page-dot.active {{ background: {css_color(fg, 0.9)}; min-width: 16px; }}
.island button.nav-arrow {{
  background: {css_color(fg, 0.08)}; color: {css_color(fg)}; border: none; box-shadow: none;
  border-radius: 999px; min-width: 22px; min-height: 22px; padding: 2px;
}}
.island button.nav-arrow:hover {{ background: {css_color(fg, 0.18)}; }}
.island button.water-snooze {{
  background: {css_color(fg, 0.08)}; color: {css_color(fg)}; border: none; box-shadow: none;
  border-radius: 999px; padding: 4px 12px; font-size: 11px;
}}
"""


def accent_tuple(spec):
    c = rgba(spec)
    return (c.red, c.green, c.blue)
