#!/usr/bin/env bash
# install.sh - installer for credit-scanner
# https://github.com/entropytwo-ai/abacusai-transcript-credit-analysis
#
# Copyright (C) 2026 Andrew Graham (entropytwo-ai)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# One-line install (to ~/.local/bin):
#   curl -fsSL https://raw.githubusercontent.com/entropytwo-ai/abacusai-transcript-credit-analysis/main/install.sh | bash
# System-wide (to /usr/local/bin, uses sudo when needed):
#   curl -fsSL https://raw.githubusercontent.com/entropytwo-ai/abacusai-transcript-credit-analysis/main/install.sh | bash -s -- --system
# Uninstall:
#   curl -fsSL https://raw.githubusercontent.com/entropytwo-ai/abacusai-transcript-credit-analysis/main/install.sh | bash -s -- --uninstall

set -euo pipefail

REPO="entropytwo-ai/abacusai-transcript-credit-analysis"
REF="${CREDIT_SCANNER_REF:-main}"
NAME="credit-scanner"
PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR=""
FROM=""
ACTION="install"
REF_SET=0

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf 'install.sh: warning: %s\n' "$*" >&2; }
die()  { printf 'install.sh: error: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<EOF
credit-scanner installer

Usage: install.sh [OPTIONS]

Options:
  --prefix DIR     Install to DIR/bin (default: \$HOME/.local, or \$PREFIX)
  --bin-dir DIR    Install directly into DIR (overrides --prefix)
  --system         Same as --prefix /usr/local (uses sudo if needed)
  --name NAME      Command name (default: credit-scanner)
  --ref REF        Git branch/tag to download (default: main)
  --from FILE      Install from a local credit-scanner.sh instead of downloading
  --uninstall      Remove the installed command
  -h, --help       Show this help

Run from a git checkout, the local credit-scanner.sh is used automatically.
EOF
}

while (($#)); do
    case $1 in
        --prefix)    [[ $# -ge 2 ]] || die "--prefix needs a DIR"; PREFIX=$2; shift ;;
        --prefix=*)  PREFIX=${1#*=} ;;
        --bin-dir)   [[ $# -ge 2 ]] || die "--bin-dir needs a DIR"; BIN_DIR=$2; shift ;;
        --bin-dir=*) BIN_DIR=${1#*=} ;;
        --system)    PREFIX=/usr/local ;;
        --name)      [[ $# -ge 2 ]] || die "--name needs a NAME"; NAME=$2; shift ;;
        --name=*)    NAME=${1#*=} ;;
        --ref)       [[ $# -ge 2 ]] || die "--ref needs a REF"; REF=$2; REF_SET=1; shift ;;
        --ref=*)     REF=${1#*=}; REF_SET=1 ;;
        --from)      [[ $# -ge 2 ]] || die "--from needs a FILE"; FROM=$2; shift ;;
        --from=*)    FROM=${1#*=} ;;
        --uninstall) ACTION="uninstall" ;;
        -h|--help)   usage; exit 0 ;;
        *)           die "unknown option '$1' (see --help)" ;;
    esac
    shift
done

[[ -n $BIN_DIR ]] || BIN_DIR="${PREFIX%/}/bin"
[[ $NAME =~ ^[A-Za-z0-9._-]+$ ]] || die "invalid command name '$NAME'"
TARGET="$BIN_DIR/$NAME"

# Use sudo only when the destination is not writable by the current user.
SUDO=()
needs_sudo() {
    local d=$1
    while [[ ! -e $d ]]; do d=$(dirname "$d"); done
    [[ ! -w $d ]]
}
as_root() { if ((${#SUDO[@]})); then sudo "$@"; else "$@"; fi; }
if [[ $EUID -ne 0 ]] && needs_sudo "$BIN_DIR"; then
    command -v sudo >/dev/null 2>&1 || die "'$BIN_DIR' is not writable and sudo is not available (try --prefix \$HOME/.local)"
    SUDO=(sudo)
    say "'$BIN_DIR' needs elevated permissions; using sudo"
fi

if [[ $ACTION == uninstall ]]; then
    if [[ -e $TARGET || -L $TARGET ]]; then
        as_root rm -f "$TARGET"
        say "Removed $TARGET"
    else
        warn "$TARGET is not installed"
        for alt in "$HOME/.local/bin/$NAME" "/usr/local/bin/$NAME"; do
            if [[ $alt != "$TARGET" && -e $alt ]]; then
                warn "found another copy at $alt (remove it with --bin-dir $(dirname "$alt"))"
            fi
        done
    fi
    exit 0
fi

# ---- preflight: runtime requirements of credit-scanner itself ----------------
say "Checking runtime requirements"
missing=()
for c in bash awk sort wc grep date mktemp chmod mkdir; do
    command -v "$c" >/dev/null 2>&1 || missing+=("$c")
done
((${#missing[@]} == 0)) || die "missing required command(s): ${missing[*]}"
bash_major=$(bash -c 'echo "${BASH_VERSINFO[0]}"')
[[ $bash_major -ge 4 ]] || die "credit-scanner needs bash 4+ as 'bash' on PATH (found bash $bash_major); on macOS: brew install bash"
awk_ok=$(LC_ALL=C awk 'BEGIN { s = sprintf("%.2f", 1234.5); if (match("ab12", /[0-9]+$/)) print s "-" RSTART }' 2>/dev/null || true)
[[ $awk_ok == "1234.50-3" ]] || die "your awk does not behave like a POSIX awk (got '$awk_ok')"

# ---- obtain the script ------------------------------------------------------------
TMP=$(mktemp -d 2>/dev/null || mktemp -d -t credit-scanner-install)
trap 'rm -rf "$TMP"' EXIT
SRC="$TMP/credit-scanner.sh"

self_dir=""
if [[ -n ${BASH_SOURCE[0]:-} && -f ${BASH_SOURCE[0]} ]]; then
    self_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
fi
if [[ -z $FROM && $REF_SET -eq 0 && -n $self_dir && -f $self_dir/credit-scanner.sh ]]; then
    FROM="$self_dir/credit-scanner.sh"
fi

if [[ -n $FROM ]]; then
    [[ -f $FROM ]] || die "'$FROM' does not exist"
    say "Using local file $FROM"
    cp "$FROM" "$SRC"
else
    url="https://raw.githubusercontent.com/$REPO/$REF/credit-scanner.sh"
    say "Downloading $url"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --retry 3 -o "$SRC" "$url" || die "download failed: $url"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$SRC" "$url" || die "download failed: $url"
    else
        die "need curl or wget to download $url"
    fi
fi

# ---- verify before installing --------------------------------------------------------
say "Verifying script"
[[ -s $SRC ]] || die "downloaded file is empty"
[[ $(head -n 1 "$SRC") == "#!/usr/bin/env bash" ]] || die "downloaded file is not the credit-scanner script (bad shebang)"
grep -q '^readonly VERSION=' "$SRC" || die "downloaded file is not the credit-scanner script (no VERSION)"
bash -n "$SRC" || die "downloaded script has syntax errors"
bash "$SRC" --self-test >"$TMP/selftest.log" 2>&1 || { cat "$TMP/selftest.log" >&2; die "self-test failed; not installing"; }

# ---- install ---------------------------------------------------------------------------
say "Installing to $TARGET"
as_root mkdir -p "$BIN_DIR"
as_root cp "$SRC" "$TARGET.tmp.$$"
as_root chmod 0755 "$TARGET.tmp.$$"
as_root mv -f "$TARGET.tmp.$$" "$TARGET"

# ---- verify the installed copy (runs through its own shebang) --------------------------
say "Verifying installed command"
version=$("$TARGET" --version 2>&1) || die "installed command does not run: $version"
"$TARGET" --self-test >"$TMP/selftest2.log" 2>&1 || { cat "$TMP/selftest2.log" >&2; die "installed command failed its self-test"; }
say "Installed $version -> $TARGET (self-test passed)"

case ":$PATH:" in
    *":$BIN_DIR:"*)
        say "Run '$NAME --help' to get started." ;;
    *)
        warn "$BIN_DIR is not on your PATH."
        echo "  Add it for bash:   echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
        echo "  NixOS/home-manager: home.sessionPath = [ \"$BIN_DIR\" ];"
        echo "  Or run it directly: $TARGET --help" ;;
esac
