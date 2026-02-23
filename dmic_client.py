"""
D-MIC v5 — Pydroid 3 BULLETPROOF Edition
==========================================
All errors logged to: ~/dmic_log.txt
If app crashes, check that file for details.

BEFORE RUNNING:
   1. pip install kivy pyjnius
   2. Settings > Apps > Pydroid 3 > Permissions > Microphone > Allow

Developed by Soham
"""

# ═══════════════════════════════════════════════════════════════
# STEP 0: FILE-BASED ERROR LOGGER (before ANY other import)
#   If the app crashes, check ~/dmic_log.txt on your phone
# ═══════════════════════════════════════════════════════════════
import os
import sys

_LOG_PATH = os.path.join(os.path.expanduser('~'), 'dmic_log.txt')

def log(msg):
    """Write to file AND console. Survives crashes."""
    line = f"[DMIC] {msg}"
    try:
        with open(_LOG_PATH, 'a') as f:
            f.write(line + '\n')
    except:
        pass
    try:
        print(line, flush=True)
    except:
        pass

# Clear old log
try:
    with open(_LOG_PATH, 'w') as f:
        f.write(f"=== D-MIC v5 Log ===\n")
        f.write(f"Python: {sys.version}\n")
        f.write(f"Platform: {sys.platform}\n\n")
except:
    pass

log("══════ D-MIC v5 Starting ══════")

# ═══════════════════════════════════════════════════════════════
# STEP 1: Basic imports (safe, no Android/Kivy yet)
# ═══════════════════════════════════════════════════════════════
try:
    import struct
    import socket
    import threading
    import time
    import math
    import traceback
    import platform as plat
    log("Basic imports: OK")
except Exception as e:
    log(f"FATAL: Basic import failed: {e}")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
# STEP 2: Kivy (import BEFORE jnius to avoid JVM conflicts)
# ═══════════════════════════════════════════════════════════════
try:
    # Only set GL backend on Windows. On Android, Kivy auto-detects.
    if plat.system() == 'Windows':
        os.environ.setdefault('KIVY_GL_BACKEND', 'angle_sdl2')
    log(f"OS: {plat.system()}")

    log("Importing Kivy...")
    from kivy.app import App
    log("  App OK")
    from kivy.uix.floatlayout import FloatLayout
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.label import Label
    from kivy.uix.textinput import TextInput
    from kivy.uix.button import Button
    from kivy.uix.widget import Widget
    log("  Widgets OK")
    from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
    log("  Graphics OK")
    from kivy.clock import Clock
    log("  Clock OK")
    from kivy.core.window import Window
    log(f"  Window OK (Window={Window})")
    from kivy.utils import get_color_from_hex
    from kivy.metrics import dp, sp
    from kivy.properties import NumericProperty, BooleanProperty
    log("Kivy: ALL imports OK ✓")
except Exception as e:
    log(f"FATAL: Kivy import failed: {e}")
    traceback.print_exc()
    # Write to log file too
    try:
        with open(_LOG_PATH, 'a') as f:
            traceback.print_exc(file=f)
    except: pass
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
# STEP 3: jnius — LAZY LOADING (never call autoclass at top level)
#   All Android API calls happen inside functions, not during import.
#   This prevents JVM conflicts with Kivy's initialization.
# ═══════════════════════════════════════════════════════════════
_jnius_ok = False
_jarray_fn = None

def _init_jnius():
    """Initialize jnius lazily. Call this only when needed."""
    global _jnius_ok, _jarray_fn
    if _jnius_ok:
        return True
    try:
        from jnius import autoclass, cast
        log("jnius: autoclass OK")
        try:
            from jnius import jarray
            _jarray_fn = jarray
            log("jnius: jarray OK")
        except ImportError:
            log("jnius: jarray not found (will use fallback)")
        _jnius_ok = True
        return True
    except ImportError:
        log("jnius: NOT available (PC mode)")
        return False
    except Exception as e:
        log(f"jnius: init error: {e}")
        return False

def _get_context():
    """Get Android application context. Returns None on PC."""
    try:
        from jnius import autoclass
        AT = autoclass('android.app.ActivityThread')
        app = AT.currentApplication()
        if app:
            ctx = app.getApplicationContext()
            log(f"Android context: {ctx}")
            return ctx
    except Exception as e:
        log(f"Context error: {e}")
    return None

def _is_android():
    """Check if running on Android."""
    if plat.system() == 'Linux' and os.path.exists('/system/build.prop'):
        return True
    try:
        _init_jnius()
        if _jnius_ok:
            from jnius import autoclass
            autoclass('android.os.Build')
            return True
    except:
        pass
    return False

# Detect platform (safe check, no JVM init yet)
IS_ANDROID = (plat.system() == 'Linux' and
              (os.path.exists('/system/build.prop') or
               'android' in sys.platform or
               'ANDROID_ROOT' in os.environ))
log(f"IS_ANDROID: {IS_ANDROID}")

# ═══════════════════════════════════════════════════════════════
# Colors
# ═══════════════════════════════════════════════════════════════
C_BG     = get_color_from_hex('#0A0A0F')
C_CARD   = get_color_from_hex('#12121A')
C_BORDER = get_color_from_hex('#2A2A3E')
C_CYAN   = get_color_from_hex('#00E5FF')
C_PURPLE = get_color_from_hex('#7C4DFF')
C_RED    = get_color_from_hex('#FF1744')
C_GREEN  = get_color_from_hex('#00E676')
C_ORANGE = get_color_from_hex('#FF9100')
C_WHITE  = [1, 1, 1, 1]
C_DIM    = [1, 1, 1, 0.3]
C_MID    = [1, 1, 1, 0.5]
log("Colors defined")


# ═══════════════════════════════════════════════════════════════
# PERMISSION CHECKER
# ═══════════════════════════════════════════════════════════════
def check_mic_permission():
    """Check RECORD_AUDIO. User must grant manually in Settings."""
    if not IS_ANDROID:
        return True
    try:
        if not _init_jnius():
            log("Can't check permission (no jnius)")
            return True  # try anyway
        from jnius import autoclass
        ctx = _get_context()
        if not ctx:
            log("No context, can't check permission, trying anyway")
            return True
        PM = autoclass('android.content.pm.PackageManager')
        r = ctx.checkSelfPermission('android.permission.RECORD_AUDIO')
        ok = (r == PM.PERMISSION_GRANTED)
        log(f"Mic permission: {'GRANTED ✓' if ok else 'DENIED ✗'}")
        return ok
    except Exception as e:
        log(f"Permission check error: {e}")
        return True  # try anyway, AudioRecord will fail clearly


# ═══════════════════════════════════════════════════════════════
# AUDIO ENGINE
# ═══════════════════════════════════════════════════════════════
class AudioEngine:
    RATES   = [44100, 22050, 16000, 8000]
    SHORTS  = 1024
    RETRIES = 3

    def __init__(self):
        self.streaming = False
        self.vu_level  = 0.0
        self._thread   = None
        log("AudioEngine: created")

    def start(self, ip, port):
        if self.streaming:
            return
        self.streaming = True
        self._thread = threading.Thread(
            target=self._run_safe, args=(ip, port),
            name="DMIC-Audio", daemon=True
        )
        self._thread.start()

    def stop(self):
        log("AudioEngine: stopping")
        self.streaming = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None
        self.vu_level = 0.0

    def _run_safe(self, ip, port):
        try:
            log(f"Audio thread started → {ip}:{port}")
            if IS_ANDROID and _init_jnius():
                self._run_android(ip, port)
            else:
                self._run_mock(ip, port)
        except Exception as e:
            log(f"AUDIO FATAL: {e}")
            try:
                with open(_LOG_PATH, 'a') as f:
                    traceback.print_exc(file=f)
            except: pass
        finally:
            self.streaming = False
            self.vu_level = 0.0
            log("Audio thread ended")

    def _run_android(self, ip, port):
        from jnius import autoclass

        for attempt in range(self.RETRIES):
            recorder = None
            sock = None
            try:
                if not self.streaming:
                    return

                log(f"─ Attempt {attempt+1}/{self.RETRIES} ─")

                AR = autoclass('android.media.AudioRecord')
                AF = autoclass('android.media.AudioFormat')
                MR = autoclass('android.media.MediaRecorder')

                MONO  = AF.CHANNEL_IN_MONO
                PCM16 = AF.ENCODING_PCM_16BIT
                MIC   = MR.AudioSource.MIC
                INIT  = AR.STATE_INITIALIZED

                # ── Find working sample rate ──
                recorder = None
                rate_used = 0

                for rate in self.RATES:
                    try:
                        mb = AR.getMinBufferSize(rate, MONO, PCM16)
                        log(f"  {rate}Hz → minBuf={mb}")
                        if mb <= 0:
                            continue

                        bsz = max(mb * 4, 8192)
                        r = AR(MIC, rate, MONO, PCM16, bsz)
                        s = r.getState()
                        log(f"  {rate}Hz → state={s}")

                        if s == INIT:
                            recorder = r
                            rate_used = rate
                            log(f"  ✓ Using {rate}Hz")
                            break
                        else:
                            r.release()
                    except Exception as e:
                        log(f"  {rate}Hz error: {e}")

                if not recorder:
                    log("✗ All sample rates failed")
                    if attempt < self.RETRIES - 1:
                        log("Retrying in 2s...")
                        time.sleep(2)
                        continue
                    log("GIVE UP. Check mic permission in Settings.")
                    return

                # ── UDP ──
                log(f"UDP → {ip}:{port}")
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                addr = (ip, port)

                # ── Buffer ──
                use_jarray = False
                java_buf = None
                n_shorts = self.SHORTS

                if _jarray_fn:
                    try:
                        java_buf = _jarray_fn('h')(n_shorts)
                        use_jarray = True
                        log(f"jarray buffer: {n_shorts} shorts ✓")
                    except Exception as e:
                        log(f"jarray failed: {e}")

                if not use_jarray:
                    log("Using byte[] fallback")
                    n_bytes = n_shorts * 2

                # ── Start ──
                recorder.startRecording()
                rs = recorder.getRecordingState()
                log(f"RecordingState: {rs} (3=OK)")

                if rs != 3:
                    log("✗ Failed to start recording")
                    recorder.release()
                    recorder = None
                    if attempt < self.RETRIES - 1:
                        time.sleep(2)
                        continue
                    return

                log(f"★ STREAMING {rate_used}Hz → {ip}:{port} ★")

                pkt = 0
                errs = 0

                while self.streaming:
                    try:
                        if use_jarray:
                            n = recorder.read(java_buf, 0, n_shorts)
                            if n > 0:
                                data = struct.pack(f'<{n}h', *java_buf[:n])
                                sock.sendto(data, addr)
                                pk = max(abs(java_buf[i]) for i in range(0, n, max(1, n//16)))
                                self.vu_level = min(1.0, pk / 10000.0)
                        else:
                            bb = bytearray(n_bytes)
                            n = recorder.read(bb, 0, n_bytes)
                            if n > 0:
                                sock.sendto(bytes(bb[:n]), addr)
                                pk = 0
                                for i in range(0, min(n, 128), 2):
                                    v = abs(struct.unpack_from('<h', bb, i)[0])
                                    if v > pk: pk = v
                                self.vu_level = min(1.0, pk / 10000.0)

                        if n > 0:
                            pkt += 1
                            errs = 0
                            if pkt <= 5 or pkt % 200 == 0:
                                log(f"PKT #{pkt} VU={self.vu_level:.2f}")
                        elif n == 0:
                            time.sleep(0.002)
                        else:
                            errs += 1
                            if errs > 20:
                                log("Too many read errors")
                                break
                            time.sleep(0.01)

                    except Exception as ex:
                        log(f"Loop err: {ex}")
                        time.sleep(0.01)

                log(f"Done. {pkt} packets sent.")
                return  # success, no retry

            except Exception as ex:
                log(f"Attempt {attempt+1} err: {ex}")
                traceback.print_exc()
                if attempt < self.RETRIES - 1:
                    time.sleep(2)
            finally:
                if recorder:
                    try: recorder.stop(); recorder.release()
                    except: pass
                if sock:
                    try: sock.close()
                    except: pass

    def _run_mock(self, ip, port):
        log(f"Mock → {ip}:{port}")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        addr = (ip, port)
        t = pkt = 0
        while self.streaming:
            buf = b''.join(
                struct.pack('<h', int(8000*math.sin(2*math.pi*440*(t+i)/44100)))
                for i in range(1024)
            )
            t += 1024
            try: sock.sendto(buf, addr); pkt += 1
            except: pass
            self.vu_level = 0.3 + 0.2*math.sin(time.time()*3)
            if pkt <= 3 or pkt % 100 == 0: log(f"Mock #{pkt}")
            time.sleep(0.023)
        sock.close()
        self.vu_level = 0


# ═══════════════════════════════════════════════════════════════
# WAKELOCK (lazy jnius)
# ═══════════════════════════════════════════════════════════════
class WakeLockMgr:
    def __init__(self):
        self._wl = None

    def acquire(self):
        if not IS_ANDROID:
            return
        try:
            if not _init_jnius():
                return
            from jnius import autoclass, cast
            ctx = _get_context()
            if not ctx:
                return
            C = autoclass('android.content.Context')
            PM = autoclass('android.os.PowerManager')
            pm = cast('android.os.PowerManager',
                       ctx.getSystemService(C.POWER_SERVICE))
            self._wl = pm.newWakeLock(PM.PARTIAL_WAKE_LOCK, 'dmic:a')
            self._wl.acquire()
            log("WakeLock ✓")
        except Exception as e:
            log(f"WakeLock err (ok): {e}")

    def release(self):
        try:
            if self._wl and self._wl.isHeld():
                self._wl.release()
                log("WakeLock released")
        except: pass
        self._wl = None


# ═══════════════════════════════════════════════════════════════
# VU METER (simplified for low RAM)
# ═══════════════════════════════════════════════════════════════
class VUMeter(Widget):
    level  = NumericProperty(0.0)
    active = BooleanProperty(False)

    def __init__(self, **kw):
        super().__init__(**kw)
        self._t = 0
        self.bind(pos=self._draw, size=self._draw,
                  level=self._draw, active=self._draw)
        Clock.schedule_interval(self._tick, 1/20)

    def _tick(self, dt):
        self._t += dt * 2
        self._draw()

    def _draw(self, *_):
        try:
            self.canvas.clear()
            cx, cy = self.center_x, self.center_y
            r = min(self.width, self.height) * 0.38
            if r < 10:
                return

            lv = self.level
            act = self.active

            with self.canvas:
                # Glow
                if act and lv > 0.05:
                    a = lv
                    Color(0, 0.9*(1-a)+0.1*a, 1*(1-a), 0.1+a*0.2)
                    g = r + 20 + a*30
                    Ellipse(pos=(cx-g, cy-g), size=(g*2, g*2))

                # Circle fill
                if act:
                    Color(0, 0.9, 1, 0.08 + lv*0.2)
                else:
                    Color(1, 1, 1, 0.05 + 0.02*math.sin(self._t))
                Ellipse(pos=(cx-r, cy-r), size=(r*2, r*2))

                # Ring
                if act:
                    Color(0, 0.9*(1-lv), 1*(1-lv)+lv*0.1, 0.8)
                else:
                    Color(0.16, 0.16, 0.24, 1)
                Line(circle=(cx, cy, r), width=dp(2))

                # Level arc
                if act and lv > 0.02:
                    Color(0, 0.9*(1-lv), 1*(1-lv), 0.9)
                    Line(circle=(cx, cy, r+dp(6), 90, 90+lv*360), width=dp(3))

                # 8 segments (reduced from 12 for performance)
                for i in range(8):
                    sa = i * 45
                    sl = (i+1) / 8
                    if act and lv >= sl:
                        if sl > 0.75: Color(1, 0.1, 0.25, 0.8)
                        elif sl > 0.5: Color(1, 0.7, 0, 0.7)
                        else: Color(0, 0.9, 1, 0.6)
                    else:
                        Color(1, 1, 1, 0.03)
                    Line(circle=(cx, cy, r+dp(14), sa+3, sa+38), width=dp(4))
        except Exception as e:
            log(f"VU draw err: {e}")


# ═══════════════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════════════
class DMicApp(App):

    def __init__(self, **kw):
        try:
            super().__init__(**kw)
            self.title = 'D-MIC'
            self.engine = AudioEngine()
            self.wakelock = WakeLockMgr()
            self._on = False
            self._logs = []
            log("DMicApp init OK")
        except Exception as e:
            log(f"DMicApp init FAIL: {e}")
            raise

    def build(self):
        log("build() starting")
        try:
            return self._build_ui()
        except Exception as e:
            log(f"build() FAIL: {e}")
            with open(_LOG_PATH, 'a') as f:
                traceback.print_exc(file=f)
            traceback.print_exc()
            # Return a minimal error screen
            root = FloatLayout()
            root.add_widget(Label(
                text=f'D-MIC Error:\n{e}\n\nCheck ~/dmic_log.txt',
                font_size=sp(14), color=[1, 0.3, 0.3, 1],
                halign='center', valign='middle',
                size_hint=(0.9, 0.5),
                pos_hint={'center_x': .5, 'center_y': .5}
            ))
            return root

    def _build_ui(self):
        # Safe window setup
        try:
            if Window is not None:
                Window.clearcolor = C_BG
        except:
            pass

        root = FloatLayout()

        # BG
        try:
            with root.canvas.before:
                Color(*C_BG)
                self._bg = Rectangle(size=(500, 900))
            if Window:
                Window.bind(size=lambda *_: setattr(self._bg, 'size', Window.size))
                self._bg.size = Window.size
        except Exception as e:
            log(f"BG err: {e}")

        # Title
        root.add_widget(Label(
            text='D-MIC', font_size=sp(38), bold=True, color=C_CYAN,
            size_hint=(1, None), height=dp(50),
            pos_hint={'center_x': .5, 'top': .97}
        ))
        root.add_widget(Label(
            text='Phone > Laptop Mic', font_size=sp(11), color=C_MID,
            size_hint=(1, None), height=dp(20),
            pos_hint={'center_x': .5, 'top': .91}
        ))

        # VU
        self.vu = VUMeter(
            size_hint=(.65, .22),
            pos_hint={'center_x': .5, 'center_y': .67}
        )
        root.add_widget(self.vu)

        self.mic_lbl = Label(
            text='MIC\nOFF', font_size=sp(20), bold=True,
            color=C_DIM, halign='center', valign='middle',
            size_hint=(None, None), size=(dp(90), dp(60)),
            pos_hint={'center_x': .5, 'center_y': .67}
        )
        root.add_widget(self.mic_lbl)

        # Status
        self.status_lbl = Label(
            text='Enter server IP and tap STREAM',
            font_size=sp(11), color=C_DIM,
            size_hint=(1, None), height=dp(18),
            pos_hint={'center_x': .5, 'center_y': .53}
        )
        root.add_widget(self.status_lbl)

        # Log area
        self.log_lbl = Label(
            text='', font_size=sp(7), color=[1, 1, 1, 0.2],
            halign='left', valign='top',
            size_hint=(.92, None), height=dp(42),
            pos_hint={'center_x': .5, 'center_y': .47}
        )
        self.log_lbl.bind(size=self.log_lbl.setter('text_size'))
        root.add_widget(self.log_lbl)

        # Card
        card = BoxLayout(
            orientation='vertical', spacing=dp(8),
            padding=[dp(18), dp(12), dp(18), dp(12)],
            size_hint=(.88, None), height=dp(125),
            pos_hint={'center_x': .5, 'center_y': .30}
        )
        try:
            with card.canvas.before:
                Color(*C_CARD)
                self._cr = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(14)])
                Color(*C_BORDER)
                self._cb = Line(rounded_rectangle=(*card.pos, *card.size, dp(14)), width=1)
            card.bind(pos=self._uc, size=self._uc)
        except Exception as e:
            log(f"Card canvas err: {e}")

        # IP
        ipr = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(46))
        ipr.add_widget(Label(text='IP', font_size=sp(13), bold=True,
                             color=C_CYAN, size_hint_x=None, width=dp(30)))
        self.ip_in = TextInput(
            hint_text='192.168.X.X', multiline=False, font_size=sp(15),
            background_color=[.04, .04, .06, 1], foreground_color=C_WHITE,
            hint_text_color=C_DIM, cursor_color=C_CYAN,
            padding=[dp(10)]*4
        )
        ipr.add_widget(self.ip_in)
        card.add_widget(ipr)

        # Port
        ptr = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(36))
        ptr.add_widget(Label(text='PORT', font_size=sp(10), bold=True,
                             color=C_MID, size_hint_x=None, width=dp(40)))
        self.port_in = TextInput(
            text='50005', multiline=False, font_size=sp(13),
            background_color=[.04, .04, .06, 1], foreground_color=[1, 1, 1, .6],
            hint_text_color=C_DIM, cursor_color=C_PURPLE,
            padding=[dp(8)]*4, input_filter='int'
        )
        ptr.add_widget(self.port_in)
        card.add_widget(ptr)
        root.add_widget(card)

        # Button
        self.btn = Button(
            text='STREAM', font_size=sp(18), bold=True,
            size_hint=(.88, None), height=dp(52),
            pos_hint={'center_x': .5, 'center_y': .12},
            background_normal='', background_color=[0, 0, 0, 0],
            color=[0, 0, 0, 1]
        )
        try:
            with self.btn.canvas.before:
                Color(*C_CYAN)
                self._br = RoundedRectangle(
                    pos=self.btn.pos, size=self.btn.size, radius=[dp(14)])
            self.btn.bind(pos=self._ub, size=self._ub)
        except Exception as e:
            log(f"Btn canvas err: {e}")
            self.btn.background_color = C_CYAN

        self.btn.bind(on_release=self._btn_tap)
        root.add_widget(self.btn)

        # Footer
        root.add_widget(Label(
            text='Developed by Soham', font_size=sp(9),
            color=[1, 1, 1, .1], size_hint=(1, None), height=dp(14),
            pos_hint={'center_x': .5, 'y': .01}
        ))

        # Tick
        Clock.schedule_interval(self._tick, 1/15)

        log("build() OK ✓")
        self._ui_log("Ready")
        return root

    # ── Helpers ──
    def _uc(self, w, *_):
        try:
            self._cr.pos = w.pos; self._cr.size = w.size
            self._cb.rounded_rectangle = (*w.pos, *w.size, dp(14))
        except: pass

    def _ub(self, w, *_):
        try:
            self._br.pos = w.pos; self._br.size = w.size
        except: pass

    def _ui_log(self, msg):
        log(msg)
        self._logs.append(msg)
        self._logs = self._logs[-4:]
        try:
            self.log_lbl.text = '\n'.join(self._logs)
        except: pass

    def _set_status(self, txt, col):
        try:
            self.status_lbl.text = txt
            self.status_lbl.color = col
        except: pass

    def _tick(self, dt):
        try:
            lv = self.engine.vu_level
            self.vu.level = lv
            self.vu.active = self._on
            if self._on:
                self.mic_lbl.text = f'MIC\n{int(lv*100)}%'
                self.mic_lbl.color = C_CYAN if lv < 0.7 else C_RED
        except: pass

    # ── Button ──
    def _btn_tap(self, *a):
        log("★ BUTTON TAP ★")
        self._ui_log("Button tapped")
        try:
            if self._on:
                self._stop()
            else:
                self._start()
        except Exception as e:
            log(f"BTN ERROR: {e}")
            traceback.print_exc()
            self._ui_log(f"Error: {e}")

    def _start(self):
        ip = self.ip_in.text.strip()
        port = int(self.port_in.text.strip() or '50005')
        log(f"START: {ip}:{port}")

        if not ip:
            self._set_status('Enter IP!', C_RED)
            self._ui_log("No IP")
            return

        # Permission check
        if IS_ANDROID:
            self._ui_log("Checking mic permission...")
            ok = check_mic_permission()
            if not ok:
                self._set_status('Mic DENIED! Enable in Settings', C_RED)
                self._ui_log("Settings > Apps > Pydroid 3")
                self._ui_log("> Permissions > Microphone > Allow")
                return

        self._ui_log(f"Connecting {ip}:{port}...")

        try:
            self.wakelock.acquire()
        except: pass

        self.engine.start(ip, port)
        self._on = True

        self._set_status(f'Streaming to {ip}:{port}', C_GREEN)
        self.btn.text = 'STOP'
        self._set_btn_col(C_RED)
        self._ui_log("Streaming!")

    def _stop(self):
        log("STOP")
        self._ui_log("Stopping...")
        self.engine.stop()
        try: self.wakelock.release()
        except: pass
        self._on = False
        self._set_status('Stopped', C_DIM)
        self.btn.text = 'STREAM'
        self.mic_lbl.text = 'MIC\nOFF'
        self.mic_lbl.color = C_DIM
        self._set_btn_col(C_CYAN)
        self._ui_log("Stopped")

    def _set_btn_col(self, c):
        try:
            self.btn.canvas.before.clear()
            with self.btn.canvas.before:
                Color(*c)
                self._br = RoundedRectangle(
                    pos=self.btn.pos, size=self.btn.size, radius=[dp(14)])
        except:
            self.btn.background_color = c

    def on_stop(self):
        try: self._stop()
        except: pass


# ═══════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════
log("Creating app instance...")
try:
    if __name__ == '__main__':
        DMicApp().run()
except Exception as e:
    log(f"APP CRASHED: {e}")
    try:
        with open(_LOG_PATH, 'a') as f:
            traceback.print_exc(file=f)
    except: pass
    traceback.print_exc()
finally:
    log("App exited")
