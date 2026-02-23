"""
D-MIC Client - Phone Microphone Streamer
Run this on Pydroid 3 on your Android phone.
Streams mic audio to your laptop over UDP.
Keeps running in background with foreground service.

Requirements (install in Pydroid):
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

# ============================================================
# ANDROID BACKGROUND SERVICE & AUDIO (via jnius)
# ============================================================
IS_ANDROID = False
try:
    from jnius import autoclass, cast
    from android import mActivity
    IS_ANDROID = True
except ImportError:
    pass

# ============================================================
# KIVY SETUP (must be before any kivy import)
# ============================================================
os.environ['KIVY_AUDIO'] = 'sdl2'
# Only use ANGLE on Windows; Android uses native OpenGL ES
import platform
if platform.system() == 'Windows':
    os.environ.setdefault('KIVY_GL_BACKEND', 'angle_sdl2')

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.graphics import PushMatrix, PopMatrix, Rotate, Scale
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.utils import get_color_from_hex
from kivy.metrics import dp, sp
from kivy.properties import NumericProperty, BooleanProperty, StringProperty
from kivy.animation import Animation

# ============================================================
# COLORS
# ============================================================
BG_DARK = get_color_from_hex('#0A0A0F')
BG_CARD = get_color_from_hex('#12121A')
BORDER = get_color_from_hex('#2A2A3E')
CYAN = get_color_from_hex('#00E5FF')
PURPLE = get_color_from_hex('#7C4DFF')
RED = get_color_from_hex('#FF1744')
WHITE = [1, 1, 1, 1]
WHITE_DIM = [1, 1, 1, 0.3]
WHITE_MID = [1, 1, 1, 0.5]


# ============================================================
# ANDROID AUDIO CAPTURE ENGINE (uses AudioRecord via JNI)
# ============================================================
class AndroidAudioEngine:
    """Captures audio using Android's native AudioRecord API via pyjnius"""

    def __init__(self):
        self.is_recording = False
        self.thread = None
        self.vu_level = 0.0
        self.sample_rate = 44100
        self.buffer_size = 2048

    def start(self, server_ip, server_port):
        if self.is_recording:
            return
        self.is_recording = True
        self.thread = threading.Thread(
            target=self._capture_loop,
            args=(server_ip, server_port),
            daemon=True
        )
        self.thread.start()

    def stop(self):
        self.is_recording = False
        if self.thread:
            self.thread.join(timeout=2)
            self.thread = None
        self.vu_level = 0.0

    def _capture_loop(self, server_ip, server_port):
        if not IS_ANDROID:
            # MOCK MODE for testing on PC
            self._mock_capture(server_ip, server_port)
            return

        try:
            # Java classes
            AudioRecord = autoclass('android.media.AudioRecord')
            AudioFormat = autoclass('android.media.AudioFormat')
            MediaRecorder = autoclass('android.media.MediaRecorder')

            CHANNEL_IN_MONO = AudioFormat.CHANNEL_IN_MONO
            ENCODING_PCM_16BIT = AudioFormat.ENCODING_PCM_16BIT
            MIC_SOURCE = MediaRecorder.AudioSource.MIC

            # Get minimum buffer size
            min_buf = AudioRecord.getMinBufferSize(
                self.sample_rate, CHANNEL_IN_MONO, ENCODING_PCM_16BIT
            )
            buf_size = max(min_buf, self.buffer_size)

            # Create AudioRecord
            recorder = AudioRecord(
                MIC_SOURCE,
                self.sample_rate,
                CHANNEL_IN_MONO,
                ENCODING_PCM_16BIT,
                buf_size
            )

            if recorder.getState() != AudioRecord.STATE_INITIALIZED:
                print("[D-MIC] AudioRecord failed to initialize")
                self.is_recording = False
                return

            # Create UDP socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            addr = (server_ip, server_port)

            # Start recording
            recorder.startRecording()
            print(f"[D-MIC] Streaming to {server_ip}:{server_port}")

            # Read buffer (Java byte array)
            JArray = autoclass('java.lang.reflect.Array')
            buffer = bytearray(self.buffer_size)

            while self.is_recording:
                try:
                    # Read audio into byte array
                    bytes_read = recorder.read(buffer, 0, len(buffer))
                    if bytes_read > 0:
                        # Send via UDP
                        sock.sendto(bytes(buffer[:bytes_read]), addr)

                        # Calculate VU level (RMS of PCM16)
                        rms_sum = 0
                        sample_count = bytes_read // 2
                        for i in range(0, bytes_read - 1, 2):
                            sample = struct.unpack_from('<h', buffer, i)[0]
                            rms_sum += sample * sample
                        if sample_count > 0:
                            rms = math.sqrt(rms_sum / sample_count)
                            self.vu_level = min(1.0, rms / 16384.0)
                except Exception as e:
                    print(f"[D-MIC] Stream error: {e}")
                    time.sleep(0.01)

            # Cleanup
            recorder.stop()
            recorder.release()
            sock.close()
            print("[D-MIC] Stopped streaming")

        except Exception as e:
            print(f"[D-MIC] Audio engine error: {e}")
            self.is_recording = False

    def _mock_capture(self, server_ip, server_port):
        """Mock capture for testing on PC (generates sine wave)"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        addr = (server_ip, server_port)
        t = 0
        while self.is_recording:
            # Generate a test tone
            samples = []
            for i in range(1024):
                val = int(8000 * math.sin(2 * math.pi * 440 * t / 44100))
                samples.append(struct.pack('<h', val))
                t += 1
            data = b''.join(samples)
            try:
                sock.sendto(data, addr)
            except:
                pass
            # Fake VU
            self.vu_level = 0.3 + 0.2 * math.sin(time.time() * 3)
            time.sleep(0.023)  # ~44100/1024
        sock.close()
        self.vu_level = 0.0


# ============================================================
# ANDROID BACKGROUND SERVICE
# ============================================================
class AndroidService:
    """Keeps the app alive in background using WakeLock + Foreground notification"""

    def __init__(self):
        self.wake_lock = None

    def start(self):
        if not IS_ANDROID:
            return
        try:
            # Acquire WakeLock to prevent CPU sleep
            Context = autoclass('android.content.Context')
            PowerManager = autoclass('android.os.PowerManager')
            pm = cast('android.os.PowerManager',
                       mActivity.getSystemService(Context.POWER_SERVICE))
            self.wake_lock = pm.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK, 'dmic:streaming'
            )
            self.wake_lock.acquire()

            # Show persistent notification (keeps app alive)
            self._show_notification()
            print("[D-MIC] Background service started")
        except Exception as e:
            print(f"[D-MIC] Service error: {e}")

    def stop(self):
        if not IS_ANDROID:
            return
        try:
            if self.wake_lock and self.wake_lock.isHeld():
                self.wake_lock.release()
            self._cancel_notification()
            print("[D-MIC] Background service stopped")
        except Exception as e:
            print(f"[D-MIC] Service stop error: {e}")

    def _show_notification(self):
        try:
            Context = autoclass('android.content.Context')
            NotificationBuilder = autoclass('android.app.Notification$Builder')
            NotificationManager = autoclass('android.app.NotificationManager')
            NotificationChannel = autoclass('android.app.NotificationChannel')
            Build = autoclass('android.os.Build')
            PendingIntent = autoclass('android.app.PendingIntent')
            Intent = autoclass('android.content.Intent')

            # Create notification channel (Android 8+)
            if Build.VERSION.SDK_INT >= 26:
                channel = NotificationChannel(
                    'dmic_channel', 'D-MIC Streaming',
                    NotificationManager.IMPORTANCE_LOW
                )
                channel.setDescription('D-MIC is streaming audio')
                nm = cast('android.app.NotificationManager',
                           mActivity.getSystemService(Context.NOTIFICATION_SERVICE))
                nm.createNotificationChannel(channel)

                builder = NotificationBuilder(mActivity, 'dmic_channel')
            else:
                builder = NotificationBuilder(mActivity)

            # Create intent to reopen app
            intent = Intent(mActivity, mActivity.getClass())
            intent.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
            pi = PendingIntent.getActivity(
                mActivity, 0, intent,
                PendingIntent.FLAG_IMMUTABLE
            )

            notification = (builder
                            .setContentTitle('D-MIC Active')
                            .setContentText('Streaming microphone...')
                            .setSmallIcon(mActivity.getApplicationInfo().icon)
                            .setOngoing(True)
                            .setContentIntent(pi)
                            .build())

            nm = cast('android.app.NotificationManager',
                       mActivity.getSystemService(Context.NOTIFICATION_SERVICE))
            nm.notify(9999, notification)
        except Exception as e:
            print(f"[D-MIC] Notification error: {e}")

    def _cancel_notification(self):
        try:
            Context = autoclass('android.content.Context')
            nm = cast('android.app.NotificationManager',
                       mActivity.getSystemService(Context.NOTIFICATION_SERVICE))
            nm.cancel(9999)
        except:
            pass


# ============================================================
# PERMISSION HANDLER
# ============================================================
def request_mic_permission():
    if not IS_ANDROID:
        return True
    try:
        from android.permissions import request_permissions, Permission, check_permission
        if not check_permission(Permission.RECORD_AUDIO):
            request_permissions([
                Permission.RECORD_AUDIO,
                Permission.INTERNET,
                Permission.WAKE_LOCK
            ])
            time.sleep(1)  # Wait for user response
        return check_permission(Permission.RECORD_AUDIO)
    except Exception as e:
        print(f"[D-MIC] Permission error: {e}")
        return False


# ============================================================
# VU METER WIDGET
# ============================================================
class VUMeter(Widget):
    level = NumericProperty(0.0)
    active = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._phase = 0
        self.bind(pos=self._update, size=self._update, level=self._update, active=self._update)
        Clock.schedule_interval(self._tick, 1 / 30)

    def _tick(self, dt):
        self._phase += dt * 2
        self._update()

    def _update(self, *args):
        self.canvas.clear()
        cx = self.center_x
        cy = self.center_y
        radius = min(self.width, self.height) * 0.4

        with self.canvas:
            # Outer glow ring
            if self.active:
                glow_alpha = 0.1 + self.level * 0.4
                r = CYAN[0] * (1 - self.level) + RED[0] * self.level
                g = CYAN[1] * (1 - self.level) + RED[1] * self.level
                b = CYAN[2] * (1 - self.level) + RED[2] * self.level
                Color(r, g, b, glow_alpha)
                glow_r = radius + 20 + self.level * 30
                Ellipse(pos=(cx - glow_r, cy - glow_r), size=(glow_r * 2, glow_r * 2))
            
            # Background circle
            if self.active:
                bg_alpha = 0.15 + self.level * 0.3
                Color(CYAN[0], CYAN[1], CYAN[2], bg_alpha)
            else:
                pulse = 0.08 + 0.04 * math.sin(self._phase)
                Color(1, 1, 1, pulse)
            Ellipse(pos=(cx - radius, cy - radius), size=(radius * 2, radius * 2))

            # Border ring
            if self.active:
                r = CYAN[0] * (1 - self.level) + RED[0] * self.level
                g = CYAN[1] * (1 - self.level) + RED[1] * self.level
                b = CYAN[2] * (1 - self.level) + RED[2] * self.level
                Color(r, g, b, 0.9)
            else:
                Color(*BORDER)
            Line(circle=(cx, cy, radius), width=dp(2))

            # Level arc (active only)
            if self.active and self.level > 0.01:
                r = CYAN[0] * (1 - self.level) + RED[0] * self.level
                g = CYAN[1] * (1 - self.level) + RED[1] * self.level
                b = CYAN[2] * (1 - self.level) + RED[2] * self.level
                Color(r, g, b, 0.8)
                angle = self.level * 360
                Line(circle=(cx, cy, radius + dp(6), 90, 90 + angle), width=dp(3))

            # Segmented ring (8 segments)
            for i in range(8):
                seg_angle = i * 45
                seg_level = (i + 1) / 8
                if self.active and self.level >= seg_level:
                    if seg_level > 0.75:
                        Color(*RED[:3], 0.8)
                    elif seg_level > 0.5:
                        Color(1, 0.8, 0, 0.7)
                    else:
                        Color(*CYAN[:3], 0.6)
                else:
                    Color(1, 1, 1, 0.05)
                Line(
                    circle=(cx, cy, radius + dp(14), seg_angle * 1.0 + 2, (seg_angle + 40) * 1.0),
                    width=dp(4)
                )


# ============================================================
# MAIN APP
# ============================================================
class DMicApp(App):
    vu_level = NumericProperty(0.0)
    is_streaming = BooleanProperty(False)
    status_text = StringProperty('Ready')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.audio_engine = AndroidAudioEngine()
        self.bg_service = AndroidService()
        self.title = 'D-MIC'

    def build(self):
        Window.clearcolor = BG_DARK

        root = FloatLayout()

        # ---- BACKGROUND ----
        with root.canvas.before:
            Color(*BG_DARK)
            self._bg_rect = Rectangle(pos=(0, 0), size=Window.size)
        root.bind(size=self._update_bg)

        # ---- TITLE ----
        title_label = Label(
            text='D-MIC',
            font_size=sp(38),
            bold=True,
            color=CYAN,
            size_hint=(1, None),
            height=dp(50),
            pos_hint={'center_x': 0.5, 'top': 0.97}
        )
        root.add_widget(title_label)

        subtitle = Label(
            text='Phone → Laptop Microphone',
            font_size=sp(11),
            color=WHITE_MID,
            size_hint=(1, None),
            height=dp(20),
            pos_hint={'center_x': 0.5, 'top': 0.91}
        )
        root.add_widget(subtitle)

        # ---- VU METER ----
        self.vu_meter = VUMeter(
            size_hint=(0.7, 0.3),
            pos_hint={'center_x': 0.5, 'center_y': 0.65}
        )
        root.add_widget(self.vu_meter)

        # ---- MIC ICON TEXT ----
        self.mic_label = Label(
            text='🎤\nOFF',
            font_size=sp(28),
            color=WHITE_DIM,
            halign='center',
            size_hint=(None, None),
            size=(dp(100), dp(80)),
            pos_hint={'center_x': 0.5, 'center_y': 0.65}
        )
        root.add_widget(self.mic_label)

        # ---- STATUS ----
        self.status_label = Label(
            text='Ready',
            font_size=sp(11),
            color=WHITE_DIM,
            size_hint=(1, None),
            height=dp(20),
            pos_hint={'center_x': 0.5, 'center_y': 0.48}
        )
        root.add_widget(self.status_label)

        # ---- INPUT CARD ----
        card = BoxLayout(
            orientation='vertical',
            spacing=dp(10),
            padding=[dp(20), dp(15), dp(20), dp(15)],
            size_hint=(0.85, None),
            height=dp(140),
            pos_hint={'center_x': 0.5, 'center_y': 0.3}
        )
        with card.canvas.before:
            Color(*BG_CARD)
            self._card_rect = RoundedRectangle(
                pos=card.pos, size=card.size, radius=[dp(16)]
            )
            Color(*BORDER)
            self._card_border = Line(
                rounded_rectangle=(*card.pos, *card.size, dp(16)),
                width=dp(1)
            )
        card.bind(pos=self._update_card, size=self._update_card)

        # IP Input
        ip_row = BoxLayout(orientation='horizontal', spacing=dp(8), size_hint_y=None, height=dp(48))
        ip_icon = Label(text='🖥️', font_size=sp(20), size_hint_x=None, width=dp(36))
        self.ip_input = TextInput(
            hint_text='192.168.X.X',
            text='',
            multiline=False,
            font_size=sp(16),
            background_color=[0.04, 0.04, 0.06, 1],
            foreground_color=WHITE,
            hint_text_color=WHITE_DIM,
            cursor_color=CYAN,
            padding=[dp(12), dp(12), dp(12), dp(12)],
            input_filter='int',  # will also allow dots
        )
        # Allow dots in IP input
        self.ip_input.input_filter = None
        ip_row.add_widget(ip_icon)
        ip_row.add_widget(self.ip_input)
        card.add_widget(ip_row)

        # Port Input
        port_row = BoxLayout(orientation='horizontal', spacing=dp(8), size_hint_y=None, height=dp(42))
        port_icon = Label(text='🔌', font_size=sp(16), size_hint_x=None, width=dp(36))
        self.port_input = TextInput(
            hint_text='50005',
            text='50005',
            multiline=False,
            font_size=sp(14),
            background_color=[0.04, 0.04, 0.06, 1],
            foreground_color=[1, 1, 1, 0.7],
            hint_text_color=WHITE_DIM,
            cursor_color=PURPLE,
            padding=[dp(10), dp(10), dp(10), dp(10)],
            input_filter='int',
        )
        port_row.add_widget(port_icon)
        port_row.add_widget(self.port_input)
        card.add_widget(port_row)

        root.add_widget(card)

        # ---- STREAM BUTTON ----
        self.stream_btn = Button(
            text='▶  STREAM',
            font_size=sp(18),
            bold=True,
            size_hint=(0.85, None),
            height=dp(56),
            pos_hint={'center_x': 0.5, 'center_y': 0.12},
            background_color=CYAN,
            color=[0, 0, 0, 1],
            background_normal='',
        )
        # Round corners via canvas
        with self.stream_btn.canvas.before:
            Color(*CYAN)
            self._btn_rect = RoundedRectangle(
                pos=self.stream_btn.pos,
                size=self.stream_btn.size,
                radius=[dp(16)]
            )
        self.stream_btn.bind(pos=self._update_btn, size=self._update_btn)
        self.stream_btn.background_color = [0, 0, 0, 0]  # transparent, we draw our own
        self.stream_btn.bind(on_press=self._toggle_stream)
        root.add_widget(self.stream_btn)

        # ---- FOOTER ----
        footer = Label(
            text='Developed by Soham',
            font_size=sp(9),
            color=[1, 1, 1, 0.15],
            size_hint=(1, None),
            height=dp(20),
            pos_hint={'center_x': 0.5, 'y': 0.01}
        )
        root.add_widget(footer)

        # Schedule VU updates
        Clock.schedule_interval(self._update_vu, 1 / 24)

        return root

    def _update_bg(self, *args):
        self._bg_rect.size = Window.size

    def _update_card(self, instance, *args):
        self._card_rect.pos = instance.pos
        self._card_rect.size = instance.size
        self._card_border.rounded_rectangle = (*instance.pos, *instance.size, dp(16))

    def _update_btn(self, instance, *args):
        self._btn_rect.pos = instance.pos
        self._btn_rect.size = instance.size

    def _update_vu(self, dt):
        level = self.audio_engine.vu_level
        self.vu_meter.level = level
        self.vu_meter.active = self.is_streaming
        if self.is_streaming:
            pct = int(level * 100)
            self.mic_label.text = f'🎤\n{pct}%'
            self.mic_label.color = CYAN if level < 0.7 else RED
        else:
            self.mic_label.text = '🎤\nOFF'
            self.mic_label.color = WHITE_DIM

    def _toggle_stream(self, *args):
        if self.is_streaming:
            self._stop_stream()
        else:
            self._start_stream()

    def _start_stream(self):
        ip = self.ip_input.text.strip()
        port_text = self.port_input.text.strip()

        if not ip:
            self.status_label.text = '⚠ Enter server IP address'
            self.status_label.color = RED
            return

        port = int(port_text) if port_text else 50005

        # Request mic permission
        if IS_ANDROID:
            granted = request_mic_permission()
            if not granted:
                self.status_label.text = '⚠ Microphone permission denied!'
                self.status_label.color = RED
                return

        # Start background service
        self.bg_service.start()

        # Start audio streaming
        self.audio_engine.start(ip, port)

        self.is_streaming = True
        self.status_label.text = f'🔴 Streaming to {ip}:{port}'
        self.status_label.color = CYAN
        self.stream_btn.text = '⏹  STOP'

        # Update button color to red
        self._btn_color = RED
        self._btn_rect_update()

    def _stop_stream(self):
        self.audio_engine.stop()
        self.bg_service.stop()

        self.is_streaming = False
        self.status_label.text = 'Stopped'
        self.status_label.color = WHITE_DIM
        self.stream_btn.text = '▶  STREAM'

        self._btn_color = CYAN
        self._btn_rect_update()

    def _btn_rect_update(self):
        color = getattr(self, '_btn_color', CYAN)
        self.stream_btn.canvas.before.clear()
        with self.stream_btn.canvas.before:
            Color(*color)
            self._btn_rect = RoundedRectangle(
                pos=self.stream_btn.pos,
                size=self.stream_btn.size,
                radius=[dp(16)]
            )

    def on_stop(self):
        """Called when app is closing"""
        self._stop_stream()


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == '__main__':
    DMicApp().run()
