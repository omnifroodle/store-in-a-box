#!/usr/bin/env bash
# Install Couchbase Edge Server 1.1 for the box.
#   macOS (the Phase 0 box): unpack the vendor zip into box/.edge-server/; nothing is installed outside the checkout.
#   Linux (best-effort, the Pi): install the .deb with apt and the two systemd units in this directory.
# Checksums are the vendor's published .sha256 files for 1.1.0.
set -euo pipefail

EDGE_VERSION=1.1.0
BASE_URL="https://packages.couchbase.com/releases/couchbase-edge-server/${EDGE_VERSION}"
MAC_ZIP_SHA256=65b4b555fd3926a04363626c5ca9307a63dd0008122a576dfab8cffb45b83ef6
DEB_ARM64_SHA256=72181418fca8ba2a2807e0e94beeb9589fa371f61bad6fc4e8539f4b93cda1c6
DEB_AMD64_SHA256=6a330ef8f3a621230ce3a371196c88a77c9bd59ca6ba96cfa87481dcd9ec52e5

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
box="$(dirname "$here")"
repo="$(dirname "$box")"
edge_dir="$box/.edge-server"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

die() { echo "install.sh: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is required"; }
sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }

fetch() { # url expected-sha256 dest
  curl -fsSL --retry 3 -o "$3" "$1" || die "download failed: $1"
  local got
  got="$(sha256 "$3")"
  [[ "$got" == "$2" ]] || die "checksum mismatch for $1 (got $got)"
}

check_python() {
  if command -v uv >/dev/null 2>&1; then return; fi
  command -v python3 >/dev/null 2>&1 || die "uv or python3 (3.12+) is required"
  python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' || die "python3 is older than 3.12; install uv"
}

install_macos() {
  need curl; need unzip; check_python
  local zip="couchbase-edge-server-${EDGE_VERSION}-macos.zip" bin arch
  fetch "$BASE_URL/$zip" "$MAC_ZIP_SHA256" "$tmp/$zip"
  unzip -q "$tmp/$zip" -d "$tmp/unpacked"
  bin="$(find "$tmp/unpacked" -type f -name couchbase-edge-server -perm -u+x | head -n 1)"
  [[ -n "$bin" ]] || die "no couchbase-edge-server binary in $zip"
  arch="$(uname -m)"
  file "$bin" | grep -q "$arch" || die "the binary in $zip does not run on $arch"
  mkdir -p "$edge_dir"
  rm -rf "$edge_dir/dist"
  mv "$tmp/unpacked" "$edge_dir/dist"
  ln -sfn "dist/${bin#"$tmp/unpacked/"}" "$edge_dir/couchbase-edge-server"
  echo "install.sh: Edge Server ${EDGE_VERSION} is at box/.edge-server/couchbase-edge-server"
  echo "next: put the values in .env (see .env.example), then box/run.sh"
}

# ---- Linux: best-effort, for the Pi. Capped at about 60 lines with the two units; see box/README.md.
manual_linux() {
  cat >&2 <<EOF
install.sh: the package did not install cleanly here. Manual steps:
  1. sudo apt-get install ./couchbase-edge-server_${EDGE_VERSION}_<arch>.deb apache2-utils
  2. uv sync && uv run python -m siab_box render-config
  3. box/run.sh --edge-only, and record the result in the needs-verification issue for the Pi.
EOF
  exit 2
}

install_linux() {
  need curl; need apt-get; need systemctl; check_python
  local arch sum deb bin unit
  arch="$(dpkg --print-architecture)"
  case "$arch" in
    arm64) sum="$DEB_ARM64_SHA256" ;;
    amd64) sum="$DEB_AMD64_SHA256" ;;
    *) die "no Edge Server package for $arch" ;;
  esac
  deb="couchbase-edge-server_${EDGE_VERSION}_${arch}.deb"
  fetch "$BASE_URL/$deb" "$sum" "$tmp/$deb"
  sudo apt-get install -y "$tmp/$deb" apache2-utils || manual_linux
  bin="$(dpkg -L couchbase-edge-server | grep '/couchbase-edge-server$' | while read -r f; do
    if [[ -f "$f" && -x "$f" ]]; then echo "$f"; fi; done | head -n 1)"
  [[ -n "$bin" ]] || manual_linux
  mkdir -p "$edge_dir"
  ln -sfn "$bin" "$edge_dir/couchbase-edge-server"
  for unit in couchbase-edge-server siab-box-agent; do
    sed -e "s|@REPO@|$repo|g" -e "s|@EDGE_BIN@|$bin|g" -e "s|@USER@|$(id -un)|g" "$here/$unit.service" |
      sudo tee "/etc/systemd/system/$unit.service" >/dev/null
  done
  sudo systemctl daemon-reload
  sudo systemctl enable couchbase-edge-server siab-box-agent
  echo "install.sh: units enabled, not started. Render the config (uv run python -m siab_box render-config),"
  echo "then: sudo systemctl restart couchbase-edge-server siab-box-agent"
}

case "$(uname -s)" in
  Darwin) install_macos ;;
  Linux) install_linux ;;
  *) die "unsupported OS: $(uname -s)" ;;
esac
