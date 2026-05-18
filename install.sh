#!/usr/bin/env bash
# TeamForge installer for macOS and Linux.
#
# What it does:
#   1. Checks for Python 3.11+ and offers to install via brew/apt/dnf if missing
#   2. Creates a .venv virtual environment in the project root
#   3. Installs requirements.txt into the venv
#   4. Copies .env.example to .env so you can fill in your ANTHROPIC_API_KEY
#   5. Optionally starts the orchestrator
#
# Usage:
#   bash install.sh
# or, after `chmod +x install.sh`:
#   ./install.sh

set -e

# ---- pretty printing ------------------------------------------------------
cyan()  { printf '\033[36m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yel()   { printf '\033[33m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*"; }

header() { printf '\n'; cyan "=== $1 ==="; }
ok()     { green "[ok] $1"; }
step()   { yel   "[..] $1"; }
warn()   { yel   "[!]  $1"; }
bad()    { red   "[x]  $1"; }

cd "$(dirname "$0")"
header "TeamForge installer"
echo "Project root: $(pwd)"

# ---- 1) Python check ------------------------------------------------------
check_python() {
    local cmd="${1:-python3}"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        return 1
    fi
    local ver
    ver=$("$cmd" -c 'import sys; print("%d.%d" % (sys.version_info[0], sys.version_info[1]))' 2>/dev/null || echo "0.0")
    local major="${ver%%.*}"
    local minor="${ver##*.}"
    if [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; then
        ok "Python detected: $($cmd --version)"
        PY="$cmd"
        return 0
    fi
    warn "$cmd is too old (need 3.11+): $($cmd --version 2>&1)"
    return 1
}

PY=""
if check_python python3 || check_python python; then
    :
else
    warn "Python 3.11+ is required and was not found."
    read -r -p "Install Python via your package manager now? (y/N) " ans
    if [[ "$ans" =~ ^[yY]$ ]]; then
        case "$OSTYPE" in
            darwin*)
                if command -v brew >/dev/null 2>&1; then
                    step "brew install python@3.12"
                    brew install python@3.12
                else
                    bad "Homebrew not found."
                    echo "Install Homebrew first: https://brew.sh"
                    exit 1
                fi
                ;;
            linux*)
                if command -v apt-get >/dev/null 2>&1; then
                    step "sudo apt-get update && sudo apt-get install python3 python3-venv python3-pip"
                    sudo apt-get update
                    sudo apt-get install -y python3 python3-venv python3-pip
                elif command -v dnf >/dev/null 2>&1; then
                    step "sudo dnf install python3 python3-pip"
                    sudo dnf install -y python3 python3-pip
                elif command -v pacman >/dev/null 2>&1; then
                    step "sudo pacman -S python python-pip"
                    sudo pacman -S --noconfirm python python-pip
                else
                    bad "No supported package manager found (apt/dnf/pacman)."
                    echo "Install Python 3.11+ manually."
                    exit 1
                fi
                ;;
            *)
                bad "Unsupported OS: $OSTYPE"
                echo "Install Python 3.11+ manually from https://www.python.org/downloads/"
                exit 1
                ;;
        esac
        check_python python3 || { bad "Python install seems to have failed."; exit 1; }
    else
        echo "Install Python 3.11+ manually and re-run this script."
        exit 1
    fi
fi

# ---- 2) Virtual environment ----------------------------------------------
if [ -d ".venv" ]; then
    ok ".venv already exists"
else
    step "Creating virtual environment in .venv"
    "$PY" -m venv .venv
    ok ".venv created"
fi

# shellcheck disable=SC1091
. .venv/bin/activate
ok "Virtual environment activated"

# ---- 3) Dependencies ------------------------------------------------------
step "Upgrading pip"
python -m pip install --upgrade pip --quiet

if [ -f "requirements.txt" ]; then
    step "Installing requirements.txt (this may take a minute)"
    python -m pip install -r requirements.txt --quiet
    ok "Dependencies installed"
else
    warn "requirements.txt not found - skipping pip install"
fi

# ---- 4) .env file ---------------------------------------------------------
if [ -f ".env" ]; then
    ok ".env already exists - leaving it untouched"
elif [ -f ".env.example" ]; then
    cp .env.example .env
    ok ".env created from .env.example"
    echo ""
    warn "You must now open .env and set:"
    echo "    ANTHROPIC_API_KEY=sk-ant-api03-..."
    echo "  Get a key at: https://console.anthropic.com/settings/keys"
else
    warn ".env.example missing - cannot bootstrap .env"
fi

# ---- 5) Summary + optional start -----------------------------------------
header "Setup complete"
echo "Next steps:"
echo "  1. Make sure ANTHROPIC_API_KEY is set in .env"
echo "  2. Start the orchestrator:  python -m orchestrator"
echo "  3. The dashboard opens at http://127.0.0.1:7777 (setup wizard greets you)"
echo ""

read -r -p "Start the orchestrator now? (y/N) " start
if [[ "$start" =~ ^[yY]$ ]]; then
    echo ""
    step "Starting: python -m orchestrator"
    python -m orchestrator
fi
