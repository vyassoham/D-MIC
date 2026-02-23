"""
D-MIC Client v2 - Phone Microphone Streamer
============================================
Run on Pydroid 3 on your Android phone.
Streams mic audio to your laptop over UDP.
Background-safe with WakeLock.

Install in Pydroid:
  pip install kivy pyjnius

Developed by Soham
"""

import os
import sys
import struct
import socket
import threading
import time
import math

# ─────────────────────────────────────────────
# Platform detection
# ─────────────────────────────────────────────
IS_ANDROID = False
_activity = None

try:
    from jnius import autoclass, cast, jarray
    from android import mActivity
    _activity = mActivity
    IS_ANDROID = True
    print("[D-MIC] Running on Android ✓")
except ImportError:
    print("[D-MIC] Running on PC (mock mode)")

# ─────────────────────────────────────────────
# Kivy env (before any kivy import)
# ─────────────────────────────────────────────
if not IS_ANDROID:
    os.environ.setdefault('KIVY_GL_BACKEND', 'angle_sdl2')

from kivy.app import App
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.utils import get_color_from_hex
from kivy.metrics import dp, sp
from kivy.properties import NumericProperty, BooleanProperty, StringProperty

# ─────────────────────────────────────────────
# Colors
# ─────────────────────────────────────────────
C_BG       = get_color_from_hex('#0A0A0F')
C_CARD     = get_color_from_hex('#12121A')
C_BORDER   = get_color_from_hex('#2A2A3E')
C_CYAN     = get_color_from_hex('#00E5FF')
C_PURPLE   = get_color_from_hex('#7C4DFF')
C_RED      = get_color_from_hex('#FF1744')
C_GREEN    = get_color_from_hex('#00E676')
C_WHITE    = [1, 1, 1, 1]
C_DIM      = [1, 1, 1, 0.3]
C_MID      = [1, 1, 1, 0.5]


# ═══════════════════════════════════════════════
#  PERMISSIONS (Pydroid 3 compatible)
# ═══════════════════════════════════════════════
def ensure_mic_permission():
    """Request RECORD_AUDIO permission using raw Android API via jnius."""
    if not IS_ANDROID:
        return True

    try:
        Context = autoclass('android.content.Context')
        PackageManager = autoclass('android.content.pm.PackageManager')

        # Check current status
        check = _activity.checkSelfPermission('android.permission.RECORD_AUDIO')
        if check == PackageManager.PERMISSION_GRANTED:
            print("[D-MIC] Mic permission: already granted ✓")
            return True

        # Build Java String[] with the permission
        String = autoclass('java.lang.String')
        perm_array = jarray('Ljava/lang/String;')(['android.permission.RECORD_AUDIO'])

        # Request
        print("[D-MIC] Requesting mic permission...")
        _activity.requestPermissions(perm_array, 1001)

        # Poll until granted or timeout (15 sec)
        for i in range(30):
            time.sleep(0.5)
            check = _activity.checkSelfPermission('android.permission.RECORD_AUDIO')
            if check == PackageManager.PERMISSION_GRANTED:
                print("[D-MIC] Mic permission: granted ✓")
                return True

        print("[D-MIC] Mic permission: DENIED ✗")
        return False

    except Exception as e:
        print(f"[D-MIC] Permission error: {e}")
        return False


# ═══════════════════════════════════════════════
#  AUDIO ENGINE (Android native via jnius)
# ═══════════════════════════════════════════════
class AudioEngine:
    """
    Captures mic audio via Android AudioRecord and streams raw PCM
    over UDP. Uses jarray for proper Java array interop.
    """

    SAMPLE_RATE  = 44100
    NUM_SHORTS   = 1024        # shorts per read (~23ms at 44100)
    BUFFER_BYTES = 1024 * 2    # 2 bytes per short

    def __init__(self):
        self.streaming = False
        self.vu_level  = 0.0
        self._thread   = None

    def start(self, ip, port):
        if self.streaming:
            return
        self.streaming = True
        self._thread = threading.Thread(
            target=self._run, args=(ip, port), daemon=True
        )
        self._thread.start()

    def stop(self):
        self.streaming = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        self.vu_level = 0.0

    # ── Android capture ──────────────────────
    def _run(self, ip, port):
        if not IS_ANDROID:
            self._run_mock(ip, port)
            return

        recorder = None
        sock = None
        try:
            AudioRecord   = autoclass('android.media.AudioRecord')
            AudioFormat   = autoclass('android.media.AudioFormat')
            MediaRecorder = autoclass('android.media.MediaRecorder')

            CH_MONO   = AudioFormat.CHANNEL_IN_MONO
            PCM16     = AudioFormat.ENCODING_PCM_16BIT
            MIC_SRC   = MediaRecorder.AudioSource.MIC

            # Buffer
            min_buf = AudioRecord.getMinBufferSize(self.SAMPLE_RATE, CH_MONO, PCM16)
            buf_sz  = max(min_buf * 2, self.BUFFER_BYTES * 4)
            print(f"[D-MIC] AudioRecord buffer: {buf_sz} bytes (min={min_buf})")

            # Create recorder
            recorder = AudioRecord(MIC_SRC, self.SAMPLE_RATE, CH_MONO, PCM16, buf_sz)
            if recorder.getState() != AudioRecord.STATE_INITIALIZED:
                print("[D-MIC] ERROR: AudioRecord not initialized!")
                print("[D-MIC] Check mic permission or another app using mic.")
                self.streaming = False
                return

            # UDP socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            addr = (ip, port)

            # Java short[] buffer via jarray
            java_shorts = jarray('h')(self.NUM_SHORTS)

            recorder.startRecording()
            print(f"[D-MIC] ✓ Streaming to {ip}:{port} @ {self.SAMPLE_RATE}Hz")

            pkt_count = 0
            while self.streaming:
                try:
                    n = recorder.read(java_shorts, 0, self.NUM_SHORTS)

                    if n > 0:
                        # Pack to little-endian bytes
                        data = struct.pack(f'<{n}h', *java_shorts[:n])
                        sock.sendto(data, addr)

                        # VU meter (RMS)
                        sq_sum = 0
                        for i in range(n):
                            sq_sum += java_shorts[i] * java_shorts[i]
                        rms = math.sqrt(sq_sum / n)
                        self.vu_level = min(1.0, rms / 12000.0)

                        pkt_count += 1
                        if pkt_count % 200 == 0:
                            print(f"[D-MIC] Sent {pkt_count} packets, VU={self.vu_level:.2f}")

                    elif n == 0:
                        time.sleep(0.005)
                    else:
                        print(f"[D-MIC] AudioRecord.read error: {n}")
                        time.sleep(0.02)

                except Exception as ex:
                    print(f"[D-MIC] Send error: {ex}")
                    time.sleep(0.01)

        except Exception as ex:
            print(f"[D-MIC] Engine error: {ex}")
            import traceback; traceback.print_exc()
        finally:
            self.streaming = False
            try:
                if recorder:
                    recorder.stop()
                    recorder.release()
                    print("[D-MIC] AudioRecord released")
            except: pass
            try:
                if sock: sock.close()
            except: pass
            print("[D-MIC] Audio engine stopped")

    # ── PC mock (sine wave) ──────────────────
    def _run_mock(self, ip, port):
        print(f"[D-MIC] Mock streaming to {ip}:{port}")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        addr = (ip, port)
        t = 0
        while self.streaming:
            buf = []
            for _ in range(1024):
                v = int(8000 * math.sin(2 * math.pi * 440 * t / 44100))
                buf.append(struct.pack('<h', v))
                t += 1
            try:
                sock.sendto(b''.join(buf), addr)
            except: pass
            self.vu_level = 0.3 + 0.2 * math.sin(time.time() * 3)
            time.sleep(0.023)
        sock.close()
        self.vu_level = 0.0


# ═══════════════════════════════════════════════
#  WAKELOCK (keep CPU alive in background)
# ═══════════════════════════════════════════════
class WakeLockManager:
    def __init__(self):
        self._lock = None

    def acquire(self):
        if not IS_ANDROID: return
        try:
            Context = autoclass('android.content.Context')
            PowerManager = autoclass('android.os.PowerManager')
            pm = cast('android.os.PowerManager',
                       _activity.getSystemService(Context.POWER_SERVICE))
            self._lock = pm.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK, 'dmic:audio'
            )
            self._lock.acquire()
            print("[D-MIC] WakeLock acquired ✓")
        except Exception as e:
            print(f"[D-MIC] WakeLock error: {e}")

    def release(self):
        if not IS_ANDROID: return
        try:
            if self._lock and self._lock.isHeld():
                self._lock.release()
                print("[D-MIC] WakeLock released")
        except: pass
        self._lock = None


# ═══════════════════════════════════════════════
#  VU METER WIDGET
# ═══════════════════════════════════════════════
class VUMeter(Widget):
    level  = NumericProperty(0.0)
    active = BooleanProperty(False)

    def __init__(self, **kw):
        super().__init__(**kw)
        self._t = 0
        self.bind(pos=self.redraw, size=self.redraw,
                  level=self.redraw, active=self.redraw)
        Clock.schedule_interval(self._tick, 1/30)

    def _tick(self, dt):
        self._t += dt * 2
        self.redraw()

    def redraw(self, *_):
        self.canvas.clear()
        cx, cy = self.center_x, self.center_y
        r = min(self.width, self.height) * 0.38

        with self.canvas:
            # ── Glow effect ──
            if self.active and self.level > 0.02:
                a = self.level
                cr = C_CYAN[0]*(1-a) + C_RED[0]*a
                cg = C_CYAN[1]*(1-a) + C_RED[1]*a
                cb = C_CYAN[2]*(1-a) + C_RED[2]*a
                Color(cr, cg, cb, 0.08 + a*0.25)
                gr = r + 25 + a*35
                Ellipse(pos=(cx-gr, cy-gr), size=(gr*2, gr*2))

            # ── Inner circle ──
            if self.active:
                a = self.level
                Color(C_CYAN[0], C_CYAN[1], C_CYAN[2], 0.1 + a*0.25)
            else:
                p = 0.06 + 0.03 * math.sin(self._t)
                Color(1, 1, 1, p)
            Ellipse(pos=(cx-r, cy-r), size=(r*2, r*2))

            # ── Main ring ──
            if self.active:
                a = self.level
                Color(C_CYAN[0]*(1-a)+C_RED[0]*a,
                      C_CYAN[1]*(1-a)+C_RED[1]*a,
                      C_CYAN[2]*(1-a)+C_RED[2]*a, 0.85)
            else:
                Color(*C_BORDER)
            Line(circle=(cx, cy, r), width=dp(2))

            # ── Level arc ──
            if self.active and self.level > 0.01:
                a = self.level
                Color(C_CYAN[0]*(1-a)+C_RED[0]*a,
                      C_CYAN[1]*(1-a)+C_RED[1]*a,
                      C_CYAN[2]*(1-a)+C_RED[2]*a, 0.9)
                Line(circle=(cx, cy, r+dp(7), 90, 90+a*360), width=dp(3))

            # ── Segment ring (12 segments) ──
            for i in range(12):
                seg_a = i * 30
                seg_lv = (i+1) / 12
                if self.active and self.level >= seg_lv:
                    if seg_lv > 0.8:
                        Color(*C_RED[:3], 0.85)
                    elif seg_lv > 0.5:
                        Color(1, 0.75, 0, 0.75)
                    else:
                        Color(*C_CYAN[:3], 0.65)
                else:
                    Color(1, 1, 1, 0.04)
                Line(circle=(cx, cy, r+dp(16), seg_a+2, seg_a+25),
                     width=dp(4))


# ═══════════════════════════════════════════════
#  MAIN APPLICATION
# ═══════════════════════════════════════════════
class DMicApp(App):

    def __init__(self, **kw):
        super().__init__(**kw)
        self.title = 'D-MIC'
        self.engine = AudioEngine()
        self.wakelock = WakeLockManager()
        self._streaming = False

    def build(self):
        if Window:
            Window.clearcolor = C_BG

        root = FloatLayout()
        with root.canvas.before:
            Color(*C_BG)
            self._bg = Rectangle(size=Window.size if Window else (400,700))
        if Window:
            Window.bind(size=lambda *_: setattr(self._bg, 'size', Window.size))

        # ── Header ──
        root.add_widget(Label(
            text='D-MIC', font_size=sp(40), bold=True, color=C_CYAN,
            size_hint=(1, None), height=dp(50),
            pos_hint={'center_x':.5, 'top':.97}
        ))
        root.add_widget(Label(
            text='Phone → Laptop Microphone', font_size=sp(11), color=C_MID,
            size_hint=(1, None), height=dp(20),
            pos_hint={'center_x':.5, 'top':.91}
        ))

        # ── VU Meter ──
        self.vu = VUMeter(
            size_hint=(.7, .28),
            pos_hint={'center_x':.5, 'center_y':.64}
        )
        root.add_widget(self.vu)

        self.mic_lbl = Label(
            text='MIC\nOFF', font_size=sp(22), bold=True,
            color=C_DIM, halign='center',
            size_hint=(None, None), size=(dp(100), dp(70)),
            pos_hint={'center_x':.5, 'center_y':.64}
        )
        self.mic_lbl.bind(size=self.mic_lbl.setter('text_size'))
        root.add_widget(self.mic_lbl)

        # ── Status ──
        self.status = Label(
            text='Ready — enter server IP below', font_size=sp(11),
            color=C_DIM, size_hint=(1, None), height=dp(20),
            pos_hint={'center_x':.5, 'center_y':.48}
        )
        root.add_widget(self.status)

        # ── Input card ──
        card = BoxLayout(
            orientation='vertical', spacing=dp(10),
            padding=[dp(20), dp(14), dp(20), dp(14)],
            size_hint=(.88, None), height=dp(135),
            pos_hint={'center_x':.5, 'center_y':.30}
        )
        with card.canvas.before:
            Color(*C_CARD)
            self._cr = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(16)])
            Color(*C_BORDER)
            self._cb = Line(rounded_rectangle=(*card.pos, *card.size, dp(16)), width=1)
        card.bind(pos=self._upd_card, size=self._upd_card)

        # IP row
        ip_r = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(48))
        ip_r.add_widget(Label(text='IP', font_size=sp(14), bold=True,
                              color=C_CYAN, size_hint_x=None, width=dp(32)))
        self.ip_in = TextInput(
            hint_text='192.168.X.X', multiline=False, font_size=sp(16),
            background_color=[.04,.04,.06,1], foreground_color=C_WHITE,
            hint_text_color=C_DIM, cursor_color=C_CYAN,
            padding=[dp(12)]*4
        )
        ip_r.add_widget(self.ip_in)
        card.add_widget(ip_r)

        # Port row
        pt_r = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(40))
        pt_r.add_widget(Label(text='PORT', font_size=sp(11), bold=True,
                              color=C_MID, size_hint_x=None, width=dp(42)))
        self.port_in = TextInput(
            text='50005', multiline=False, font_size=sp(14),
            background_color=[.04,.04,.06,1], foreground_color=[1,1,1,.7],
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
            pos_hint={'center_x':.5, 'center_y':.12},
            background_normal='', background_color=[0,0,0,0],
            color=[0,0,0,1]
        )
        with self.btn.canvas.before:
            Color(*C_CYAN)
            self._br = RoundedRectangle(pos=self.btn.pos, size=self.btn.size, radius=[dp(14)])
        self.btn.bind(pos=self._upd_btn, size=self._upd_btn)
        self.btn.bind(on_press=self._toggle)
        root.add_widget(self.btn)

        # ── Footer ──
        root.add_widget(Label(
            text='Developed by Soham', font_size=sp(9),
            color=[1,1,1,.12], size_hint=(1, None), height=dp(16),
            pos_hint={'center_x':.5, 'y':.01}
        ))

        # ── Update loop ──
        Clock.schedule_interval(self._tick, 1/20)
        return root

    # ── Layout helpers ──
    def _upd_card(self, w, *_):
        self._cr.pos = w.pos; self._cr.size = w.size
        self._cb.rounded_rectangle = (*w.pos, *w.size, dp(16))

    def _upd_btn(self, w, *_):
        self._br.pos = w.pos; self._br.size = w.size

    # ── VU tick ──
    def _tick(self, dt):
        lv = self.engine.vu_level
        self.vu.level = lv
        self.vu.active = self._streaming
        if self._streaming:
            pct = int(lv * 100)
            self.mic_lbl.text = f'MIC\n{pct}%'
            self.mic_lbl.color = C_CYAN if lv < 0.7 else C_RED

    # ── Toggle streaming ──
    def _toggle(self, *_):
        if self._streaming:
            self._stop()
        else:
            self._start()

    def _start(self):
        ip = self.ip_in.text.strip()
        if not ip:
            self.status.text = '⚠ Enter server IP!'
            self.status.color = C_RED
            return

        port = int(self.port_in.text.strip() or '50005')

        # Permission
        if IS_ANDROID:
            self.status.text = 'Requesting mic permission...'
            self.status.color = C_MID
            # Run permission in thread so UI doesn't freeze
            threading.Thread(
                target=self._start_with_permission,
                args=(ip, port), daemon=True
            ).start()
        else:
            self._begin_stream(ip, port)

    def _start_with_permission(self, ip, port):
        ok = ensure_mic_permission()
        if ok:
            Clock.schedule_once(lambda dt: self._begin_stream(ip, port), 0)
        else:
            Clock.schedule_once(lambda dt: self._perm_denied(), 0)

    def _perm_denied(self):
        self.status.text = '✗ Mic permission denied! Check settings.'
        self.status.color = C_RED

    def _begin_stream(self, ip, port):
        self.wakelock.acquire()
        self.engine.start(ip, port)
        self._streaming = True
        self.status.text = f'● Streaming to {ip}:{port}'
        self.status.color = C_GREEN
        self.btn.text = 'STOP'
        self._set_btn_color(C_RED)

    def _stop(self):
        self.engine.stop()
        self.wakelock.release()
        self._streaming = False
        self.status.text = 'Stopped'
        self.status.color = C_DIM
        self.btn.text = 'STREAM'
        self.mic_lbl.text = 'MIC\nOFF'
        self.mic_lbl.color = C_DIM
        self._set_btn_color(C_CYAN)

    def _set_btn_color(self, c):
        self.btn.canvas.before.clear()
        with self.btn.canvas.before:
            Color(*c)
            self._br = RoundedRectangle(
                pos=self.btn.pos, size=self.btn.size, radius=[dp(14)])

    def on_stop(self):
        self._stop()


# ═══════════════════════════════════════════════
if __name__ == '__main__':
    DMicApp().run()
