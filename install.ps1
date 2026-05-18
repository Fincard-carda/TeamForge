# TeamForge installer for Windows (PowerShell).
#
# What it does:
#   1. Checks for Python 3.11+ and offers to install via winget if missing
#   2. Creates a .venv virtual environment in the project root
#   3. Installs requirements.txt into the venv
#   4. Copies .env.example to .env so you can fill in your ANTHROPIC_API_KEY
#   5. Optionally starts the orchestrator
#
# Usage:
#   .\install.ps1
# Or (if PowerShell blocks scripts):
#   double-click setup.bat   (uses ExecutionPolicy Bypass)

$ErrorActionPreference = 'Stop'

function Write-Header($text) {
    Write-Host ""
    Write-Host "=== $text ===" -ForegroundColor Cyan
}
function Write-Ok($text)    { Write-Host "[ok] $text"    -ForegroundColor Green  }
function Write-Step($text)  { Write-Host "[..] $text"    -ForegroundColor Yellow }
function Write-Warn($text)  { Write-Host "[!]  $text"    -ForegroundColor Yellow }
function Write-Bad($text)   { Write-Host "[x]  $text"    -ForegroundColor Red    }

Write-Header "TeamForge installer"
Write-Host "Project root: $(Get-Location)"

# ---------------------------------------------------------------------------
# 1) Python check
# ---------------------------------------------------------------------------
function Test-Python {
    try {
        $v = & python --version 2>&1
        if ($v -match 'Python (\d+)\.(\d+)') {
            $major = [int]$matches[1]
            $minor = [int]$matches[2]
            if ($major -eq 3 -and $minor -ge 11) {
                Write-Ok "Python detected: $v"
                return $true
            } else {
                Write-Warn "Python found but too old: $v (need 3.11+)"
            }
        }
    } catch { }
    return $false
}

function Test-Winget {
    try { winget --version | Out-Null; return $true } catch { return $false }
}

if (-not (Test-Python)) {
    Write-Warn "Python 3.11+ is required and was not found on PATH."
    if (Test-Winget) {
        $ans = Read-Host "Install Python 3.12 via winget now? (y/N)"
        if ($ans -match '^[yY]') {
            Write-Step "Running: winget install --id Python.Python.3.12 --silent"
            winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
            # Refresh PATH for current session
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                        [System.Environment]::GetEnvironmentVariable("Path", "User")
            if (-not (Test-Python)) {
                Write-Bad "winget reported success but 'python' still missing on PATH."
                Write-Host "Close this PowerShell window, open a new one, then re-run the installer."
                exit 1
            }
        } else {
            Write-Host "Install Python 3.11+ manually from https://www.python.org/downloads/"
            Write-Host "Then re-run this script."
            exit 1
        }
    } else {
        Write-Bad "winget not available on this system."
        Write-Host "Install Python 3.11+ manually:"
        Write-Host "  https://www.python.org/downloads/"
        Write-Host "(make sure 'Add Python to PATH' is checked during installation)"
        exit 1
    }
}

# ---------------------------------------------------------------------------
# 2) Virtual environment
# ---------------------------------------------------------------------------
if (Test-Path ".venv") {
    Write-Ok ".venv already exists"
} else {
    Write-Step "Creating virtual environment in .venv"
    python -m venv .venv
    Write-Ok ".venv created"
}

# Activate for this script's session
$activate = ".\.venv\Scripts\Activate.ps1"
if (-not (Test-Path $activate)) {
    Write-Bad "Activation script missing at $activate"
    exit 1
}
. $activate
Write-Ok "Virtual environment activated"

# ---------------------------------------------------------------------------
# 3) Dependencies
# ---------------------------------------------------------------------------
Write-Step "Upgrading pip"
python -m pip install --upgrade pip --quiet

if (Test-Path "requirements.txt") {
    Write-Step "Installing requirements.txt (this may take a minute)"
    python -m pip install -r requirements.txt --quiet
    Write-Ok "Dependencies installed"
} else {
    Write-Warn "requirements.txt not found - skipping pip install"
}

# ---------------------------------------------------------------------------
# 4) .env file
# ---------------------------------------------------------------------------
if (Test-Path ".env") {
    Write-Ok ".env already exists - leaving it untouched"
} elseif (Test-Path ".env.example") {
    Copy-Item ".env.example" ".env"
    Write-Ok ".env created from .env.example"
    Write-Host ""
    Write-Warn "You must now open .env and set:"
    Write-Host "    ANTHROPIC_API_KEY=sk-ant-api03-..."
    Write-Host "  Get a key at: https://console.anthropic.com/settings/keys"
    Write-Host ""
    $open = Read-Host "Open .env in Notepad now? (y/N)"
    if ($open -match '^[yY]') { notepad .env | Out-Null }
} else {
    Write-Warn ".env.example missing - cannot bootstrap .env"
}

# ---------------------------------------------------------------------------
# 5) Summary + optional start
# ---------------------------------------------------------------------------
Write-Header "Setup complete"
Write-Host "Next steps:"
Write-Host "  1. Make sure ANTHROPIC_API_KEY is set in .env"
Write-Host "  2. Start the orchestrator:  python -m orchestrator"
Write-Host "  3. The dashboard opens at http://127.0.0.1:7777 (setup wizard greets you)"
Write-Host ""
$start = Read-Host "Start the orchestrator now? (y/N)"
if ($start -match '^[yY]') {
    Write-Host ""
    Write-Step "Starting: python -m orchestrator"
    python -m orchestrator
}
