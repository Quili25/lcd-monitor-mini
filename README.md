# lcd-monitor-mini

Open-source Windows tray app that drives a **3.5″ USB serial LCD** (chip id `USB35INCHIPSV2`, VID `1A86` / PID `5722`, often on **COM4**): system metrics, themes, and a small Theme Studio.

I use it day to day; anyone else can run, fork, or build it too.

Protocol research notes: [docs/PROTOCOL-REV-A.md](docs/PROTOCOL-REV-A.md).

## Download (Windows)

Prefer the installer from **[Releases](https://github.com/Quili25/lcd-monitor-mini/releases)**:

| Asset | Use |
|-------|-----|
| `lcd-monitor-mini-Setup-*.exe` | Recommended (Inno Setup) |
| `lcd-monitor-mini-*-windows-x64.zip` | Portable onedir |

Windows SmartScreen may warn until the binary is Authenticode-signed.

Config and themes live in `%LOCALAPPDATA%\lcd-monitor-mini\` (writable). Older local data folders are migrated on first run when present.

## Requirements

- Windows 10/11 x64
- Compatible **3.5″ Rev A** USB serial LCD (see VID/PID above)
- Free COM port (close any other app that already opened the panel)

## Dev quick start

```powershell
git clone https://github.com/Quili25/lcd-monitor-mini.git
cd lcd-monitor-mini
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-app.txt
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

Tray: right-click → Settings / Theme Studio / Stop / Exit.

Optional helpers under `scripts/` can free the COM port if another monitor utility is holding it.

### Build installer locally

Needs [Inno Setup 6](https://jrsoftware.org/isinfo.php).

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\pack.ps1
```

Artifacts: `dist\lcd-monitor-mini\` and `dist\lcd-monitor-mini-Setup-<VERSION>.exe`.

## Features

- Metrics: CPU / GPU / RAM / disk / net / volume / time (+ optional weather)
- Portrait / landscape + 180° flip
- Theme hot-swap and in-app **Theme Studio**
- Eco mode (lighter refresh / USB)
- Autostart
- Soft/hard COM recovery (avoids leaving the device PnP-disabled)

## Versioning & release

SemVer — [docs/VERSIONING.md](docs/VERSIONING.md), [docs/PACKAGING.md](docs/PACKAGING.md).  
Canonical file: [`VERSION`](VERSION).

Branches: **`staging`** → **`main`** (production).

On commits to `main`:

```text
version: patch   # default if omitted
version: minor
version: major
skip release     # no pack / no GitHub Release
```

Push to `main` runs Actions **Release**: bump → tag `vX.Y.Z` → Windows pack → **GitHub Release**.

## Recovery

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\reset-display.ps1 -SoftOnly
powershell -ExecutionPolicy Bypass -File .\scripts\reset-display.ps1 -Elevate
```

## Layout

| Path | Purpose |
|------|---------|
| `app/` | Product code (session, UI, renderer) |
| `packaging/` | PyInstaller, Inno, seed, icon |
| `themes/omar/` | Default theme (seeded into AppData) |
| `config.yaml` | Dev / seed defaults |
| `vendor/` | Trimmed upstream GPL reference + JetBrains Mono |
| `scripts/` | run / pack / reset / COM helpers |

## Config notes

- `REVISION: A`, `COM_PORT: AUTO` (or `COM4`)
- `THEME: omar`, `DISPLAY_ORIENTATION: portrait|landscape`
- `ECO_MODE: true` (recommended)
- `RESET_ON_STARTUP: false`

## License

**[GNU General Public License v3.0](LICENSE)** (`GPL-3.0`).

Third-party code and fonts under `vendor/` keep their own licenses (see `vendor/README.md`).

Copyright (c) 2026 Omar.
