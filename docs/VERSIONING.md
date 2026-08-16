# Versionado lcd-monitor-mini (`MAJOR.MINOR.PATCH`)

Formato: **`X.Y.Z`**. Fuente de verdad: archivo [`VERSION`](../VERSION) + tags git `vX.Y.Z`.

Se usa en:
- Inno Setup (`MyAppVersion` / `lcd-monitor-mini-Setup-X.Y.Z.exe`)
- PyInstaller `packaging/version_info.txt`
- `app.__version__`

Este documento es **solo** de lcd-monitor-mini (no compartir con atlas249 u otros repos).

---

## Cuándo subir cada número

| Posición | Cuándo | Ejemplos |
|----------|--------|----------|
| **PATCH** `Z+1` | Bugfix / polish sin capacidad nueva | Freezes COM, Eco mode tweaks, textos UI |
| **MINOR** `Y+1` (`Z→0`) | Feature usable; configs viejas siguen ok | Nuevos estilos TRON, Theme Studio, métricas |
| **MAJOR** `X+1` (`Y,Z→0`) | Ruptura o decisión gorda | Protocolo incompatible, cambio de AppId Inno |

**Regla rápida**

- ¿El usuario de `1.2.0` puede usar la build sin changelog? → **patch**
- ¿Hay algo nuevo que valga mencionar, pero lo viejo sigue ok? → **minor**
- ¿Puede romper instalación/datos sin avisar? → **major**

---

## Cómo se indica el salto (commit a `main`)

En el **mensaje del commit** de merge a `main` (o último commit del push), incluye **una** de:

```text
version: patch
version: minor
version: major
```

También se aceptan tokens en el asunto: `[patch]`, `[minor]`, `[major]`.

| Resultado | Regla |
|-----------|--------|
| Ningún marcador | **patch** (default) |
| `skip release` o `[skip release]` | No empaqueta ni publica GitHub Release |
| Solo docs/workflow sin querer release | Usa `skip release` |

---

## Pipeline

```text
staging  →  CI (compile + import smoke)
main     →  CI → bump VERSION → tag vX.Y.Z → PyInstaller + Inno → GitHub Release
```

- Publicación de binarios: **GitHub Releases** (no Cloudflare R2).
- **No reutilizar** un `X.Y.Z` ya publicado.
- El fix urgente tras `1.2.3` es **`1.2.4`**, no reescribir `1.2.3`.

---

## Primera publicación

`VERSION` arranca en `1.0.0`.

| Objetivo | Cómo |
|----------|------|
| Primera release automática | Merge a `main` con `version: patch` → publica **1.0.1** |
| Empezar en marketing `1.1.0` | `version: minor` desde `1.0.0` |
| Solo docs sin installer | `skip release` en el commit |

---

## Manual (local)

```powershell
./scripts/bump-version.ps1 -Bump minor
./scripts/pack.ps1
```
