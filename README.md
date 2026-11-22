# stoat-server-tui

A terminal UI (`ss-tui`) for managing a self-hosted [Stoat](https://stoat.chat) (Revolt) Docker Compose server, either locally or over SSH.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Rutytoi220/stoat-server-tui/main/install.sh | bash
```

Or with `uv` / `pipx`:

```bash
uv tool install git+https://github.com/Rutytoi220/stoat-server-tui
```

## Usage

```bash
ss-tui                              # uses ~/.config/ss-tui/config.json or ~/stoat
ss-tui --host user@server           # manage over SSH
ss-tui --local --dir ~/stoat        # run directly on the server
```

Optional config in `~/.config/ss-tui/config.json`:

```json
{
  "host": "user@your-server",
  "stoat_dir": "/home/user/stoat"
}
```

### Tabs & keys

- `1`–`6` — Dashboard, Services, Users, Limits & Config, Tailscale Funnel, Logs
- `j` / `k`, `h` / `l` — navigate
- `r` — refresh, `?` — help, `q` — quit
- **Services**: `Enter` logs, `s` start, `x` stop, `R` restart, `F` force-recreate
- **Users**: `p` reset password, `u` unlock, `K` revoke sessions, `d` disable/enable, `D` delete

## License

MIT
