[app]
title = D-MIC
package.name = dmic
package.domain = org.soham
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 1.0.0
requirements = python3,kivy,pyjnius

# Permissions
android.permissions = RECORD_AUDIO, INTERNET

# Appearance
orientation = portrait
fullscreen = 1

# Android specific - using stable versions only
android.api = 33
android.minapi = 21
android.ndk = 25b
android.build_tools_version = 33.0.2
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
