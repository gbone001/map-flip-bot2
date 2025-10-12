# HLL Map Switcher Bot

Discord bot that posts a persistent control panel message so authorised members can flip Hell Let Loose maps and set objectives through CRCONv2. Operators pick a server, review the live status (current/next map + objectives), then launch guided flows to either change the map (game type → map → time variant) or update the five objective slots. Every action pulls source data directly from CRCON so the UI stays in sync with the server.

## Quick Start

1. Copy `.env.example` to `.env` and fill in the values:
   - Discord bot token, guild ID, and channel ID.
   - Optional permitted role IDs (comma separated).
   - CRCON base URL and API token (Django token).
   - Optional direct RCON connection info if you plan future TCP extensions.
   - Populate `src/data/servers.json` with each server’s CRCON base URL and token (falls back to `servers.example.json`).
2. Install Python dependencies and run the bot:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.bot
```

The bot requires Python 3.10+ and `discord.py` 2.4.

## Features

- **Server-aware control panel** – A persistent message lets staff pick a server and immediately see current map, next map, time remaining, and the live objective layout.
- **Guided map changes** – Clicking “Change Map” walks through game type selection, CRCON-fetched map list, and time-of-day variants before pushing a `ChangeMap` command with the chosen map ID.
- **Objective wizard** – Clicking “Set Objectives” loads the five-by-three layout options from CRCON, lets officers pick all five slots, then applies them via `SetSectorLayout`.
- **Automatic embeds** – After any change the bot refreshes the control panel embed by calling `/api/get_public_info` and `GetSectorLayout` so the message reflects the latest state.
- **Endpoint discovery** – The CRCON client reads `/api/get_api_documentation`, falls back gracefully when endpoints differ, and can reuse the generic `/api/commands/execute` dispatcher for custom commands.

## Running with Docker

```
docker compose up --build
```

Ensure the `.env` file is available to the container (see `docker-compose.yml` for volume configuration).

## Development Tips

- `src/services/crcon_client.py` centralises HTTP calls (discovery, map changing, command execution). Extend here if your CRCON exposes additional helper endpoints.
- `src/data/available_maps.json` provides metadata (game type, pretty name, variant, map ID). The bot filters this catalogue against CRCON’s `AddMapToRotation` response so only valid options appear in Discord.
- `src/handlers/control_panel.py` contains the Discord UI flows. Add new buttons or modify the wizards here (e.g., add a rotation viewer or map cooldown).
