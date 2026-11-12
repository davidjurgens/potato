# Sharing a Task on a Temporary URL

`potato share` runs your task and puts it on a public HTTPS URL for as long as
the command is running.

```bash
potato share myproject/config.yaml
```

```
Tunnel backend: cloudflared
Starting Potato on 127.0.0.1:8000 ...
Opening tunnel ...

==============================================================
  https://plain-marble-ridge-fx.trycloudflare.com
==============================================================

This link works only while this command is running.
Press Ctrl-C to stop.
```

Send that link to a colleague, open it on your phone, or hand it to a pilot
participant. It works from anywhere.

## The URL dies with the terminal

The server is running in your terminal. The URL dies when you press Ctrl-C,
when the laptop sleeps, and when the wifi changes. Annotations are written to
your own disk, which is the one good thing about it — there is nothing to pull
back.

Use it for a pilot, a lab meeting, or handing someone a link for twenty
minutes. For anything a participant might come back to tomorrow,
[deploy it somewhere](one-command-deploy.md).

## Exposure

Whatever your config allows, it allows to the entire internet for as long as
the command runs. `share` runs the same preflight a real deploy does and prints
the same exposure summary, then asks before opening anything:

```
Exposure:
  Reachable from the public internet: yes
  Sign-in: open — anyone with the URL can create an account
  ...
Publish this task to the internet? [y/N]
```

Open registration is reported rather than blocked, because for a crowdsourced
pilot it is usually the point. To restrict it:

```yaml
user_config:
  allow_all_users: false
  users:
    - alice@example.edu
    - bob@example.edu
```

`--yes` skips the prompt. `--skip-preflight` skips the assessment entirely and
is a bad idea for a link you are about to send to someone.

## Choosing a tunnel

Three backends. Potato uses whichever is installed, in this order, and
`--backend` picks one explicitly.

| Backend | Account | Notes |
|---|---|---|
| `cloudflared` | none | The default. Some networks filter it — see below |
| `tailscale` | yes | Serves on `*.ts.net`; the node must already be logged in |
| `ngrok` | yes | Shows visitors an interstitial page first |

```bash
brew install cloudflared          # no account at all
brew install tailscale            # then: tailscale up
brew install ngrok                # then: set NGROK_AUTHTOKEN
```

**Cloudflare quick tunnels get filtered.** `trycloudflare.com` has been used
heavily enough for malware staging that university proxies and mail gateways
now block it — which is exactly the sort of network a study participant sits
behind. If someone reports that the link does not load, that is usually why,
and `--backend tailscale` is the way out.

Tailscale has a second advantage: `ts.net` is on the Public Suffix List, so
browsers isolate cookies per host. `trycloudflare.com` is not, which means any
other quick tunnel could set a cookie your Flask session would accept. For a
twenty-minute pilot this is theoretical; for anything longer it is a reason to
prefer Tailscale or a real host.

## Options

```
potato share config.yaml [-p PORT] [--backend NAME] [--yes] [--skip-preflight]
```

`-p` sets the local port, which matters only if 8000 is taken. The server binds
to `127.0.0.1` regardless, so the tunnel is the only route in.

## The two processes

`share` starts two processes and watches both. The server binds to loopback
with `POTATO_PROXY_FIX=1` set, so `url_for` and session cookies use the
external scheme and host rather than `http://127.0.0.1`. The tunnel client runs
alongside it, and Potato reads the assigned hostname out of its output.

If either process exits, `share` stops the other and tells you which one went.

## Troubleshooting

**`No tunnel backend found`** — install one of the three above. The message
lists them with their install commands.

**`cloudflared exited before publishing a URL`** — the last twenty lines of its
output are printed underneath. This is usually a network that blocks Cloudflare
outright.

**`The server did not come up`** — the task itself failed to start, and the
message prints the exact `potato start` command to run so you can see the
error.

**Participants report a blocked or suspicious link** — that is
`trycloudflare.com` being filtered. Use `--backend tailscale`, or move to
[a real host](one-command-deploy.md), which gives you an ordinary HTTPS URL
that nothing filters.

## Related

- [Deploying a task](one-command-deploy.md) — the hosted alternatives
- [Running it on your own machine](deploy-local.md) — the same server with no
  public URL at all
- [Render](deploy-render.md) — a free host for something that has to outlive
  the terminal
