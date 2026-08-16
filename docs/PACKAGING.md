# lcd-monitor-mini – empaquetado Windows + GitHub Releases

Flujo **específico de este repo**. No usa Velopack, Cloudflare R2, ni scripts de atlas249.

## Versionado

Ver [VERSIONING.md](VERSIONING.md). Fuente: archivo `/VERSION`.

| Acción | Comando / evento |
|--------|------------------|
| Indicar salto | En commit a `main`: `version: patch` \| `minor` \| `major` |
| No publicar | `skip release` o `[skip release]` |
| Manual | GitHub → Actions → **Release** → Run workflow |

## Secrets

No se requieren secrets extra. `GITHUB_TOKEN` (permiso `contents: write`) basta para tag + GitHub Release.

## Pack (local)

Requisitos: `.venv` con `requirements-app.txt`, [Inno Setup 6](https://jrsoftware.org/isinfo.php).

```powershell
# Usa VERSION del repo (+ sync packaging / __version__)
./scripts/pack.ps1

# O forzar versión
./scripts/pack.ps1 -Version 1.2.3
```

Artefactos:

| Archivo | Descripción |
|---------|-------------|
| `dist\lcd-monitor-mini\lcd-monitor-mini.exe` | Onedir portable |
| `dist\lcd-monitor-mini-Setup-X.Y.Z.exe` | Instalador Inno |

## CI / Release (GitHub Actions)

| Workflow | Rama | Qué hace |
|----------|------|----------|
| `CI` | `staging`, `main` (+ PRs) | compileall + import smoke |
| `Release` | solo `main` | bump → tag → pack → **GitHub Release** (Setup + zip) |

El workflow de Release **no** sube a R2 ni a ningún feed externo.

## Notas

- SmartScreen puede avisar hasta firmar Authenticode (fuera de alcance).
- Icono de build: `packaging/icon.png` / `icon.ico` (en CI no se usa el icono del Desktop).
