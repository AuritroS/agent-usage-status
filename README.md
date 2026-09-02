# Agent Usage Widget

A small iPhone home-screen widget showing remaining Codex and Claude Code
usage, and when each resets.

<!-- add a screenshot or two here -->

Monochrome and minimal by design — bar length carries the signal, no
colors, no clutter.

## How it works

A local script checks Codex/Claude usage every 5 minutes and saves it to a
JSON file. A small local server hands that file out over the internet
(behind an API key), and a [Scriptable](https://scriptable.app) script on
the phone fetches it and draws the widget.

```
agent_usage_status.py --> agent-usage-status.json --> serve.py --> tunnel --> iPhone
  checks usage              just a file               serves it,   exposes    widget
                                                        API-key      it
                                                        gated
```

## What's in here

- `agent_usage_status.py` — polls the `codex` and `claude` CLIs, writes `agent-usage-status.json`.
- `serve.py` — serves that file locally, only responding to requests with the right API key.
- `systemd/` — background services that keep the above two running automatically.
- `agent-usage-widget.js` — the Scriptable script that draws the widget on the phone.
- `set-agent-usage-widget-key.js` — a one-time script that saves the API key to the iPhone's Keychain.

## Setting it up

Requires the `codex` and `claude` CLIs installed and logged in, plus some
way to expose a local port to the internet over HTTPS — built using a
Cloudflare Tunnel, but any reverse proxy or something like Tailscale works
too.

**1. Get the files in place**

Clone this repo to `~/agent-usage-widget` (the systemd files assume that
exact path — edit them if placed elsewhere).

**2. Make an API key**

```
mkdir -p ~/.config/agent-usage-widget
echo "API_KEY=$(openssl rand -hex 32)" > ~/.config/agent-usage-widget/api-key.env
chmod 600 ~/.config/agent-usage-widget/api-key.env
```

**3. Set up a tunnel**

With Cloudflare:

```
cloudflared tunnel login
cloudflared tunnel create agent-usage-widget
cloudflared tunnel route dns agent-usage-widget usage.example.com
```

Copy `systemd/cloudflared-config.yml.example` to `~/.cloudflared/config.yml`
and fill in the actual path and hostname.

**4. Turn on the background services**

```
cp systemd/*.service systemd/*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agent-usage-status.timer agent-usage-server.service agent-usage-tunnel.service
loginctl enable-linger "$USER"
```

Once running, `https://usage.example.com/agent-usage-status.json` should
return "unauthorized" without a key, and real data with the correct
`X-Api-Key` header.

**5. Set up the widget on the phone**

- In Scriptable, create a new script, paste in `agent-usage-widget.js`, and
  change the `URL` at the top to the actual endpoint from step 3.
- Create another new script, paste in `set-agent-usage-widget-key.js`, fill
  in the API key, and run it once (tap play, don't add it as a widget) —
  this saves the key to the Keychain. Delete this script afterward.
- Add two small widgets to the home screen, both pointing at
  `agent-usage-widget.js`. Long-press each, open Edit Widget, and set the
  Parameter field to `codex` on one and `claude` on the other.

End result: two widgets, updating roughly every 10 minutes.
