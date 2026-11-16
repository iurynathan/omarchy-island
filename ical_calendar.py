"""Leitura de agenda via URL iCal (.ics) somente leitura (Google, Outlook, iCloud, Nextcloud…).

A URL secreta é guardada no chaveiro do sistema (SecretStore), nunca no config.json.
"""
import re
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from secret_store import SecretStore

MAX_BYTES = 5 * 1024 * 1024
MEET_RE = re.compile(
    r"https://(?:meet\.google\.com|[\w.-]*zoom\.us|teams\.microsoft\.com)/[^\s<>\"'\\]+",
    re.IGNORECASE,
)


def normalize_ical_url(url):
    """Aceita https:// ou webcal:// (convertido para https://). Rejeita outros esquemas."""
    u = (url or "").strip()
    if u.lower().startswith("webcal://"):
        u = "https://" + u[9:]
    if not u.startswith("https://") or len(u) > 2048 or any(c.isspace() for c in u):
        return None
    return u


def _unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text)


def _unescape(val):
    return (val.replace("\\n", "\n")
               .replace("\\N", "\n")
               .replace("\\,", ",")
               .replace("\\;", ";")
               .replace("\\\\", "\\"))


def _parse_dt(val, params):
    val = val.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", val):
        d = date(int(val[:4]), int(val[4:6]), int(val[6:8]))
        return {"date": d.isoformat()}
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z?)", val)
    if not m:
        return None
    y, mo, da, h, mi, s, z = m.groups()
    dt = datetime(int(y), int(mo), int(da), int(h), int(mi), int(s))
    if z == "Z":
        dt = dt.replace(tzinfo=timezone.utc)
    elif "TZID" in params:
        try:
            dt = dt.replace(tzinfo=ZoneInfo(params["TZID"]))
        except (ZoneInfoNotFoundError, KeyError, ValueError):
            dt = dt.astimezone()
    else:
        dt = dt.astimezone()
    return {"dateTime": dt.isoformat()}


def parse_ics(text, start, end):
    """Converte conteúdo .ics em itens compatíveis com agenda.normalize()."""
    lines = _unfold(text).splitlines()
    items = []
    cur = None
    in_alarm = False

    for line in lines:
        if line == "BEGIN:VEVENT":
            cur = {}
            in_alarm = False
            continue
        if line == "END:VEVENT":
            if cur and cur.get("start") and cur.get("summary"):
                items.append(cur)
            cur = None
            continue
        if cur is None:
            continue
        if line == "BEGIN:VALARM":
            in_alarm = True
            continue
        if line == "END:VALARM":
            in_alarm = False
            continue
        if in_alarm or ":" not in line:
            continue

        raw_key, val = line.split(":", 1)
        parts = raw_key.split(";")
        key = parts[0].upper()
        params = {}
        for p in parts[1:]:
            if "=" in p:
                pk, pv = p.split("=", 1)
                params[pk.upper()] = pv.strip('"')

        if key == "UID":
            cur["id"] = val.strip()
        elif key == "SUMMARY":
            cur["summary"] = _unescape(val).strip()
        elif key == "STATUS":
            if val.strip().upper() == "CANCELLED":
                cur["status"] = "cancelled"
        elif key == "DTSTART":
            dt = _parse_dt(val, params)
            if dt:
                cur["start"] = dt
        elif key == "DTEND":
            dt = _parse_dt(val, params)
            if dt:
                cur["end"] = dt
        elif key in ("LOCATION", "DESCRIPTION", "URL"):
            text_val = _unescape(val)
            m = MEET_RE.search(text_val)
            if m and not cur.get("hangoutLink"):
                cur["hangoutLink"] = m.group(0)
            if key == "URL" and text_val.startswith("https://"):
                cur["htmlLink"] = text_val.strip()

    # Filtra rapidamente pelo intervalo [start, end]
    filtered = []
    for it in items:
        s = it["start"]
        if "dateTime" in s:
            dt = datetime.fromisoformat(s["dateTime"]).astimezone()
        else:
            dt = datetime.fromisoformat(s["date"]).replace(tzinfo=start.tzinfo)
        e = it.get("end") or s
        if "dateTime" in e:
            edt = datetime.fromisoformat(e["dateTime"]).astimezone()
        else:
            edt = datetime.fromisoformat(e["date"]).replace(tzinfo=start.tzinfo)
        if edt >= start and dt <= end + timedelta(days=1):
            filtered.append(it)
    return filtered


class IcalCalendar:
    def __init__(self):
        self._store = SecretStore("ical-url", "Agenda iCal")
        self._url = normalize_ical_url(self._store.load())

    @property
    def connected(self):
        return bool(self._url)

    def set_url(self, url):
        norm = normalize_ical_url(url)
        if not norm:
            raise ValueError("URL inválida (use https:// ou webcal://)")
        self._url = norm
        self._store.save(norm)

    def disconnect(self):
        self._url = None
        self._store.clear()

    def fetch_events(self, start, end):
        if not self._url:
            return []
        req = urllib.request.Request(self._url, headers={"User-Agent": "omarchy-island"})
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Arquivo .ics excede 5 MB")
        text = raw.decode("utf-8", errors="replace")
        return parse_ics(text, start, end)
