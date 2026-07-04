#!/usr/bin/env bash
# packaging/agent/macos/build_dmg.sh — gera dist/CausiaAgente.dmg (não assinado).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
APP="$ROOT/dist/Causia Agente.app"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$APP/Contents/Frameworks"
# O bootloader do PyInstaller detecta que está dentro de um .app (pelo caminho do
# executável) e passa a procurar os libs de suporte em Contents/Frameworks (achatado,
# sem subpasta _internal) em vez do _internal/ irmão do onedir solto — por isso o
# executável vai em Contents/MacOS/ e o CONTEÚDO de _internal/ vai achatado em
# Contents/Frameworks/, não a pasta _internal/ inteira dentro de Contents/MacOS/.
cp "$ROOT/dist/causia-agent/causia-agent" "$APP/Contents/MacOS/"
cp -R "$ROOT/dist/causia-agent/_internal/." "$APP/Contents/Frameworks/"
cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Causia Agente</string>
  <key>CFBundleIdentifier</key><string>br.com.causia.agent</string>
  <key>CFBundleVersion</key><string>2026.7.4.1</string>
  <key>CFBundleExecutable</key><string>causia-agent</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PL
# instalador embutido: um script que copia o .app e carrega o LaunchAgent
cp "$ROOT/packaging/agent/macos/com.causia.agent.plist" "$APP/Contents/Resources/"
cp "$ROOT/packaging/agent/LEIA-ME.txt" "$ROOT/dist/LEIA-ME.txt"
hdiutil create -volname "Causia Agente" -srcfolder "$ROOT/dist/Causia Agente.app" \
  -srcfolder "$ROOT/dist/LEIA-ME.txt" -ov -format UDZO "$ROOT/dist/CausiaAgente.dmg"
echo "→ dist/CausiaAgente.dmg"
