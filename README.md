<p align="center">
  <img src="app/static/favicon/android-chrome-192x192.png" width="64" alt="logo">
</p>

<h1 align="center">Discord Notification Scheduler</h1>

<p align="center">
  A self-hosted web app to schedule and send Discord webhook messages at specific
  times. Runs entirely in Docker with no host dependencies.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPLv3-blue.svg" alt="License: GPL v3"></a>
</p>

<p align="center">
  Built by <a href="https://desynkro.com">DeSynkro</a>
  with assistance from <a href="https://opencode.ai">Opencode</a>.
</p>

<p align="center">
  Made with love for the community, and a special thank you to everyone who was
  welcoming and kind, it means a lot.
</p>

## Requirements

- [Docker](https://docs.docker.com/engine/install/) with the Compose plugin

## Quick start

### First time

```bash
git clone https://codeberg.org/DeSynkro/discord-notification-scheduler.git
cd discord-notification-scheduler
mkdir -p data
sudo chown -R 1001:1001 data/
docker compose up -d
```

Open [http://localhost:9001](http://localhost:9001)

### Update to latest version

```bash
git pull
docker compose up --build -d
```

**Webhook URLs** must match the Discord format:
`https://discord.com/api/webhooks/<id>/<token>`

## Screenshots

<p align="center">
  <a href="./app/static/screenshots/dashboard.webp" target="_blank">
    <img src="app/static/screenshots/dashboard.webp" width="48%" alt="Dashboard">
  </a>
  <a href="./app/static/screenshots/alarm-form.webp" target="_blank">
    <img src="app/static/screenshots/alarm-form.webp" width="48%" alt="Alarm form">
  </a>
</p>

## Why this exists

There are plenty of hosted services that can fire a webhook on a schedule. but
they require trust, trust that your webhook URL wont be logged, trust that
your message content isn't mined, trust that the service will be around next
month.

This project flips that. You run it on your own machine, your own network,
your own terms. No signup, no API keys to a third party, no vendor lock-in.
Just Docker and a JSON file you can copy with one command.

## Features

-   **Self-hosted and private** - runs on your hardware, zero cloud
    dependencies
-   **Zero telemetry** - no analytics, no tracking, no phone-home, no CDN
-   **Your data, your rules** - webhooks and alarms stored as plain JSON,
    fully portable, backup by copying one folder
-   **SSRF-safe** - webhook URLs validated against Discords exact pattern;
    no arbitrary outbound requests
-   **Minimal outbound traffic** - the only data leaving your machine is the
    message you scheduled, delivered to Discord over HTTPS; no CDN, no font
    hosts, no third-party servers
-   One `docker compose up` and done
-   Dark-themed web UI using HTMX and FastAPI
-   Plain text and rich embed messages (title, optional color picker)
-   Per-alarm timezone override with searchable autocomplete
-   Markdown preview in the compose form
-   60-second polling loop, no external cron needed
-   429 rate-limit handling with Retry-After backoff
-   Test button to fire any alarm or webhook on demand

## What data is stored?

| Kept | Not kept |
|------|----------|
| Webhook URL (Discord endpoint) | No analytics |
| Alarm schedule and message content | No telemetry of any kind |
| Last-fired and last-error timestamps | No logs sent anywhere |
| | No user accounts, emails, or IPs |
| | No cookies, no fingerprinting |

The only network request leaving your network is the webhook POST to Discord.
HTMX, fonts, and all other assets are served directly from the app itself,
   with no CDN, analytics, or third-party servers contacted on page load.

## Tech Stack

| Layer | How |
|-------|-----|
| Backend | Python 3.12 + FastAPI |
| Frontend | HTMX + Jinja2 (no JavaScript framework) |
| Styling | CSS with dark theme and subtle gradients |
| Scheduler | APScheduler (AsyncIOScheduler, 60s polling loop) |
| HTTP | httpx (async) |
| Validation | Pydantic v2 |
| Container | Docker / Docker Compose (single container) |
| Persistence | Plain JSON files (no database) |

## Project structure

```text
├── docker-compose.yml      Single service, port 9001
├── Dockerfile              python:3.12-slim, non-root (uid 1001)
├── requirements.txt        Python dependencies
├── .gitignore              Git rules
├── LICENSE                 GPL v3
├── README.md               This file
├── app/
│   ├── __init__.py
│   ├── main.py             FastAPI routes and HTMX handlers
│   ├── models.py           Pydantic schemas with validation
│   ├── storage.py          Thread-safe atomic JSON read/write
│   ├── scheduler.py        60-second polling loop
│   ├── discord.py          Async webhook sender with rate-limit handling
│   ├── templates/
│   │   └── index.html      Single-page dashboard
│   └── static/
│       ├── style.css       Dark theme styles
│       ├── htmx.min.js     HTMX v2.0.4 (self-hosted)
│       ├── desynkro.png    DeSynkro logo
│       ├── fonts/          Inter variable font (self-hosted)
│       ├── favicon/        Full favicon set
│       └── screenshots/    Dashboard and alarm form previews
└── data/                  Auto-created at startup (gitignored)
    ├── alarms.json
    └── webhooks.json
```

## Troubleshooting

### Permission errors on data/

The container runs as uid 1001 and needs write access to `./data/`. If you see
permission errors, the files are likely owned by your host user:

```bash
mkdir -p data
sudo chown -R 1001:1001 data/
```

This only needs to run once (or after you delete and recreate the data folder).

### Port conflict

The dashboard listens on port 9001. To change it, edit the `ports:` line in
`docker-compose.yml`:

```yaml
ports:
  - "9001:9001"    # change left side to your preferred port
```

## License

GNU General Public License v3.0 or later. See [LICENSE](LICENSE).

## Credits

-   Built by [DeSynkro](https://desynkro.com)
-   Assisted by [Opencode](https://opencode.ai)
-   Thank you to the self-hosted and Discord communities for being welcoming

<p align="center">
  <a href="https://desynkro.com" target="_blank">
    <img src="app/static/desynkro.png" width="300"
         alt="DeSynkro"
         style="background:#0d1117;border-radius:8px;padding:8px 14px">
  </a>
</p>
