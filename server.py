import socket
import sounddevice as sd
import numpy as np
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from config import *

class DMicServer:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("D-MIC | Terminal")
        self.root.geometry("400x300")
        self.root.configure(bg="#0f0f0f")
        self.root.resizable(False, False)

        self.running = False
        self.sock = None
        self.stream = None

        # Custom Styling
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TButton", padding=10, relief="flat", background="#1e1e1e", foreground="white")
        style.map("TButton", background=[('active', '#333')])

        # UI Layout
        tk.Label(self.root, text="D-MIC", fg="#00ffcc", bg="#0f0f0f", font=("Courier", 24, "bold")).pack(pady=20)
        
        self.status_label = tk.Label(self.root, text="STATUS: OFFLINE", fg="#ff3333", bg="#0f0f0f", font=("Consolas", 12))
        self.status_label.pack(pady=5)

        self.ip_label = tk.Label(self.root, text=f"IP ADDRESS: {get_local_ip()}", fg="#888", bg="#0f0f0f", font=("Consolas", 10))
        self.ip_label.pack(pady=5)

        tk.Label(self.root, text="( Ensure phone is on same WiFi )", fg="#555", bg="#0f0f0f", font=("Arial", 8, "italic")).pack()

        # Control Frame
        ctrl_frame = tk.Frame(self.root, bg="#0f0f0f")
        ctrl_frame.pack(pady=20)

        self.btn_toggle = ttk.Button(ctrl_frame, text="START SERVER", command=self.toggle_server)
        self.btn_toggle.pack(side="left", padx=10)

        # VU Meter
        self.vu_canvas = tk.Canvas(self.root, width=300, height=20, bg="#1a1a1a", highlightthickness=0)
        self.vu_canvas.pack(pady=10)
        self.vu_bar = self.vu_canvas.create_rectangle(0, 0, 0, 20, fill="#00ffcc")

    def update_vu(self, data):
        volume = np.linalg.norm(data) * 10
        width = min(300, volume)
        self.vu_canvas.coords(self.vu_bar, 0, 0, width, 20)
        # Dynamic color from green to red based on peak
        color = "#00ffcc" if width < 200 else "#ffcc00" if width < 280 else "#ff3333"
        self.vu_canvas.itemconfig(self.vu_bar, fill=color)

    def audio_receiver(self):
        try:
            self.stream = sd.OutputStream(
                samplerate=RATE,
                channels=CHANNELS,
                dtype='int16'
            )
            self.stream.start()
            
            while self.running:
                data, addr = self.sock.recvfrom(CHUNK * 4)
                audio_array = np.frombuffer(data, dtype=np.int16)
                self.stream.write(audio_array)
                self.root.after(0, self.update_vu, audio_array)
        except Exception as e:
            print(f"Receiver Error: {e}")
        finally:
            if self.stream:
                self.stream.stop()
                self.stream.close()

    def toggle_server(self):
        if not self.running:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.bind(('', PORT))
                self.running = True
                self.status_label.config(text="STATUS: LISTENING...", fg="#00ffcc")
                self.btn_toggle.config(text="STOP SERVER")
                
                self.thread = threading.Thread(target=self.audio_receiver, daemon=True)
                self.thread.start()
            except Exception as e:
                messagebox.showerror("D-MIC Error", f"Failed to bind port {PORT}: {e}")
        else:
            self.running = False
            if self.sock:
                self.sock.close()
            self.status_label.config(text="STATUS: OFFLINE", fg="#ff3333")
            self.btn_toggle.config(text="START SERVER")
            self.vu_canvas.coords(self.vu_bar, 0, 0, 0, 20)

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    server = DMicServer()
    server.run()
