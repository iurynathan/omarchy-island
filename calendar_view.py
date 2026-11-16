"""Calendário local (sem conta): grade do mês com semanas ISO, progresso do ano e da vida.

Espelha o popup do omarchy.clock (mesmas preferências: início da semana, ano de
nascimento e expectativa de vida), para quem não quer conectar o Google.
"""
import calendar
from datetime import date

from gi.repository import Gtk

import i18n
from i18n import _, month, weekday
from views import icon, label

# Índice estilo JS do omarchy.clock (0 = domingo) -> índice do calendar.Calendar (0 = segunda)
WEEK_STARTS = {"monday": 0, "sunday": 6, "saturday": 5}
DEFAULT_LIFE_EXPECTANCY = 90


def resolve_week_start(value):
    if value in WEEK_STARTS:
        return WEEK_STARTS[value]
    # "auto": segue o costume do idioma da ilha
    return 0 if i18n.lang() == "es" else 6


def month_grid(year, mon, first_weekday):
    """Sempre 6 semanas de 7 dias (a ilha não pula de tamanho entre os meses)."""
    cal = calendar.Calendar(first_weekday)
    weeks = cal.monthdatescalendar(year, mon)
    while len(weeks) < 6:
        last = weeks[-1][-1]
        weeks.append([date.fromordinal(last.toordinal() + i) for i in range(1, 8)])
    return weeks[:6]


def year_progress(today):
    start = date(today.year, 1, 1)
    total = (date(today.year + 1, 1, 1) - start).days
    return max(0.0, min(1.0, (today - start).days / total))


def life_progress(today, birth_year, expectancy):
    if not birth_year or birth_year > today.year or birth_year < today.year - 120:
        return None
    span = expectancy if 0 < expectancy <= 150 else DEFAULT_LIFE_EXPECTANCY
    age = today.year - birth_year
    return max(0.0, min(1.0, age / span)), age, span


class MonthGrid(Gtk.Box):
    """Grade do mês. on_select(date) ao clicar num dia."""

    def __init__(self, on_select=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.on_select = on_select
        self.today = date.today()
        self.view = (self.today.year, self.today.month)
        self.selected = None
        self.marked = set()
        self.first_weekday = 6

        head = Gtk.Box(spacing=4)
        self.title = label("title")
        head.pack_start(self.title, True, True, 0)
        self.today_btn = self._nav_button("go-home-symbolic", _("Hoje"), self.go_today)
        prev = self._nav_button("go-previous-symbolic", _("Mês anterior"), lambda: self.step(-1))
        nxt = self._nav_button("go-next-symbolic", _("Próximo mês"), lambda: self.step(1))
        for b in (self.today_btn, prev, nxt):
            head.pack_start(b, False, False, 0)
        self.pack_start(head, False, False, 0)

        self.grid = Gtk.Grid(column_homogeneous=True, row_spacing=2, column_spacing=2)
        self.pack_start(self.grid, False, False, 0)

    @staticmethod
    def _nav_button(icon_name, tip, cb):
        btn = Gtk.Button()
        btn.add(icon(icon_name, 13))
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.set_can_focus(False)
        btn.set_tooltip_text(tip)
        btn.get_style_context().add_class("nav-arrow")
        btn.connect("clicked", lambda *_a: cb())
        return btn

    def configure(self, week_start, marked=None):
        self.first_weekday = resolve_week_start(week_start)
        self.marked = marked or set()
        self.render()

    def go_today(self):
        self.today = date.today()
        self.view = (self.today.year, self.today.month)
        self.selected = None
        self.render()
        if self.on_select:
            self.on_select(None)

    def step(self, delta):
        y, m = self.view
        m += delta
        y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
        self.view = (y, m)
        self.render()

    def _select(self, d):
        self.selected = None if d == self.selected else d
        if (d.year, d.month) != self.view:
            self.view = (d.year, d.month)
        self.render()
        if self.on_select:
            self.on_select(self.selected)

    def render(self):
        self.today = date.today()
        y, m = self.view
        self.title.set_text(_("{mes} de {ano}").format(mes=month(m).capitalize(), ano=y))
        self.today_btn.set_visible((y, m) != (self.today.year, self.today.month)
                                   or self.selected is not None)
        for c in self.grid.get_children():
            self.grid.remove(c)

        wk = label("cal-head", 0.5)
        wk.set_text(_("S"))
        wk.set_tooltip_text(_("Semana ISO"))
        self.grid.attach(wk, 0, 0, 1, 1)
        for col in range(7):
            wd = (self.first_weekday + col) % 7
            h = label("cal-head", 0.5)
            h.set_text(weekday(wd, True)[:3].capitalize())
            self.grid.attach(h, col + 1, 0, 1, 1)

        for row, week in enumerate(month_grid(y, m, self.first_weekday), start=1):
            n = label("cal-week", 0.5)
            monday = next(d for d in week if d.weekday() == 0)
            n.set_text(str(monday.isocalendar()[1]))
            self.grid.attach(n, 0, row, 1, 1)
            for col, d in enumerate(week, start=1):
                self.grid.attach(self._day_button(d, m), col, row, 1, 1)
        self.grid.show_all()

    def _day_button(self, d, m):
        btn = Gtk.Button()
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.set_can_focus(False)
        ctx = btn.get_style_context()
        ctx.add_class("cal-day")
        if d.month != m:
            ctx.add_class("other")
        if d == self.today:
            ctx.add_class("today")
        if d == self.selected:
            ctx.add_class("selected")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        num = Gtk.Label(label=str(d.day))
        box.pack_start(num, False, False, 0)
        dot = Gtk.Label(label="•" if d in self.marked else " ")
        dot.get_style_context().add_class("cal-dot")
        box.pack_start(dot, False, False, 0)
        btn.add(box)
        btn.connect("clicked", lambda *_a: self._select(d))
        return btn


class ProgressRow(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        top = Gtk.Box()
        self.name = label("dim small")
        self.value = label("dim small", 1.0)
        top.pack_start(self.name, True, True, 0)
        top.pack_end(self.value, False, False, 0)
        self.bar = Gtk.ProgressBar()
        self.bar.get_style_context().add_class("thin")
        self.pack_start(top, False, False, 0)
        self.pack_start(self.bar, False, False, 0)

    def set(self, name, value, fraction):
        self.name.set_text(name)
        self.value.set_text(value)
        self.bar.set_fraction(fraction)
