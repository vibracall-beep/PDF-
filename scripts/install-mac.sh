#!/bin/bash
# Full, local Apple Silicon installation. No developer subscription is needed.
set -euo pipefail
umask 077
PDF_SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fail() { printf '%s\n' "$*" >&2; exit 1; }
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || fail 'Requer um Mac Apple Silicon executando nativamente (sem Rosetta).'
PDF_OS_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
[[ "$PDF_OS_MAJOR" -ge 26 ]] || fail 'A instalação completa requer macOS 26 ou posterior para Liquid Glass e IA local.'
xcrun --find swift >/dev/null 2>&1 || fail 'Instale Xcode 26 ou posterior e selecione-o com xcode-select.'
PDF_SDK_MAJOR="$(xcrun --sdk macosx --show-sdk-version | cut -d. -f1)"
[[ "$PDF_SDK_MAJOR" -ge 26 ]] || fail 'Selecione um Xcode com SDK macOS 26 ou posterior: sudo xcode-select -s /Applications/Xcode.app/Contents/Developer'
PDF_SWIFT_VERSION="$(xcrun swift --version | sed -nE 's/.*Swift version ([0-9]+\.[0-9]+).*/\1/p' | head -1)"
[[ "$PDF_SWIFT_VERSION" =~ ^[0-9]+\.[0-9]+$ ]] || fail 'Não foi possível identificar a versão do Swift.'
PDF_SWIFT_MAJOR="${PDF_SWIFT_VERSION%%.*}"
PDF_SWIFT_MINOR="${PDF_SWIFT_VERSION#*.}"
(( PDF_SWIFT_MAJOR > 6 || (PDF_SWIFT_MAJOR == 6 && PDF_SWIFT_MINOR >= 2) )) || fail 'Swift 6.2 ou posterior é necessário.'
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
PDF_LOCK_ID="$(stat -f '%d:%i' "$PDF_LOCK")"
PDF_STAGE=''
PDF_RUNTIME=''
PDF_RUNTIME_ID=''
PDF_STAGE_ID=''
PDF_BACKUP=''
PDF_ACTIVATED=0
PDF_SUCCESS=0
PDF_ORIGINAL_ID=''
PDF_STAGED_ID=''
PDF_RETAIN_RUNTIME=0
PDF_PYTHON=''
PDF_FILE_HELPER="$PDF_SOURCE_ROOT/scripts/install_files.py"
cleanup() {
  PDF_STATUS=$?
  trap - EXIT INT TERM
  set +e
  if [[ "$PDF_SUCCESS" -ne 1 ]]; then
    # Preserve a failed activated bundle rather than recursively deleting a path
    # that another process may have changed while validation was running.
    if [[ -n "$PDF_STAGED_ID" && -n "$PDF_PYTHON" && -d "$PDF_DESTINATION" && ! -L "$PDF_DESTINATION" ]]; then
      PDF_CURRENT_ID="$("$PDF_PYTHON" "$PDF_FILE_HELPER" identity "$PDF_DESTINATION" 2>/dev/null)"
      if [[ "$PDF_CURRENT_ID" == "$PDF_STAGED_ID" ]]; then
        PDF_FAILED="$PDF_INSTALL_PARENT/PDF.failed.$(date -u +%Y%m%dT%H%M%SZ).$$.app"
        PDF_RETAIN_RUNTIME=1
        if "$PDF_PYTHON" "$PDF_FILE_HELPER" move "$PDF_DESTINATION" "$PDF_FAILED" --expected "$PDF_STAGED_ID" >/dev/null; then
          printf 'Instalação com falha preservada para diagnóstico: %s\n' "$PDF_FAILED" >&2
        fi
      fi
    fi
    if [[ -n "$PDF_BACKUP" && -d "$PDF_BACKUP" && ! -L "$PDF_BACKUP" ]] && \
       [[ "$("$PDF_PYTHON" "$PDF_FILE_HELPER" identity "$PDF_BACKUP" 2>/dev/null)" == "$PDF_ORIGINAL_ID" ]]; then
      if [[ ! -e "$PDF_DESTINATION" && ! -L "$PDF_DESTINATION" ]] && \
         "$PDF_PYTHON" "$PDF_FILE_HELPER" move "$PDF_BACKUP" "$PDF_DESTINATION" --expected "$PDF_ORIGINAL_ID" >/dev/null; then
        printf '%s\n' 'A instalação anterior foi restaurada.' >&2
      else
        printf 'A versão anterior permanece preservada em: %s\n' "$PDF_BACKUP" >&2
      fi
    fi
    if [[ "$PDF_RETAIN_RUNTIME" -eq 0 && -n "$PDF_RUNTIME" && -d "$PDF_RUNTIME" && ! -L "$PDF_RUNTIME" ]] && \
       [[ "$(stat -f '%d:%i' "$PDF_RUNTIME" 2>/dev/null)" == "$PDF_RUNTIME_ID" ]]; then rm -rf -- "$PDF_RUNTIME"; fi
  fi
  if [[ -n "$PDF_STAGE" && -d "$PDF_STAGE" && ! -L "$PDF_STAGE" ]] && \
     [[ "$(stat -f '%d:%i' "$PDF_STAGE" 2>/dev/null)" == "$PDF_STAGE_ID" ]]; then rm -rf -- "$PDF_STAGE"; fi
  if [[ -d "$PDF_LOCK" && ! -L "$PDF_LOCK" ]] && [[ "$(stat -f '%d:%i' "$PDF_LOCK" 2>/dev/null)" == "$PDF_LOCK_ID" ]]; then
    rm -f -- "$PDF_LOCK/pid"
    rmdir "$PDF_LOCK"
  fi
  exit "$PDF_STATUS"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ -e "$PDF_DESTINATION" || -L "$PDF_DESTINATION" ]]; then
  [[ -d "$PDF_DESTINATION" && ! -L "$PDF_DESTINATION" ]] || fail "O destino não é um bundle regular: $PDF_DESTINATION"
  PDF_EXISTING_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$PDF_DESTINATION/Contents/Info.plist" 2>/dev/null || true)"
  [[ "$PDF_EXISTING_ID" == local.pdf.desktop ]] || fail 'Já existe outro aplicativo chamado PDF.app. Escolha PDF_INSTALL_DIR diferente.'
  [[ -f "$PDF_DESTINATION/Contents/Resources/installation.lock" && ! -L "$PDF_DESTINATION/Contents/Resources/installation.lock" ]] || fail 'A versão anterior não possui atualização segura. Use PDF_INSTALL_DIR em um diretório novo; o aplicativo anterior e suas preferências serão preservados.'
  PDF_ORIGINAL_ID="$(stat -f '%d:%i' "$PDF_DESTINATION")"
fi
cd "$PDF_SOURCE_ROOT"
printf '%s\n' 'Compilando PDF para Apple Silicon…'
xcrun swift build -c release --arch arm64
PDF_BINARY_DIR="$(xcrun swift build -c release --arch arm64 --show-bin-path)"
[[ -x "$PDF_BINARY_DIR/PDF" ]] || fail 'A compilação não gerou o executável PDF.'
PDF_STAGE="$(mktemp -d "$PDF_INSTALL_PARENT/.pdf-install.XXXXXXXX")"
PDF_STAGE_ID="$(stat -f '%d:%i' "$PDF_STAGE")"
PDF_BUNDLE="$PDF_STAGE/PDF.app"
mkdir -p "$PDF_BUNDLE/Contents/Resources/runtime/bin"
# Build the unprivileged process-table witness before dependency downloads.
# Source and portable bundles use the same fixed, application-owned path.
PDF_PROCESS_GROUP_CHECK="$PDF_BUNDLE/Contents/Resources/runtime/bin/pdf-process-group-check"
xcrun clang -arch arm64 -mmacosx-version-min=26.0 -std=c11 -Wall -Wextra -Werror -O2 \
  scripts/ProcessGroupSnapshot.c -lproc -o "$PDF_PROCESS_GROUP_CHECK"
lipo "$PDF_PROCESS_GROUP_CHECK" -verify_arch arm64
xcrun swift scripts/make-icon.swift "$PDF_STAGE/PDF.iconset"
iconutil -c icns "$PDF_STAGE/PDF.iconset" -o "$PDF_BUNDLE/Contents/Resources/PDF.icns"
# Dependencies remain on this Mac. They are not represented as a portable bundle.
export NONINTERACTIVE=1
export HOMEBREW_NO_AUTO_UPDATE=1
brew install python@3.12 qpdf ocrmypdf tesseract-lang openjdk@21
[[ -x /opt/homebrew/bin/qpdf ]] || fail 'O verificador qpdf não foi instalado em /opt/homebrew/bin. Nenhum aplicativo novo será ativado.'
/opt/homebrew/bin/qpdf --version
if [[ ! -x /Applications/LibreOffice.app/Contents/MacOS/soffice ]] && ! command -v soffice >/dev/null 2>&1; then
  brew install --cask libreoffice
fi
PDF_PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
PDF_RUNTIME_ROOT="$HOME/Library/Application Support/PDF/runtimes"
mkdir -p "$PDF_RUNTIME_ROOT"
PDF_RUNTIME="$(mktemp -d "$PDF_RUNTIME_ROOT/install.XXXXXXXX")"
PDF_RUNTIME_ID="$(stat -f '%d:%i' "$PDF_RUNTIME")"
"$PDF_PYTHON" -m venv "$PDF_RUNTIME"
"$PDF_RUNTIME/bin/python3" -m pip install --disable-pip-version-check -r requirements.txt -r requirements-optional.txt
export PDF_JAVA="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home/bin/java"
[[ -x "$PDF_JAVA" ]] || fail 'Java 21 do Homebrew não foi encontrado.'
export PDF_VERAPDF_JAR="$("$PDF_RUNTIME/bin/python3" scripts/install-verapdf.py --directory "$PDF_RUNTIME/share/verapdf")"
"$PDF_JAVA" -jar "$PDF_VERAPDF_JAR" --version
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
  printf 'export PDF_JAVA=%q\n' "$PDF_JAVA"
  printf 'export PDF_VERAPDF_JAR=%q\n' "$PDF_VERAPDF_JAR"
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
<key>CFBundleShortVersionString</key><string>0.7.0</string>
<key>CFBundleVersion</key><string>6</string>
<key>LSMinimumSystemVersion</key><string>26.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSServices</key><array><dict>
<key>NSMenuItem</key><dict><key>default</key><string>Abrir no PDF</string></dict>
<key>NSMessage</key><string>openPDF</string>
<key>NSPortName</key><string>PDF</string>
<key>NSSendFileTypes</key><array><string>com.adobe.pdf</string></array>
<key>NSRequiredContext</key><dict><key>NSApplicationIdentifier</key><string>com.apple.finder</string></dict>
<key>NSServiceDescription</key><string>Abrir os arquivos PDF selecionados para leitura e revisão.</string>
</dict></array>
<key>NSAppleEventsUsageDescription</key><string>O PDF usa o Pages para converter uma cópia dos seus documentos em PDF.</string>
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
"$PDF_PYTHON" scripts/app_intents_metadata.py extract --source-root "$PDF_SOURCE_ROOT" --resources "$PDF_BUNDLE/Contents/Resources"
: > "$PDF_BUNDLE/Contents/Resources/installation.lock"
chmod 444 "$PDF_BUNDLE/Contents/Resources/installation.lock"
plutil -lint "$PDF_BUNDLE/Contents/Info.plist"
# Sign innermost application-owned executable, then seal the complete bundle.
codesign --force --sign - --timestamp=none "$PDF_PROCESS_GROUP_CHECK"
codesign --verify --strict "$PDF_PROCESS_GROUP_CHECK"
codesign --force --sign - --timestamp=none "$PDF_BUNDLE/Contents/MacOS/PDF"
codesign --force --sign - --timestamp=none "$PDF_BUNDLE"
codesign --verify --deep --strict "$PDF_BUNDLE"
printf '%s\n' 'Validando motor, conversões e componentes nativos…'
"$PDF_RUNTIME/bin/python3" -m unittest discover -s tests -v
"$PDF_RUNTIME/bin/python3" -m unittest discover -s tests -p 'integration_*.py' -v
# Hold the same immutable lock inode across preflight, activation and rollback.
# The Python child inherits the shell open-file description; closing the child
# descriptor does not release the lease while this shell keeps FD 8/9 open.
if [[ -n "$PDF_ORIGINAL_ID" ]]; then
  [[ -f "$PDF_DESTINATION/Contents/Resources/installation.lock" && ! -L "$PDF_DESTINATION/Contents/Resources/installation.lock" ]] || fail 'A versão anterior não possui atualização segura. Use PDF_INSTALL_DIR em um diretório novo; o aplicativo anterior e suas preferências serão preservados.'
  exec 9< "$PDF_DESTINATION/Contents/Resources/installation.lock"
  "$PDF_PYTHON" scripts/bundle_lease.py --app "$PDF_DESTINATION" --fd 9
fi
exec 8< "$PDF_BUNDLE/Contents/Resources/installation.lock"
"$PDF_PYTHON" scripts/bundle_lease.py --app "$PDF_BUNDLE" --fd 8
PDF_INSTALLATION_LOCK_FD=8 PDF_INSTALLATION_LOCK_BUNDLE="$PDF_BUNDLE" bash scripts/check-mac.sh "$PDF_BUNDLE"
PDF_STAGED_ID="$("$PDF_PYTHON" "$PDF_FILE_HELPER" identity "$PDF_BUNDLE")"
if [[ -n "$PDF_ORIGINAL_ID" ]]; then
  PDF_BACKUP="$PDF_INSTALL_PARENT/PDF.previous.$(date -u +%Y%m%dT%H%M%SZ).$$.app"
  "$PDF_PYTHON" "$PDF_FILE_HELPER" move "$PDF_DESTINATION" "$PDF_BACKUP" --expected "$PDF_ORIGINAL_ID" >/dev/null
fi
"$PDF_PYTHON" "$PDF_FILE_HELPER" move "$PDF_BUNDLE" "$PDF_DESTINATION" --expected "$PDF_STAGED_ID" >/dev/null
PDF_ACTIVATED=1
PDF_INSTALLATION_LOCK_FD=8 PDF_INSTALLATION_LOCK_BUNDLE="$PDF_DESTINATION" bash scripts/check-mac.sh "$PDF_DESTINATION"
[[ "$("$PDF_PYTHON" "$PDF_FILE_HELPER" identity "$PDF_DESTINATION")" == "$PDF_STAGED_ID" ]] || fail 'O destino mudou durante a verificação final; os bundles foram preservados.'
PDF_SUCCESS=1
printf 'Instalado e verificado: %s\n' "$PDF_DESTINATION"
if [[ -n "$PDF_BACKUP" ]]; then printf 'Versão anterior preservada: %s\n' "$PDF_BACKUP"; fi
printf 'Abra com: open %q\n' "$PDF_DESTINATION"
printf '%s\n' 'Assinatura local ad hoc, sem notarização Apple. Para outro Mac, execute novamente este instalador no próprio computador.'
if [[ ! -d /Applications/Pages.app && ! -d "$HOME/Applications/Pages.app" ]]; then
  printf '%s\n' 'Pages → PDF requer o aplicativo Pages da Apple, disponível gratuitamente na App Store. As demais conversões estão instaladas.'
fi
