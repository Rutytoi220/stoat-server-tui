# stoat-server-tui (`ss-tui`)

A keyboard-first (`HJKL`) Terminal UI built with [Textual](https://textual.textualize.io/) for managing a self-hosted [Stoat](https://stoat.chat) (Revolt) Docker Compose server — locally or over SSH (with automatic SSH ControlMaster multiplexing).

## Quick Install

### One-line installer (recommended)
```bash
curl -fsSL https://raw.githubusercontent.com/Rutytoi220/stoat-server-tui/main/install.sh | bash
```

### Or directly with `uv` / `pipx`
```bash
uv tool install git+https://github.com/Rutytoi220/stoat-server-tui
# or
pipx install git+https://github.com/Rutytoi220/stoat-server-tui
```

## Usage

```bash
ss-tui                                  # uses ~/.config/ss-tui/config.json or local ~/stoat
ss-tui --host user@server               # manage a remote Stoat server over SSH
ss-tui --host user@server --dir /opt/stoat
ss-tui --local --dir ~/stoat            # run directly on the server
```

### Optional Config (`~/.config/ss-tui/config.json`)
```json
{
  "host": "user@your-server",
  "stoat_dir": "/home/user/stoat"
}
```
Environment variables `STOAT_SSH_HOST`, `STOAT_DIR`, and `STOAT_LOCAL=1` are also supported.

## Features & Keybindings

### Global
| Key | Action |
| --- | --- |
| `1`–`6` | Jump to tab |
| `h` / `l` | Focus sidebar / main pane |
| `j` / `k` / `↑` / `↓` | Move selection / scroll |
| `r` | Refresh current view |
| `?` | Toggle help modal |
| `q` / `Ctrl+C` | Quit |

### Tabs
1. **Dashboard (`1`)**: Stack health, Stoat version, disk/RAM, MongoDB stats, `[R]` Restart All, `[i]` Re-run `inject.js`, `[m]` Auto-Mesh Friends.
2. **Services (`2`)**: Live Docker Compose container list — `[Enter]` View Logs, `[s]` Start, `[x]` Stop, `[R]` Restart, `[F]` Force-Recreate.
3. **Users (`3`)**: Manage accounts & profiles — `[p]` Reset Password (custom or auto-generated, verified via Authifier), `[u]` Unlock / Clear Timeout, `[K]` Revoke Sessions, `[d]` Disable/Enable, `[D]` Delete Account, `[m]` Auto-Mesh Friends.
4. **Limits & Config (`4`)**: View & edit `Revolt.toml` limits (`10GB`, `50MB`, or raw bytes) with automatic service recreation, plus `[i]` Re-run `inject.js`.
5. **Tailscale Funnel (`5`)**: Inspect `tailscale funnel status`.
6. **Logs (`6`)**: Container log viewer with `[` / `]` to switch services and `[o]` to toggle OpenTelemetry log filtering.

## License

MIT
