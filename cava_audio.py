"""Integração opcional com o CAVA (áudio reativo em tempo real via PipeWire/PulseAudio)."""
import os
import shutil
import subprocess
import tempfile
import threading

from gi.repository import GLib

BARS = 5


def is_available():
    return shutil.which("cava") is not None


def install_command():
    """Comando privilegiado (pkexec) para instalar o cava conforme a distro."""
    if shutil.which("pacman"):
        return ["pkexec", "pacman", "-S", "--noconfirm", "--needed", "cava"]
    if shutil.which("apt-get"):
        return ["pkexec", "apt-get", "install", "-y", "cava"]
    if shutil.which("dnf"):
        return ["pkexec", "dnf", "install", "-y", "cava"]
    return None


def install_async(on_done):
    """Instala o cava em background via pkexec; chama on_done(ok, err_msg) na thread da UI."""
    cmd = install_command()
    if not cmd:
        GLib.idle_add(on_done, False, "Gerenciador de pacotes não suportado")
        return

    def work():
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            ok = res.returncode == 0 and is_available()
            err = "" if ok else (res.stderr.strip().splitlines()[-1] if res.stderr.strip() else "cancelado")
            GLib.idle_add(on_done, ok, err)
        except Exception as e:
            GLib.idle_add(on_done, False, str(e))

    threading.Thread(target=work, daemon=True).start()


class CavaReader:
    """Lê níveis de frequência (0.0..1.0) do cava quando está tocando música."""

    def __init__(self, on_levels):
        self.on_levels = on_levels
        self._proc = None
        self._cfg_path = None
        self._running = False
        self._lock = threading.Lock()

    def set_active(self, active):
        if active and is_available():
            self.start()
        else:
            self.stop()

    def start(self):
        with self._lock:
            if self._running:
                return
            if not is_available():
                return
            self._running = True
            fd, self._cfg_path = tempfile.mkstemp(prefix="omarchy-island-cava-", suffix=".conf")
            with os.fdopen(fd, "w") as f:
                f.write(
                    "[general]\n"
                    "framerate = 30\n"
                    f"bars = {BARS}\n"
                    "[output]\n"
                    "method = raw\n"
                    "raw_target = /dev/stdout\n"
                    "data_format = ascii\n"
                    "ascii_max_range = 100\n"
                )
            try:
                self._proc = subprocess.Popen(
                    ["cava", "-p", self._cfg_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
            except OSError:
                self._running = False
                self._cleanup_file()
                self.on_levels(None)
                return
            threading.Thread(target=self._read_loop, args=(self._proc,), daemon=True).start()

    def stop(self):
        with self._lock:
            self._running = False
            proc = self._proc
            self._proc = None
            if proc is not None:
                try:
                    proc.terminate()
                except OSError:
                    pass
            self._cleanup_file()
        self.on_levels(None)

    def _cleanup_file(self):
        if self._cfg_path:
            try:
                os.remove(self._cfg_path)
            except OSError:
                pass
            self._cfg_path = None

    def _read_loop(self, proc):
        try:
            for line in proc.stdout:
                if not self._running or self._proc is not proc:
                    break
                parts = [p for p in line.strip().split(";") if p]
                if len(parts) < BARS:
                    continue
                try:
                    vals = [min(1.0, max(0.0, int(p) / 100.0)) for p in parts[:BARS]]
                except ValueError:
                    continue
                GLib.idle_add(self._deliver, vals)
        except Exception:
            pass
        finally:
            try:
                proc.wait(timeout=1)
            except Exception:
                pass

    def _deliver(self, vals):
        if self._running:
            self.on_levels(vals)
        return False
