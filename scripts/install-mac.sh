#!/bin/bash
# Full, local Apple Silicon installation. No developer subscription is needed.
set -euo pipefail
PDF_SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fail() { printf '%s\n' "$*" >&2; exit 1; }
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || fail 'Requer um Mac Apple Silicon executando nativamente (sem Rosetta).'
PDF_OS_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
[[ "$PDF_OS_MAJOR" -ge 26 ]] || fail 'A instalação completa requer macOS 26 ou posterior para Liquid Glass e IA local.'
xcrun --find swift >/dev/null 2>&1 || fail 'Instale Xcode 26 ou posterior e selecione-o com xcode-select.'
PDF_SDK_MAJOR="$(xcrun --sdk macosx --show-sdk-version | cut -d. -f1)"
[[ "$PDF_SDK_MAJOR" -ge 26 ]] || fail 'Selecione um Xcode com SDK macOS 26 ou posterior: sudo xcode-select -s /Applications/Xcode.app/Contents/Developer'
PDF_SWIFT_MAJOR="$(xcrun swift --version | sed -nE 's/.*Swift version ([0-9]+).*/\1/p' | head -1)"
[[ -n "$PDF_SWIFT_MAJOR" && "$PDF_SWIFT_MAJOR" -ge 6 ]] || fail 'Swift 6 ou posterior é necessário.'
if ! command -v brew >/dev/null 2>&1 && [[ -x /opt/homebrew/bin/brew ]]; then
  export PATH="/opt/homebrew/bin:$PATH"
fi
command -v brew >/dev/null 2>&1 || fail 'Instale Homebrew pelas instruções oficiais em https://brew.sh e execute novamente.'
[[ "$(brew --prefix)" == /opt/homebrew ]] || fail 'Use Homebrew arm64 em /opt/homebrew; a instalação Intel não é suportada.'
PDF_INSTALL_PARENT="${PDF_INSTALL_DIR:-$HOME/Applications}"
mkdir -p "$PDF_INSTALL_PARENT"
PDF_INSTALL_PARENT="$(cd "$PDF_INSTALL_PARENT" && pwd -P)"
PDF_DESTINATION="$PDF_INSTALL_PARENT/PDF.app"
PDF_LOCK="$PDF_INSTALL_PARENT/.pdf-install.lock"
mkdir "$PDF_LOCK" 2>/dev/null || fail "Outra instalação está em andamento, ou há um bloqueio residual: $PDF_LOCK"
printf '%s\n' "$$" > "$PDF_LOCK/pid"
PDF_STAGE=''
PDF_RUNTIME=''
PDF_BACKUP=''
PDF_ACTIVATED=0
PDF_SUCCESS=0
cleanup() {
  PDF_STATUS=$?
  trap - EXIT INT TERM
  if [[ "$PDF_SUCCESS" -ne 1 ]]; then
    if [[ "$PDF_ACTIVATED" -eq 1 && -d "$PDF_DESTINATION" ]]; then
      rm -rf -- "$PDF_DESTINATION"
    fi
    if [[ -n "$PDF_BACKUP" && -d "$PDF_BACKUP" && ! -e "$PDF_DESTINATION" ]]; then
      mv -- "$PDF_BACKUP" "$PDF_DESTINATION"
      printf '%s\n' 'A instalação anterior foi restaurada.' >&2
    fi
    if [[ -n "$PDF_RUNTIME" && -d "$PDF_RUNTIME" ]]; then rm -rf -- "$PDF_RUNTIME"; fi
  fi
  if [[ -n "$PDF_STAGE" && -d "$PDF_STAGE" ]]; then rm -rf -- "$PDF_STAGE"; fi
  rm -rf -- "$PDF_LOCK"
  exit "$PDF_STATUS"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ -e "$PDF_DESTINATION" || -L "$PDF_DESTINATION" ]]; then
  [[ -d "$PDF_DESTINATION" && ! -L "$PDF_DESTINATION" ]] || fail "O destino não é um bundle regular: $PDF_DESTINATION"
  PDF_EXISTING_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$PDF_DESTINATION/Contents/Info.plist" 2>/dev/null || true)"
  [[ "$PDF_EXISTING_ID" == local.pdf.desktop ]] || fail 'Já existe outro aplicativo chamado PDF.app. Escolha PDF_INSTALL_DIR diferente.'
fi
cd "$PDF_SOURCE_ROOT"
printf '%s\n' 'Compilando PDF para Apple Silicon…'
xcrun swift build -c release --arch arm64
PDF_BINARY_DIR="$(xcrun swift build -c release --arch arm64 --show-bin-path)"
[[ -x "$PDF_BINARY_DIR/PDF" ]] || fail 'A compilação não gerou o executável PDF.'
PDF_STAGE="$(mktemp -d "$PDF_INSTALL_PARENT/.pdf-install.XXXXXXXX")"
PDF_BUNDLE="$PDF_STAGE/PDF.app"
mkdir -p "$PDF_BUNDLE/Contents/Resources"
xcrun swift scripts/make-icon.swift "$PDF_STAGE/PDF.iconset"
iconutil -c icns "$PDF_STAGE/PDF.iconset" -o "$PDF_BUNDLE/Contents/Resources/PDF.icns"
# Dependencies remain on this Mac. They are not represented as a portable bundle.
export NONINTERACTIVE=1
export HOMEBREW_NO_AUTO_UPDATE=1
brew install python@3.12 ocrmypdf tesseract-lang
if [[ ! -x /Applications/LibreOffice.app/Contents/MacOS/soffice ]] && ! command -v soffice >/dev/null 2>&1; then
  brew install --cask libreoffice
fi
PDF_PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
PDF_RUNTIME_ROOT="$HOME/Library/Application Support/PDF/runtimes"
mkdir -p "$PDF_RUNTIME_ROOT"
PDF_RUNTIME="$(mktemp -d "$PDF_RUNTIME_ROOT/install.XXXXXXXX")"
"$PDF_PYTHON" -m venv "$PDF_RUNTIME"
"$PDF_RUNTIME/bin/python3" -m pip install --disable-pip-version-check -r requirements.txt -r requirements-optional.txt
export PLAYWRIGHT_BROWSERS_PATH="$PDF_RUNTIME/browsers"
"$PDF_RUNTIME/bin/python3" -m playwright install chromium
export PATH="/opt/homebrew/bin:$PATH"
PDF_LANGUAGES="$(tesseract --list-langs 2>/dev/null)"
printf '%s\n' "$PDF_LANGUAGES" | grep -qx eng || fail 'Tesseract não encontrou o idioma inglês.'
printf '%s\n' "$PDF_LANGUAGES" | grep -qx por || fail 'Tesseract não encontrou o idioma português.'
mkdir -p "$PDF_BUNDLE/Contents/MacOS" "$PDF_BUNDLE/Contents/Resources/engine" "$PDF_BUNDLE/Contents/Resources/runtime/bin"
cp "$PDF_BINARY_DIR/PDF" "$PDF_BUNDLE/Contents/MacOS/PDF"
# Copy all engine modules, but no Python caches or development files.
find engine -type f -name '*.py' -print0 | while IFS= read -r -d '' PDF_MODULE; do
  mkdir -p "$PDF_BUNDLE/Contents/Resources/$(dirname "$PDF_MODULE")"
  cp "$PDF_MODULE" "$PDF_BUNDLE/Contents/Resources/$PDF_MODULE"
done
# Stable external venv avoids absolute shebang relocation and signing Python's
# third-party native libraries as if they were application-owned nested code.
{
  printf '#!/bin/bash\nset -euo pipefail\n'
  printf 'export PYTHONDONTWRITEBYTECODE=1\n'
  printf 'export PLAYWRIGHT_BROWSERS_PATH=%q\n' "$PDF_RUNTIME/browsers"
  printf 'export PATH=%q:"$PATH"\n' '/opt/homebrew/bin:/usr/local/bin'
  printf 'exec %q "$@"\n' "$PDF_RUNTIME/bin/python3"
} > "$PDF_BUNDLE/Contents/Resources/runtime/bin/python3"
chmod 755 "$PDF_BUNDLE/Contents/Resources/runtime/bin/python3"
printf '%s\n' "$PDF_RUNTIME" > "$PDF_BUNDLE/Contents/Resources/runtime-location.txt"
cat > "$PDF_BUNDLE/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>PDF</string>
<key>CFBundleDisplayName</key><string>PDF</string>
<key>CFBundleIdentifier</key><string>local.pdf.desktop</string>
<key>CFBundleExecutable</key><string>PDF</string>
<key>CFBundleIconFile</key><string>PDF</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.2.0</string>
<key>CFBundleVersion</key><string>2</string>
<key>LSMinimumSystemVersion</key><string>26.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSCameraUsageDescription</key><string>Digitalizar documentos para os arquivos PDF que você escolher.</string>
<key>NSLocalNetworkUsageDescription</key><string>Encontrar e usar scanners compartilhados na sua rede local.</string>
<key>NSBonjourServices</key><array><string>_scanner._tcp</string><string>_uscan._tcp</string><string>_uscans._tcp</string><string>_ica-networking._tcp</string></array>
<key>CFBundleDocumentTypes</key><array><dict>
<key>CFBundleTypeName</key><string>Documento PDF</string>
<key>CFBundleTypeRole</key><string>Editor</string>
<key>LSHandlerRank</key><string>Alternate</string>
<key>LSItemContentTypes</key><array><string>com.adobe.pdf</string></array>
</dict></array>
</dict></plist>
PLIST
plutil -lint "$PDF_BUNDLE/Contents/Info.plist"
# Sign innermost application-owned executable, then seal the complete bundle.
codesign --force --sign - --timestamp=none "$PDF_BUNDLE/Contents/MacOS/PDF"
codesign --force --sign - --timestamp=none "$PDF_BUNDLE"
codesign --verify --deep --strict "$PDF_BUNDLE"
printf '%s\n' 'Validando motor, conversões e componentes nativos…'
"$PDF_RUNTIME/bin/python3" -m unittest discover -s tests -v
"$PDF_RUNTIME/bin/python3" tests/integration_optional.py -v
bash scripts/check-mac.sh "$PDF_BUNDLE"
if [[ -d "$PDF_DESTINATION" ]]; then
  PDF_BACKUP="$PDF_INSTALL_PARENT/PDF.previous.$(date -u +%Y%m%dT%H%M%SZ).$$.app"
  [[ ! -e "$PDF_BACKUP" ]] || fail 'O caminho da cópia anterior já existe.'
  mv -- "$PDF_DESTINATION" "$PDF_BACKUP"
fi
mv -- "$PDF_BUNDLE" "$PDF_DESTINATION"
PDF_ACTIVATED=1
bash scripts/check-mac.sh "$PDF_DESTINATION"
PDF_SUCCESS=1
printf 'Instalado e verificado: %s\n' "$PDF_DESTINATION"
if [[ -n "$PDF_BACKUP" ]]; then printf 'Versão anterior preservada: %s\n' "$PDF_BACKUP"; fi
printf 'Abra com: open %q\n' "$PDF_DESTINATION"
printf '%s\n' 'Assinatura local ad hoc, sem notarização Apple. Para outro Mac, execute novamente este instalador no próprio computador.'
