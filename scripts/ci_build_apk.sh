#!/usr/bin/env bash
set -euo pipefail

echo "=== 1. Menyiapkan Web Assets Claymorphism (Standalone APK) ==="
python scripts/prepare_apk_www.py

echo "=== 2. Install Capacitor & Generate Android Project ==="
npm install --no-audit --no-fund
if [ ! -d "android" ]; then
  npx cap add android
fi
npx cap sync android

echo "=== 3. Build Android Debug APK ==="
cd android
chmod +x gradlew
./gradlew assembleDebug
