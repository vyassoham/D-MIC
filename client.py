import socket
import threading
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.label import Label
from kivy.utils import platform
from config import *

# Check if we are on Android for native recording (Ultra Lightweight)
if platform == 'android':
    from jnius import autoclass
    from android.permissions import request_permissions, Permission
    request_permissions([Permission.RECORD_AUDIO, Permission.INTERNET])
    
    AudioRecord = autoclass('android.media.AudioRecord')
    AudioFormat = autoclass('android.media.AudioFormat')
    MediaRecorder = autoclass('android.media.MediaRecorder')
else:
    import sounddevice as sd
    import numpy as np

class DMicClientApp(App):
    def build(self):
        self.running = False
        self.sock = None
        
        self.layout = BoxLayout(orientation='vertical', padding=50, spacing=20)
        self.layout.canvas.before.add(
            # Premium dark background
        )

        title = Label(text="D-MIC CLIENT", font_size=40, bold=True, color=(0, 1, 0.8, 1))
        self.layout.add_widget(title)

        self.ip_input = TextInput(
            text='', 
            hint_text='Enter Laptop IP (e.g. 192.168.1.5)',
            multiline=False, size_hint_y=None, height=100,
            background_color=(0.1, 0.1, 0.1, 1), foreground_color=(1, 1, 1, 1), font_size=32
        )
        self.layout.add_widget(self.ip_input)

        self.btn_toggle = Button(
            text="START MIC", size_hint_y=None, height=150,
            background_normal='', background_color=(0.2, 0.2, 0.2, 1), font_size=36
        )
        self.btn_toggle.bind(on_press=self.toggle_mic)
        self.layout.add_widget(self.btn_toggle)

        self.status = Label(text="Status: Disconnected", color=(1, 1, 1, 0.6))
        self.layout.add_widget(self.status)

        tk_credit = Label(text="Developed by Soham", font_size=20, color=(0.3, 0.3, 0.3, 1))
        self.layout.add_widget(tk_credit)

        return self.layout

    def android_record_thread(self):
        # Native Android Recording Logic (No heavy dependencies)
        buffer_size = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        recorder = AudioRecord(MediaRecorder.AudioSource.MIC, RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, buffer_size)
        
        recorder.startRecording()
        buffer = [0] * buffer_size
        
        while self.running:
            recorder.read(buffer, 0, len(buffer))
            # Convert to bytes and send
            data = bytes((np.array(buffer, dtype='int16')).tobytes()) if 'np' in globals() else bytes(buffer)
            try:
                self.sock.sendto(data, (self.ip, PORT))
            except: break
            
        recorder.stop()
        recorder.release()

    def desktop_audio_callback(self, indata, frames, time, status):
        if self.running and self.sock:
            try:
                self.sock.sendto(indata.tobytes(), (self.ip, PORT))
            except: pass

    def toggle_mic(self, instance):
        if not self.running:
            self.ip = self.ip_input.text.strip()
            if not self.ip:
                self.status.text = "Error: Please enter IP"
                return

            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.running = True
                self.btn_toggle.text = "STOP MIC"
                self.btn_toggle.background_color = (0, 0.8, 0.6, 1)
                self.status.text = f"Streaming to {self.ip}..."

                if platform == 'android':
                    threading.Thread(target=self.android_record_thread, daemon=True).start()
                else:
                    self.stream = sd.InputStream(samplerate=RATE, channels=CHANNELS, dtype='int16', 
                                               callback=self.desktop_audio_callback, blocksize=CHUNK)
                    self.stream.start()
            except Exception as e:
                self.status.text = f"Error: {e}"
        else:
            self.running = False
            if platform != 'android' and hasattr(self, 'stream'):
                self.stream.stop()
                self.stream.close()
            if self.sock: self.sock.close()
            self.btn_toggle.text = "START MIC"
            self.btn_toggle.background_color = (0.2, 0.2, 0.2, 1)
            self.status.text = "Status: Disconnected"

if __name__ == "__main__":
    DMicClientApp().run()
