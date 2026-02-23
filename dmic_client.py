"""
D-MIC Client v4 — Pydroid 3 Edition
=====================================
Streams phone mic → laptop via UDP.
Designed SPECIFICALLY for Pydroid 3. NOT Buildozer.

Install in Pydroid 3's pip:
    pip install kivy pyjnius

BEFORE RUNNING:
    Android Settings → Apps → Pydroid 3 → Permissions → Microphone → ALLOW

Developed by Soham
"""

# ══════════════════════════════════════════
#  STEP 0: Logging helper (before everything)
# ══════════════════════════════════════════
import sys

def log(msg):
    """Print with flush for Pydroid console visibility."""
    print(f"[DMIC] {msg}", flush=True)

log("═══ D-MIC v4 Starting ═══")
log(f"Python: {sys.version}")

# ══════════════════════════════════════════
#  STEP 1: Basic imports
# ══════════════════════════════════════════
import os
import struct
import socket
import threading
import time
import math
import traceback

log("Basic imports OK")

# ══════════════════════════════════════════
#  STEP 2: Platform detection (Pydroid-safe)
# ══════════════════════════════════════════
IS_ANDROID = False
HAS_JNIUS  = False
_context   = None  # Android Context (NOT Activity)

try:
    from jnius import autoclass, cast
    HAS_JNIUS = True
    log("jnius imported OK")

    # Try to get jarray (different pyjnius versions)
    try:
        from jnius import jarray
        log("jarray imported OK")
    except ImportError:
        # Fallback: some pyjnius versions put it elsewhere
        try:
            from jnius.reflect import jarray
            log("jarray imported from jnius.reflect")
        except ImportError:
            jarray = None
            log("WARNING: jarray not available")

    # ── Get Android context (Pydroid 3 way) ──
    # DO NOT use 'from android import mActivity' — that's Buildozer only!
    try:
        ActivityThread = autoclass('android.app.ActivityThread')
        app = ActivityThread.currentApplication()
        if app is not None:
            _context = app.getApplicationContext()
            IS_ANDROID = True
            log("✓ Android context obtained via ActivityThread")
        else:
            log("ActivityThread.currentApplication() returned None")
    except Exception as e:
        log(f"Context error: {e}")

except ImportError:
    log("No jnius — running on PC (mock mode)")

log(f"IS_ANDROID={IS_ANDROID}, HAS_JNIUS={HAS_JNIUS}, context={'YES' if _context else 'NO'}")

# ══════════════════════════════════════════
#  STEP 3: Kivy setup (before any kivy import)
# ══════════════════════════════════════════
# NEVER set ANGLE on Android — it's Windows-only and crashes
import platform
if platform.system() == 'Windows':
    os.environ.setdefault('KIVY_GL_BACKEND', 'angle_sdl2')

log("Importing Kivy...")

from kivy.app import App
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.utils import get_color_from_hex
from kivy.metrics import dp, sp
from kivy.properties import NumericProperty, BooleanProperty

log("Kivy imports OK")

# ══════════════════════════════════════════
#  Colors
# ══════════════════════════════════════════
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


# ══════════════════════════════════════════
#  PERMISSION CHECK (Pydroid 3 compatible)
# ══════════════════════════════════════════
def check_mic_permission():
    """
    Check if RECORD_AUDIO is granted.
    In Pydroid 3, you CANNOT request permissions programmatically.
    The user must grant it manually:
        Settings → Apps → Pydroid 3 → Permissions → Microphone
    """
    if not IS_ANDROID:
        return True

    try:
        PackageManager = autoclass('android.content.pm.PackageManager')
        result = _context.checkSelfPermission('android.permission.RECORD_AUDIO')
        granted = (result == PackageManager.PERMISSION_GRANTED)
        log(f"Mic permission: {'GRANTED ✓' if granted else 'DENIED ✗'}")
        return granted
    except Exception as e:
        log(f"Permission check error: {e}")
        # If check fails, try anyway — AudioRecord will fail clearly
        return True  # optimistic, let AudioRecord tell us


# ══════════════════════════════════════════
#  AUDIO ENGINE (Pydroid 3 + jnius)
# ══════════════════════════════════════════
class AudioEngine:
    """
    Captures mic via Android AudioRecord through pyjnius.
    - Tries multiple sample rates for device compatibility
    - Uses jarray for proper Java short[] interop
    - Falls back to byte[] if jarray unavailable
    - Retries on failure
    """

    # Try these in order — not all devices support 44100
    SAMPLE_RATES = [44100, 22050, 16000, 8000]
    NUM_SHORTS   = 1024  # ~23ms at 44100Hz
    MAX_RETRIES  = 3

    def __init__(self):
        self.streaming  = False
        self.vu_level   = 0.0
        self.sample_rate = 0  # will be set during init
        self._thread    = None
        self._lock      = threading.Lock()
        log("AudioEngine created")

    def start(self, ip, port):
        with self._lock:
            if self.streaming:
                log("Already streaming")
                return
            self.streaming = True

        self._thread = threading.Thread(
            target=self._safe_run, args=(ip, port),
            name="DMicAudio", daemon=True
        )
        self._thread.start()
        log(f"Audio thread started → {ip}:{port}")

    def stop(self):
        log("AudioEngine.stop() called")
        self.streaming = False
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=3)
            if t.is_alive():
                log("WARNING: Audio thread did not stop in time")
        self._thread = None
        self.vu_level = 0.0
        log("AudioEngine stopped")

    def _safe_run(self, ip, port):
        try:
            if IS_ANDROID and HAS_JNIUS:
                self._run_android(ip, port)
            else:
                self._run_mock(ip, port)
        except Exception as e:
            log(f"FATAL engine error: {e}")
            traceback.print_exc()
        finally:
            self.streaming = False
            self.vu_level = 0.0

    def _run_android(self, ip, port):
        log("── Android Audio Engine Starting ──")
        recorder = None
        sock = None

        for attempt in range(self.MAX_RETRIES):
            try:
                if not self.streaming:
                    return

                log(f"Attempt {attempt + 1}/{self.MAX_RETRIES}")

                # ── Load Java classes ──
                log("Loading Java audio classes...")
                AudioRecord   = autoclass('android.media.AudioRecord')
                AudioFormat   = autoclass('android.media.AudioFormat')
                MediaRecorder = autoclass('android.media.MediaRecorder')

                CH_MONO = AudioFormat.CHANNEL_IN_MONO
                PCM16   = AudioFormat.ENCODING_PCM_16BIT
                MIC_SRC = MediaRecorder.AudioSource.MIC
                STATE_INIT = AudioRecord.STATE_INITIALIZED
                log("Java classes loaded ✓")

                # ── Find working sample rate ──
                recorder = None
                chosen_rate = 0

                for rate in self.SAMPLE_RATES:
                    try:
                        min_buf = AudioRecord.getMinBufferSize(rate, CH_MONO, PCM16)
                        log(f"  Rate {rate}Hz → minBuf={min_buf}")

                        if min_buf <= 0:
                            log(f"  Rate {rate}Hz not supported, skipping")
                            continue

                        buf_sz = max(min_buf * 4, 8192)

                        rec = AudioRecord(MIC_SRC, rate, CH_MONO, PCM16, buf_sz)
                        state = rec.getState()
                        log(f"  Rate {rate}Hz → state={state} (need {STATE_INIT})")

                        if state == STATE_INIT:
                            recorder = rec
                            chosen_rate = rate
                            self.sample_rate = rate
                            log(f"  ✓ Using {rate}Hz, buffer={buf_sz}")
                            break
                        else:
                            rec.release()
                            log(f"  ✗ {rate}Hz failed to init")
                    except Exception as e:
                        log(f"  ✗ {rate}Hz error: {e}")

                if recorder is None:
                    log("✗ No sample rate worked!")
                    if attempt < self.MAX_RETRIES - 1:
                        log(f"Retrying in 2 seconds...")
                        time.sleep(2)
                        continue
                    else:
                        log("All retries exhausted. Is mic permission granted?")
                        log("Go to: Settings → Apps → Pydroid 3 → Permissions → Microphone")
                        return

                # ── UDP Socket ──
                log(f"Creating UDP socket → {ip}:{port}")
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                addr = (ip, port)

                # Test connectivity
                try:
                    sock.sendto(b'\x00\x00', addr)
                    log("UDP test packet sent ✓")
                except Exception as e:
                    log(f"UDP test failed: {e}")
                    log("Check: phone and laptop on same WiFi?")

                # ── Create read buffer ──
                n_shorts = self.NUM_SHORTS
                use_jarray = False

                if jarray is not None:
                    try:
                        java_buf = jarray('h')(n_shorts)
                        use_jarray = True
                        log(f"Using jarray('h')({n_shorts}) ✓")
                    except Exception as e:
                        log(f"jarray failed: {e}, using byte[] fallback")

                if not use_jarray:
                    # Fallback: use byte array
                    n_bytes = n_shorts * 2
                    log(f"Using byte[] fallback, size={n_bytes}")

                # ── Start recording ──
                log("Starting AudioRecord...")
                recorder.startRecording()
                rec_state = recorder.getRecordingState()
                log(f"Recording state: {rec_state} (3=RECORDING)")

                if rec_state != 3:  # RECORDSTATE_RECORDING
                    log("✗ Recording failed to start!")
                    recorder.stop()
                    recorder.release()
                    if attempt < self.MAX_RETRIES - 1:
                        time.sleep(2)
                        continue
                    return

                log(f"★ STREAMING @ {chosen_rate}Hz to {ip}:{port} ★")

                # ── Main capture loop ──
                pkt = 0
                errors = 0

                while self.streaming:
                    try:
                        if use_jarray:
                            n = recorder.read(java_buf, 0, n_shorts)
                            if n > 0:
                                data = struct.pack(f'<{n}h', *java_buf[:n])
                                sock.sendto(data, addr)
                                # VU (sample every 16th for speed)
                                peak = 0
                                for i in range(0, n, 16):
                                    v = abs(java_buf[i])
                                    if v > peak: peak = v
                                self.vu_level = min(1.0, peak / 10000.0)
                        else:
                            # Byte array fallback
                            byte_buf = bytearray(n_bytes)
                            n = recorder.read(byte_buf, 0, n_bytes)
                            if n > 0:
                                sock.sendto(bytes(byte_buf[:n]), addr)
                                # Simple VU from bytes
                                peak = 0
                                for i in range(0, min(n, 256), 2):
                                    s = struct.unpack_from('<h', byte_buf, i)[0]
                                    v = abs(s)
                                    if v > peak: peak = v
                                self.vu_level = min(1.0, peak / 10000.0)

                        if n > 0:
                            pkt += 1
                            errors = 0
                            if pkt <= 5 or pkt % 200 == 0:
                                log(f"PKT #{pkt} | n={n} | VU={self.vu_level:.2f}")
                        elif n == 0:
                            time.sleep(0.002)
                        else:
                            errors += 1
                            log(f"Read error: {n} (#{errors})")
                            if errors > 20:
                                log("Too many read errors, stopping")
                                break
                            time.sleep(0.01)

                    except socket.error as se:
                        log(f"Socket error: {se}")
                        time.sleep(0.05)
                    except Exception as ex:
                        log(f"Loop error: {ex}")
                        time.sleep(0.01)

                log(f"Stream ended. Total packets: {pkt}")
                # Success — don't retry
                return

            except Exception as ex:
                log(f"Attempt {attempt+1} error: {ex}")
                traceback.print_exc()
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(2)

            finally:
                # Cleanup this attempt
                if recorder:
                    try:
                        recorder.stop()
                        recorder.release()
                        log("AudioRecord released")
                    except: pass
                    recorder = None
                if sock:
                    try: sock.close()
                    except: pass
                    sock = None

        log("All attempts finished")

    def _run_mock(self, ip, port):
        """PC mock: sends sine wave for testing."""
        log(f"Mock stream → {ip}:{port}")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        addr = (ip, port)
        t = 0
        pkt = 0
        while self.streaming:
            samples = []
            for _ in range(1024):
                v = int(8000 * math.sin(2 * math.pi * 440 * t / 44100))
                samples.append(struct.pack('<h', max(-32768, min(32767, v))))
                t += 1
            try:
                sock.sendto(b''.join(samples), addr)
                pkt += 1
            except: pass
            self.vu_level = 0.3 + 0.2 * math.sin(time.time() * 3)
            if pkt <= 3 or pkt % 100 == 0:
                log(f"Mock PKT #{pkt}")
            time.sleep(0.023)
        sock.close()
        self.vu_level = 0.0
        log(f"Mock ended, {pkt} packets")


# ══════════════════════════════════════════
#  WAKELOCK (uses Application context)
# ══════════════════════════════════════════
class WakeLockMgr:
    def __init__(self):
        self._lock = None

    def acquire(self):
        if not IS_ANDROID or not _context:
            return
        try:
            Context = autoclass('android.content.Context')
            PowerManager = autoclass('android.os.PowerManager')
            pm = cast('android.os.PowerManager',
                       _context.getSystemService(Context.POWER_SERVICE))
            self._lock = pm.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK, 'dmic:audio')
            self._lock.acquire()
            log("✓ WakeLock acquired")
        except Exception as e:
            log(f"WakeLock error (non-fatal): {e}")

    def release(self):
        if self._lock:
            try:
                if self._lock.isHeld():
                    self._lock.release()
                    log("WakeLock released")
            except: pass
            self._lock = None


# ══════════════════════════════════════════
#  VU METER WIDGET
# ══════════════════════════════════════════
class VUMeter(Widget):
    level  = NumericProperty(0.0)
    active = BooleanProperty(False)

    def __init__(self, **kw):
        super().__init__(**kw)
        self._t = 0
        self.bind(pos=self.redraw, size=self.redraw,
                  level=self.redraw, active=self.redraw)
        Clock.schedule_interval(self._tick, 1/25)

    def _tick(self, dt):
        self._t += dt * 2
        self.redraw()

    def redraw(self, *_):
        self.canvas.clear()
        cx, cy = self.center_x, self.center_y
        r = min(self.width, self.height) * 0.38
        if r <= 0:
            return

        with self.canvas:
            # Glow
            if self.active and self.level > 0.02:
                a = self.level
                Color(
                    C_CYAN[0]*(1-a) + C_RED[0]*a,
                    C_CYAN[1]*(1-a) + C_RED[1]*a,
                    C_CYAN[2]*(1-a) + C_RED[2]*a,
                    0.08 + a*0.25
                )
                gr = r + 25 + a*35
                Ellipse(pos=(cx-gr, cy-gr), size=(gr*2, gr*2))

            # Inner fill
            if self.active:
                Color(C_CYAN[0], C_CYAN[1], C_CYAN[2], 0.1 + self.level*0.25)
            else:
                Color(1, 1, 1, 0.06 + 0.03 * math.sin(self._t))
            Ellipse(pos=(cx-r, cy-r), size=(r*2, r*2))

            # Ring
            if self.active:
                a = self.level
                Color(
                    C_CYAN[0]*(1-a)+C_RED[0]*a,
                    C_CYAN[1]*(1-a)+C_RED[1]*a,
                    C_CYAN[2]*(1-a)+C_RED[2]*a, 0.85
                )
            else:
                Color(*C_BORDER)
            Line(circle=(cx, cy, r), width=dp(2))

            # Arc
            if self.active and self.level > 0.01:
                a = self.level
                Color(
                    C_CYAN[0]*(1-a)+C_RED[0]*a,
                    C_CYAN[1]*(1-a)+C_RED[1]*a,
                    C_CYAN[2]*(1-a)+C_RED[2]*a, 0.9
                )
                Line(circle=(cx, cy, r+dp(7), 90, 90+a*360), width=dp(3))

            # Segments
            for i in range(12):
                sa = i * 30
                sl = (i+1) / 12
                if self.active and self.level >= sl:
                    if sl > 0.8: Color(*C_RED[:3], 0.85)
                    elif sl > 0.5: Color(1, 0.75, 0, 0.75)
                    else: Color(*C_CYAN[:3], 0.65)
                else:
                    Color(1, 1, 1, 0.04)
                Line(circle=(cx, cy, r+dp(16), sa+2, sa+25), width=dp(4))


# ══════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════
class DMicApp(App):

    def __init__(self, **kw):
        super().__init__(**kw)
        self.title = 'D-MIC'
        self.engine = AudioEngine()
        self.wakelock = WakeLockMgr()
        self._streaming = False
        self._log_lines = []
        log("DMicApp created")

    def build(self):
        log("build() starting...")

        # Safe window color
        try:
            if Window is not None:
                Window.clearcolor = C_BG
        except: pass

        root = FloatLayout()

        # Background
        with root.canvas.before:
            Color(*C_BG)
            self._bg = Rectangle(size=(500, 900))
        try:
            if Window is not None:
                def _resize(*a):
                    self._bg.size = Window.size
                Window.bind(size=_resize)
                self._bg.size = Window.size
        except: pass

        # ── Header ──
        root.add_widget(Label(
            text='D-MIC', font_size=sp(40), bold=True, color=C_CYAN,
            size_hint=(1, None), height=dp(50),
            pos_hint={'center_x': .5, 'top': .97}
        ))
        root.add_widget(Label(
            text='Phone > Laptop Microphone', font_size=sp(11), color=C_MID,
            size_hint=(1, None), height=dp(20),
            pos_hint={'center_x': .5, 'top': .91}
        ))

        # ── VU Meter ──
        self.vu = VUMeter(
            size_hint=(.7, .25),
            pos_hint={'center_x': .5, 'center_y': .65}
        )
        root.add_widget(self.vu)

        self.mic_lbl = Label(
            text='MIC\nOFF', font_size=sp(22), bold=True,
            color=C_DIM, halign='center', valign='middle',
            size_hint=(None, None), size=(dp(100), dp(70)),
            pos_hint={'center_x': .5, 'center_y': .65}
        )
        root.add_widget(self.mic_lbl)

        # ── Status ──
        self.status = Label(
            text='Enter server IP and tap STREAM', font_size=sp(11),
            color=C_DIM, size_hint=(1, None), height=dp(20),
            pos_hint={'center_x': .5, 'center_y': .50}
        )
        root.add_widget(self.status)

        # ── On-screen log ──
        self.log_lbl = Label(
            text='', font_size=sp(8), color=[1, 1, 1, 0.2],
            halign='left', valign='top',
            size_hint=(.92, None), height=dp(48),
            pos_hint={'center_x': .5, 'center_y': .44}
        )
        self.log_lbl.bind(size=self.log_lbl.setter('text_size'))
        root.add_widget(self.log_lbl)

        # ── Input card ──
        card = BoxLayout(
            orientation='vertical', spacing=dp(8),
            padding=[dp(20), dp(12), dp(20), dp(12)],
            size_hint=(.88, None), height=dp(130),
            pos_hint={'center_x': .5, 'center_y': .28}
        )
        with card.canvas.before:
            Color(*C_CARD)
            self._cr = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(16)])
            Color(*C_BORDER)
            self._cb = Line(rounded_rectangle=(*card.pos, *card.size, dp(16)), width=1)
        card.bind(pos=self._upd_card, size=self._upd_card)

        # IP row
        ip_r = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(48))
        ip_r.add_widget(Label(
            text='IP', font_size=sp(14), bold=True,
            color=C_CYAN, size_hint_x=None, width=dp(32)
        ))
        self.ip_in = TextInput(
            hint_text='192.168.X.X', multiline=False, font_size=sp(16),
            background_color=[.04, .04, .06, 1], foreground_color=C_WHITE,
            hint_text_color=C_DIM, cursor_color=C_CYAN,
            padding=[dp(12)]*4
        )
        ip_r.add_widget(self.ip_in)
        card.add_widget(ip_r)

        # Port row
        pt_r = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(38))
        pt_r.add_widget(Label(
            text='PORT', font_size=sp(11), bold=True,
            color=C_MID, size_hint_x=None, width=dp(42)
        ))
        self.port_in = TextInput(
            text='50005', multiline=False, font_size=sp(14),
            background_color=[.04, .04, .06, 1], foreground_color=[1, 1, 1, .7],
            hint_text_color=C_DIM, cursor_color=C_PURPLE,
            padding=[dp(10)]*4, input_filter='int'
        )
        pt_r.add_widget(self.port_in)
        card.add_widget(pt_r)
        root.add_widget(card)

        # ── Stream button ──
        self.btn = Button(
            text='STREAM', font_size=sp(18), bold=True,
            size_hint=(.88, None), height=dp(54),
            pos_hint={'center_x': .5, 'center_y': .11},
            background_normal='', background_color=[0, 0, 0, 0],
            color=[0, 0, 0, 1]
        )
        with self.btn.canvas.before:
            Color(*C_CYAN)
            self._br = RoundedRectangle(
                pos=self.btn.pos, size=self.btn.size, radius=[dp(14)]
            )
        self.btn.bind(pos=self._upd_btn, size=self._upd_btn)
        self.btn.bind(on_release=self._on_btn)
        root.add_widget(self.btn)

        # ── Footer ──
        root.add_widget(Label(
            text='Developed by Soham', font_size=sp(9),
            color=[1, 1, 1, .12], size_hint=(1, None), height=dp(16),
            pos_hint={'center_x': .5, 'y': .01}
        ))

        # ── Periodic VU update ──
        Clock.schedule_interval(self._tick, 1/20)

        log("build() complete ✓")
        self._ui_log("Ready. Make sure mic permission is enabled.")
        return root

    # ── UI log (thread-safe) ──
    @mainthread
    def _ui_log(self, msg):
        log(msg)
        self._log_lines.append(msg)
        self._log_lines = self._log_lines[-4:]
        try:
            self.log_lbl.text = '\n'.join(self._log_lines)
        except: pass

    # ── Layout updates ──
    def _upd_card(self, w, *_):
        self._cr.pos = w.pos; self._cr.size = w.size
        self._cb.rounded_rectangle = (*w.pos, *w.size, dp(16))

    def _upd_btn(self, w, *_):
        self._br.pos = w.pos; self._br.size = w.size

    # ── VU tick (runs on main thread) ──
    def _tick(self, dt):
        lv = self.engine.vu_level
        self.vu.level = lv
        self.vu.active = self._streaming
        if self._streaming:
            self.mic_lbl.text = f'MIC\n{int(lv * 100)}%'
            self.mic_lbl.color = C_CYAN if lv < 0.7 else C_RED

    # ── Button handler ──
    def _on_btn(self, *args):
        log(f"BUTTON PRESSED | streaming={self._streaming}")
        self._ui_log("Button pressed")
        try:
            if self._streaming:
                self._do_stop()
            else:
                self._do_start()
        except Exception as e:
            log(f"Button error: {e}")
            traceback.print_exc()
            self._ui_log(f"Error: {e}")

    def _do_start(self):
        ip = self.ip_in.text.strip()
        port_s = self.port_in.text.strip() or '50005'
        port = int(port_s)

        log(f"_do_start: ip={ip} port={port}")

        if not ip:
            self._set_status('Enter server IP!', C_RED)
            self._ui_log("No IP entered")
            return

        # Check permission first
        if IS_ANDROID:
            ok = check_mic_permission()
            if not ok:
                self._set_status('Mic permission DENIED!', C_RED)
                self._ui_log("Go to Settings > Apps > Pydroid 3")
                self._ui_log("> Permissions > Microphone > Allow")
                return

        self._ui_log(f"Connecting to {ip}:{port}...")
        self._set_status(f'Starting...', C_ORANGE)

        # Start everything
        self.wakelock.acquire()
        self.engine.start(ip, port)
        self._streaming = True

        self._set_status(f'Streaming to {ip}:{port}', C_GREEN)
        self.btn.text = 'STOP'
        self._set_btn_color(C_RED)
        self._ui_log("Streaming started!")

    def _do_stop(self):
        log("_do_stop()")
        self._ui_log("Stopping...")
        self.engine.stop()
        self.wakelock.release()
        self._streaming = False
        self._set_status('Stopped', C_DIM)
        self.btn.text = 'STREAM'
        self.mic_lbl.text = 'MIC\nOFF'
        self.mic_lbl.color = C_DIM
        self._set_btn_color(C_CYAN)
        self._ui_log("Stopped")

    @mainthread
    def _set_status(self, text, color):
        self.status.text = text
        self.status.color = color

    def _set_btn_color(self, c):
        self.btn.canvas.before.clear()
        with self.btn.canvas.before:
            Color(*c)
            self._br = RoundedRectangle(
                pos=self.btn.pos, size=self.btn.size, radius=[dp(14)]
            )

    def on_stop(self):
        log("App closing")
        try: self._do_stop()
        except: pass


# ══════════════════════════════════════════
log("Creating DMicApp...")
if __name__ == '__main__':
    DMicApp().run()
