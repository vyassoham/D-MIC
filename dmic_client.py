"""
D-MIC Client v3 - Phone Microphone Streamer
============================================
Run on Pydroid 3. Streams mic audio over UDP.

Install in Pydroid:  pip install kivy pyjnius

Developed by Soham
"""

print("[D-MIC] ===== STARTING D-MIC v3 =====")

import os
import sys
import struct
import socket
import threading
import time
import math

print("[D-MIC] Basic imports OK")

# ─────────────────────────────────────────────
# Platform detection
# ─────────────────────────────────────────────
IS_ANDROID = False
_activity = None
jarray = None

try:
    from jnius import autoclass, cast
    from jnius import jarray as _jarray
    jarray = _jarray
    print("[D-MIC] jnius imported OK")
    try:
        from android import mActivity
        _activity = mActivity
        IS_ANDROID = True
        print("[D-MIC] ✓ Running on ANDROID")
    except ImportError:
        print("[D-MIC] jnius found but no android module - hybrid mode")
except ImportError:
    print("[D-MIC] No jnius - running on PC (mock mode)")

# ─────────────────────────────────────────────
# Kivy env
# ─────────────────────────────────────────────
if not IS_ANDROID:
    os.environ.setdefault('KIVY_GL_BACKEND', 'angle_sdl2')

print("[D-MIC] Importing kivy...")

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
from kivy.properties import NumericProperty, BooleanProperty

print("[D-MIC] Kivy imports OK")

# ─────────────────────────────────────────────
# Colors
# ─────────────────────────────────────────────
C_BG     = get_color_from_hex('#0A0A0F')
C_CARD   = get_color_from_hex('#12121A')
C_BORDER = get_color_from_hex('#2A2A3E')
C_CYAN   = get_color_from_hex('#00E5FF')
C_PURPLE = get_color_from_hex('#7C4DFF')
C_RED    = get_color_from_hex('#FF1744')
C_GREEN  = get_color_from_hex('#00E676')
C_WHITE  = [1, 1, 1, 1]
C_DIM    = [1, 1, 1, 0.3]
C_MID    = [1, 1, 1, 0.5]


# ═══════════════════════════════════════════════
#  PERMISSIONS
# ═══════════════════════════════════════════════
def ensure_mic_permission():
    print("[D-MIC] ensure_mic_permission() called")
    if not IS_ANDROID:
        print("[D-MIC] Not Android, skipping permission")
        return True
    try:
        print("[D-MIC] Checking mic permission...")
        PackageManager = autoclass('android.content.pm.PackageManager')
        perm_str = 'android.permission.RECORD_AUDIO'

        check = _activity.checkSelfPermission(perm_str)
        print(f"[D-MIC] Current permission status: {check} (0=granted)")

        if check == PackageManager.PERMISSION_GRANTED:
            print("[D-MIC] ✓ Mic already granted")
            return True

        print("[D-MIC] Requesting permission dialog...")
        if jarray:
            perm_array = jarray('Ljava/lang/String;')([perm_str])
            _activity.requestPermissions(perm_array, 1001)
        else:
            print("[D-MIC] No jarray, trying direct call")
            _activity.requestPermissions([perm_str], 1001)

        for i in range(30):
            time.sleep(0.5)
            check = _activity.checkSelfPermission(perm_str)
            if check == PackageManager.PERMISSION_GRANTED:
                print(f"[D-MIC] ✓ Permission granted after {i*0.5}s")
                return True
            if i % 4 == 0:
                print(f"[D-MIC] Waiting for permission... ({i*0.5}s)")

        print("[D-MIC] ✗ Permission denied after 15s timeout")
        return False
    except Exception as e:
        print(f"[D-MIC] Permission ERROR: {e}")
        import traceback; traceback.print_exc()
        return False


# ═══════════════════════════════════════════════
#  AUDIO ENGINE
# ═══════════════════════════════════════════════
class AudioEngine:
    SAMPLE_RATE = 44100
    NUM_SHORTS  = 1024

    def __init__(self):
        self.streaming = False
        self.vu_level  = 0.0
        self._thread   = None
        print("[D-MIC] AudioEngine created")

    def start(self, ip, port):
        print(f"[D-MIC] AudioEngine.start({ip}, {port})")
        if self.streaming:
            print("[D-MIC] Already streaming, ignoring")
            return
        self.streaming = True
        self._thread = threading.Thread(
            target=self._safe_run, args=(ip, port), daemon=True
        )
        self._thread.start()
        print("[D-MIC] Audio thread started")

    def stop(self):
        print("[D-MIC] AudioEngine.stop()")
        self.streaming = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        self.vu_level = 0.0
        print("[D-MIC] AudioEngine stopped")

    def _safe_run(self, ip, port):
        """Wrapper with full error catching"""
        try:
            if IS_ANDROID:
                self._run_android(ip, port)
            else:
                self._run_mock(ip, port)
        except Exception as e:
            print(f"[D-MIC] FATAL engine error: {e}")
            import traceback; traceback.print_exc()
            self.streaming = False
            self.vu_level = 0.0

    def _run_android(self, ip, port):
        print("[D-MIC] _run_android starting...")
        recorder = None
        sock = None

        try:
            print("[D-MIC] Loading AudioRecord classes...")
            AudioRecord   = autoclass('android.media.AudioRecord')
            AudioFormat   = autoclass('android.media.AudioFormat')
            MediaRecorder = autoclass('android.media.MediaRecorder')
            print("[D-MIC] Classes loaded OK")

            CH_MONO = AudioFormat.CHANNEL_IN_MONO
            PCM16   = AudioFormat.ENCODING_PCM_16BIT
            MIC_SRC = MediaRecorder.AudioSource.MIC

            min_buf = AudioRecord.getMinBufferSize(self.SAMPLE_RATE, CH_MONO, PCM16)
            buf_sz  = max(min_buf * 4, 8192)
            print(f"[D-MIC] Buffer: min={min_buf}, using={buf_sz}")

            print("[D-MIC] Creating AudioRecord...")
            recorder = AudioRecord(MIC_SRC, self.SAMPLE_RATE, CH_MONO, PCM16, buf_sz)
            state = recorder.getState()
            print(f"[D-MIC] AudioRecord state={state} (1=initialized)")

            if state != AudioRecord.STATE_INITIALIZED:
                print("[D-MIC] ✗ AudioRecord FAILED to init!")
                print("[D-MIC]   → Check mic permission")
                print("[D-MIC]   → Check no other app using mic")
                self.streaming = False
                return

            print("[D-MIC] Creating UDP socket...")
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            addr = (ip, port)
            print(f"[D-MIC] Socket ready → {addr}")

            print("[D-MIC] Creating jarray short buffer...")
            if jarray:
                java_buf = jarray('h')(self.NUM_SHORTS)
                print(f"[D-MIC] jarray('h')({self.NUM_SHORTS}) created OK")
            else:
                print("[D-MIC] ✗ No jarray available!")
                self.streaming = False
                return

            print("[D-MIC] Starting recording...")
            recorder.startRecording()
            rec_state = recorder.getRecordingState()
            print(f"[D-MIC] Recording state={rec_state} (3=recording)")

            if rec_state != 3:
                print("[D-MIC] ✗ Recording did not start!")
                self.streaming = False
                return

            print(f"[D-MIC] ★ STREAMING to {ip}:{port} @ {self.SAMPLE_RATE}Hz ★")

            pkt = 0
            errors = 0
            while self.streaming:
                try:
                    n = recorder.read(java_buf, 0, self.NUM_SHORTS)

                    if n > 0:
                        # Pack shorts → bytes
                        data = struct.pack(f'<{n}h', *java_buf[:n])
                        sock.sendto(data, addr)

                        # VU (fast approximation)
                        peak = 0
                        for i in range(0, n, 8):  # sample every 8th
                            v = abs(java_buf[i])
                            if v > peak:
                                peak = v
                        self.vu_level = min(1.0, peak / 12000.0)

                        pkt += 1
                        if pkt <= 3 or pkt % 100 == 0:
                            print(f"[D-MIC] PKT #{pkt} | {n} shorts | VU={self.vu_level:.2f} | peak={peak}")

                    elif n == 0:
                        time.sleep(0.003)
                    else:
                        errors += 1
                        print(f"[D-MIC] Read error: {n} (count={errors})")
                        if errors > 10:
                            print("[D-MIC] Too many errors, stopping")
                            break
                        time.sleep(0.01)

                except Exception as ex:
                    print(f"[D-MIC] Loop error: {ex}")
                    time.sleep(0.01)

            print(f"[D-MIC] Stream ended. Total packets: {pkt}")

        except Exception as ex:
            print(f"[D-MIC] Android engine error: {ex}")
            import traceback; traceback.print_exc()

        finally:
            self.streaming = False
            if recorder:
                try:
                    recorder.stop()
                    recorder.release()
                    print("[D-MIC] AudioRecord released")
                except Exception as e:
                    print(f"[D-MIC] Release error: {e}")
            if sock:
                try: sock.close()
                except: pass
            print("[D-MIC] Engine cleanup done")

    def _run_mock(self, ip, port):
        print(f"[D-MIC] Mock mode → {ip}:{port}")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        addr = (ip, port)
        t = 0
        pkt = 0
        while self.streaming:
            buf = []
            for _ in range(1024):
                v = int(8000 * math.sin(2 * math.pi * 440 * t / 44100))
                buf.append(struct.pack('<h', v))
                t += 1
            try:
                sock.sendto(b''.join(buf), addr)
                pkt += 1
            except: pass
            self.vu_level = 0.3 + 0.2 * math.sin(time.time() * 3)
            if pkt <= 3 or pkt % 100 == 0:
                print(f"[D-MIC] Mock PKT #{pkt}")
            time.sleep(0.023)
        sock.close()
        self.vu_level = 0.0
        print(f"[D-MIC] Mock stopped after {pkt} packets")


# ═══════════════════════════════════════════════
#  WAKELOCK
# ═══════════════════════════════════════════════
class WakeLockMgr:
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
                PowerManager.PARTIAL_WAKE_LOCK, 'dmic:audio')
            self._lock.acquire()
            print("[D-MIC] ✓ WakeLock acquired")
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
#  VU METER
# ═══════════════════════════════════════════════
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

        with self.canvas:
            if self.active and self.level > 0.02:
                a = self.level
                cr = C_CYAN[0]*(1-a) + C_RED[0]*a
                cg = C_CYAN[1]*(1-a) + C_RED[1]*a
                cb = C_CYAN[2]*(1-a) + C_RED[2]*a
                Color(cr, cg, cb, 0.08 + a*0.25)
                gr = r + 25 + a*35
                Ellipse(pos=(cx-gr, cy-gr), size=(gr*2, gr*2))

            if self.active:
                Color(C_CYAN[0], C_CYAN[1], C_CYAN[2], 0.1 + self.level*0.25)
            else:
                Color(1, 1, 1, 0.06 + 0.03 * math.sin(self._t))
            Ellipse(pos=(cx-r, cy-r), size=(r*2, r*2))

            if self.active:
                a = self.level
                Color(C_CYAN[0]*(1-a)+C_RED[0]*a,
                      C_CYAN[1]*(1-a)+C_RED[1]*a,
                      C_CYAN[2]*(1-a)+C_RED[2]*a, 0.85)
            else:
                Color(*C_BORDER)
            Line(circle=(cx, cy, r), width=dp(2))

            if self.active and self.level > 0.01:
                a = self.level
                Color(C_CYAN[0]*(1-a)+C_RED[0]*a,
                      C_CYAN[1]*(1-a)+C_RED[1]*a,
                      C_CYAN[2]*(1-a)+C_RED[2]*a, 0.9)
                Line(circle=(cx, cy, r+dp(7), 90, 90+a*360), width=dp(3))

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


# ═══════════════════════════════════════════════
#  MAIN APP
# ═══════════════════════════════════════════════
class DMicApp(App):

    def __init__(self, **kw):
        super().__init__(**kw)
        self.title = 'D-MIC'
        self.engine = AudioEngine()
        self.wakelock = WakeLockMgr()
        self._streaming = False
        print("[D-MIC] App created")

    def build(self):
        print("[D-MIC] build() called")

        try:
            if Window:
                Window.clearcolor = C_BG
        except:
            pass

        root = FloatLayout()
        try:
            with root.canvas.before:
                Color(*C_BG)
                self._bg = Rectangle(size=(500, 800))
            if Window:
                Window.bind(size=lambda *_: setattr(self._bg, 'size', Window.size))
        except Exception as e:
            print(f"[D-MIC] BG error: {e}")

        # Header
        root.add_widget(Label(
            text='D-MIC', font_size=sp(40), bold=True, color=C_CYAN,
            size_hint=(1, None), height=dp(50),
            pos_hint={'center_x':.5, 'top':.97}
        ))
        root.add_widget(Label(
            text='Phone > Laptop Microphone', font_size=sp(11), color=C_MID,
            size_hint=(1, None), height=dp(20),
            pos_hint={'center_x':.5, 'top':.91}
        ))

        # VU Meter
        self.vu = VUMeter(
            size_hint=(.7, .28),
            pos_hint={'center_x':.5, 'center_y':.64}
        )
        root.add_widget(self.vu)

        self.mic_lbl = Label(
            text='MIC\nOFF', font_size=sp(22), bold=True,
            color=C_DIM, halign='center', valign='middle',
            size_hint=(None, None), size=(dp(100), dp(70)),
            pos_hint={'center_x':.5, 'center_y':.64}
        )
        root.add_widget(self.mic_lbl)

        # Status
        self.status = Label(
            text='Enter server IP and tap STREAM', font_size=sp(11),
            color=C_DIM, size_hint=(1, None), height=dp(20),
            pos_hint={'center_x':.5, 'center_y':.48}
        )
        root.add_widget(self.status)

        # Log area (shows last few log lines)
        self.log_lbl = Label(
            text='', font_size=sp(8), color=[1,1,1,0.25],
            halign='left', valign='top',
            size_hint=(.9, None), height=dp(50),
            pos_hint={'center_x':.5, 'center_y':.43}
        )
        self.log_lbl.bind(size=self.log_lbl.setter('text_size'))
        root.add_widget(self.log_lbl)
        self._log_lines = []

        # Input card
        card = BoxLayout(
            orientation='vertical', spacing=dp(10),
            padding=[dp(20), dp(14), dp(20), dp(14)],
            size_hint=(.88, None), height=dp(135),
            pos_hint={'center_x':.5, 'center_y':.27}
        )
        with card.canvas.before:
            Color(*C_CARD)
            self._cr = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(16)])
            Color(*C_BORDER)
            self._cb = Line(rounded_rectangle=(*card.pos, *card.size, dp(16)), width=1)
        card.bind(pos=self._upd_card, size=self._upd_card)

        # IP
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

        # Port
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

        # Stream button
        self.btn = Button(
            text='STREAM', font_size=sp(18), bold=True,
            size_hint=(.88, None), height=dp(54),
            pos_hint={'center_x':.5, 'center_y':.10},
            background_normal='', background_color=[0,0,0,0],
            color=[0,0,0,1]
        )
        with self.btn.canvas.before:
            Color(*C_CYAN)
            self._br = RoundedRectangle(pos=self.btn.pos, size=self.btn.size, radius=[dp(14)])
        self.btn.bind(pos=self._upd_btn, size=self._upd_btn)
        self.btn.bind(on_release=self._on_btn_press)
        root.add_widget(self.btn)

        # Footer
        root.add_widget(Label(
            text='Developed by Soham', font_size=sp(9),
            color=[1,1,1,.12], size_hint=(1, None), height=dp(16),
            pos_hint={'center_x':.5, 'y':.01}
        ))

        Clock.schedule_interval(self._tick, 1/20)
        print("[D-MIC] build() complete ✓")
        self._add_log("App ready")
        return root

    # ── UI log ──
    def _add_log(self, msg):
        print(f"[D-MIC] {msg}")
        self._log_lines.append(msg)
        if len(self._log_lines) > 4:
            self._log_lines = self._log_lines[-4:]
        try:
            self.log_lbl.text = '\n'.join(self._log_lines)
        except:
            pass

    # ── Layout ──
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
            self.mic_lbl.text = f'MIC\n{int(lv*100)}%'
            self.mic_lbl.color = C_CYAN if lv < 0.7 else C_RED

    # ── Button handler ──
    def _on_btn_press(self, instance):
        print(f"[D-MIC] ★ BUTTON PRESSED ★ streaming={self._streaming}")
        self._add_log("Button pressed!")
        try:
            if self._streaming:
                self._do_stop()
            else:
                self._do_start()
        except Exception as e:
            print(f"[D-MIC] Button handler ERROR: {e}")
            import traceback; traceback.print_exc()
            self._add_log(f"Error: {e}")

    def _do_start(self):
        ip = self.ip_in.text.strip()
        print(f"[D-MIC] _do_start() ip='{ip}'")
        self._add_log(f"Starting... IP={ip}")

        if not ip:
            self.status.text = 'Enter server IP!'
            self.status.color = C_RED
            self._add_log("No IP entered!")
            return

        port_str = self.port_in.text.strip() or '50005'
        port = int(port_str)
        print(f"[D-MIC] Target: {ip}:{port}")

        if IS_ANDROID:
            self.status.text = 'Requesting mic permission...'
            self.status.color = C_MID
            self._add_log("Requesting permission...")
            # Run in thread so UI stays responsive
            threading.Thread(
                target=self._start_threaded,
                args=(ip, port), daemon=True
            ).start()
        else:
            self._begin_stream(ip, port)

    def _start_threaded(self, ip, port):
        print("[D-MIC] _start_threaded running")
        try:
            ok = ensure_mic_permission()
            print(f"[D-MIC] Permission result: {ok}")
            if ok:
                Clock.schedule_once(lambda dt: self._begin_stream(ip, port), 0)
            else:
                Clock.schedule_once(lambda dt: self._perm_fail(), 0)
        except Exception as e:
            print(f"[D-MIC] _start_threaded ERROR: {e}")
            import traceback; traceback.print_exc()
            Clock.schedule_once(lambda dt: self._perm_fail(), 0)

    def _perm_fail(self):
        self.status.text = 'Mic permission DENIED!'
        self.status.color = C_RED
        self._add_log("Permission denied!")

    def _begin_stream(self, ip, port):
        print(f"[D-MIC] _begin_stream({ip}, {port})")
        self._add_log(f"Connecting to {ip}:{port}...")

        try:
            self.wakelock.acquire()
        except Exception as e:
            print(f"[D-MIC] WakeLock error: {e}")

        try:
            self.engine.start(ip, port)
        except Exception as e:
            print(f"[D-MIC] Engine start error: {e}")
            self._add_log(f"Engine error: {e}")
            return

        self._streaming = True
        self.status.text = f'Streaming to {ip}:{port}'
        self.status.color = C_GREEN
        self.btn.text = 'STOP'
        self._set_btn_color(C_RED)
        self._add_log(f"Streaming started!")

    def _do_stop(self):
        print("[D-MIC] _do_stop()")
        self._add_log("Stopping...")
        self.engine.stop()
        self.wakelock.release()
        self._streaming = False
        self.status.text = 'Stopped'
        self.status.color = C_DIM
        self.btn.text = 'STREAM'
        self.mic_lbl.text = 'MIC\nOFF'
        self.mic_lbl.color = C_DIM
        self._set_btn_color(C_CYAN)
        self._add_log("Stopped")

    def _set_btn_color(self, c):
        self.btn.canvas.before.clear()
        with self.btn.canvas.before:
            Color(*c)
            self._br = RoundedRectangle(
                pos=self.btn.pos, size=self.btn.size, radius=[dp(14)])

    def on_stop(self):
        print("[D-MIC] App closing")
        try:
            self._do_stop()
        except:
            pass


# ═══════════════════════════════════════════════
print("[D-MIC] Creating app...")
if __name__ == '__main__':
    DMicApp().run()
