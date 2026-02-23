# D-MIC: Phone-to-Laptop Microphone

A lightweight, 100% Python solution to use your phone's microphone on your laptop.

## 🚀 Laptop Setup (The EXE)
1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Run Server**:
   ```bash
   python server.py
   ```
3. **Compile to EXE**:
   ```bash
   pyinstaller --noconsole --onefile --add-data "config.py;." server.py
   ```

## 📱 Phone Setup (The App)
1. **Install Kivy**: Use `pip install kivy` to test on desktop.
2. **Compile to APK**:
   Use [Buildozer](https://github.com/kivy/buildozer).
   ```bash
   buildozer init
   # Edit buildozer.spec:
   # requirements = python3,kivy,sounddevice,numpy
   # permissions = RECORD_AUDIO, INTERNET
   buildozer android debug
   ```

## 🎙️ Using it as a System Microphone
To use D-MIC in apps like Discord, Zoom, or Teams:
1. Download and install **[VB-Audio Virtual Cable](https://vb-audio.com/Cable/)**.
2. Run D-MIC Server.
3. In Windows Sound Settings, set D-MIC to play through **"CABLE Input"**.
4. In Discord/Zoom, select **"CABLE Output"** as your Microphone.

## 🛠️ Features
- **Ultra Low Latency**: Uses UDP streaming.
- **Lightweight**: ~20MB memory footprint.
- **VU Meter**: Real-time visual feedback.
- **Dark Mode**: Sleek obsidian-themed UI.
