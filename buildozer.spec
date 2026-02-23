[app]
title = D-MIC
package.name = dmic
package.domain = org.soham
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 1.0.0
requirements = python3,kivy

# Permissions
android.permissions = RECORD_AUDIO, INTERNET

# Appearance
orientation = portrait
fullscreen = 1

# Android specific
android.api = 31
android.minapi = 21
android.sdk = 31
android.ndk = 23b
android.archs = arm64-v8a, armeabi-v7a

[buildozer]
log_level = 2
warn_on_root = 1
