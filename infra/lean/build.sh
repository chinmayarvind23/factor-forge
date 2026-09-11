#!/bin/sh
# Compile the explicitly identified launcher graph; never start an algorithm.
set -eu

# Keep a bounded merged log and preserve the child's exit independently of the pipe.
capture() {
    phase="$1"
    shift
    (
        set +e
        "$@"
        result=$?
        printf '%s\n' "$result" > "/output/$phase.exit"
        exit 0
    ) 2>&1 | head -c 16777216 > "/output/$phase.log"
    bytes=$(wc -c < "/output/$phase.log")
    sha256sum "/output/$phase.log"
    printf 'captured_bytes=%s\n' "$bytes"
    if [ "$bytes" -ge 16777216 ]; then
        printf '%s\n' 'Build log reached its cap; capture is incomplete.' >&2
        return 125
    fi
    if [ ! -f "/output/$phase.exit" ]; then
        printf '%s\n' 'Build exit status is missing.' >&2
        return 126
    fi
    result=$(cat "/output/$phase.exit")
    case "$result" in ''|*[!0-9]*) return 126 ;; esac
    return "$result"
}

case "${1:-}" in
  restore)
    dotnet --info
    capture restore dotnet restore Launcher/QuantConnect.Lean.Launcher.csproj \
      --configfile /recipe/NuGet.Config --disable-parallel \
      -p:RestorePackagesWithLockFile=true -p:NuGetAudit=true -p:NuGetAuditMode=all \
      --verbosity minimal
    ;;
  audit)
    capture audit dotnet package list \
      --project Launcher/QuantConnect.Lean.Launcher.csproj \
      --include-transitive --vulnerable --format json --output-version 1 \
      --no-restore --config /recipe/NuGet.Config
    ;;
  compile)
    capture compile dotnet build Launcher/QuantConnect.Lean.Launcher.csproj \
      --configuration Release --no-restore --no-self-contained \
      --disable-build-servers -m:2 -p:UseSharedCompilation=false \
      -nodeReuse:false --nologo --verbosity minimal
    mkdir /output/runtime
    cp -a Launcher/bin/Release/. /output/runtime/
    ;;
  *)
    printf '%s\n' 'Expected restore, audit or compile phase.' >&2
    exit 2
    ;;
esac
