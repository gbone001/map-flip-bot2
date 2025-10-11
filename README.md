# HLL RCONv2 Discord Bot — Map Change & Set Objectives

A Discord bot that posts a persistent **RCON Control Panel** with two actions:

- **Change Map**: Pick Game Type → Map → Time-of-Day variant, then change map via CRCONv2.
- **Set Objectives**: For the **current map only**, fetch valid choices using
  `GetClientReferenceData("SetSectorLayout")` and submit a `SetSectorLayout` command
  with 5 objectives (each from a pool of 3).

> Reference: Executing commands & Available Maps from the HLL_RCONv2 wiki you saved.

## Quick start

1) Copy `.env.example` to `.env` and fill values.
2) Put your servers in `src/data/servers.json` (see `servers.example.json`).
3) (Optional) Extend `src/data/available_maps.json` with more maps/variants.
4) Install deps and run the bot:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.bot
```

Or with Docker:

```bash
docker compose up --build -d
```

## Commands

- `/rcon_panel` — Post or refresh the control panel in the current channel (admin-only).

## Notes

- **Objectives** are pulled live from CRCON (`GetClientReferenceData("SetSectorLayout")`),
  so you always get the server’s current allowed options.
- **Available maps** are curated in a JSON file for convenience; keep them in sync with the wiki.
- Actions are logged to an audit channel if you set `AUDIT_CHANNEL_ID` in `.env`.


---

## 🔌 HLL RCONv2 (TCP) — Protocol & Config

This starter now targets the **TCP-based HLL RCONv2 protocol** with explicit command versioning.

**Envelope (per message):**
```json
{ "command": "CommandName", "version": 2, "body": { "ParamA": "Value" } }
```

**Session Auth:**
1. Establish a TCP connection to the CRCON RCONv2 service.
2. Send `ServerConnect` (if used in your deployment) and `Login`.
3. The server returns an **access token**.
4. Include that token on **every subsequent command within the session** (the client does this for you).

> The exact *fixed protocol header* bytes and where the token is carried (header vs. payload) can vary by build. This repo provides a pluggable header encoder so you can match your server’s framing/fields.

### .env (TCP mode)

```
RCON_HOST=crcon-japan.anzr.org
RCON_PORT=22222
RCON_USERNAME=botuser
RCON_PASSWORD=botpassword

# Optional TLS (if your gateway terminates TLS elsewhere, leave false)
RCON_USE_TLS=false

# If your build expects token in payload instead of header, set this true
RCON_TOKEN_IN_BODY=true
```

### Where to adapt header/framing

See `src/tcp_client.py` → `build_header()` and `read_frame()`.
By default we assume a **4-byte big-endian length prefix** followed by a UTF-8 JSON payload.
If your deployment uses a custom header or includes token as a header field, update those functions accordingly.

---

## 🔐 Credentials & Auth (as per your deployment)

- **CRCON_BASE_URL**: Django web backend base URL (used for optional HTTP features, health, or admin APIs).
- **CRCON_API_TOKEN_DJANGO**: Django API token (Bearer token) for the CRCON web backend.
- **RCON_HOST / RCON_PORT**: TCP endpoint for HLL RCONv2.
- **RCON_PASSWORD**: Password used by the `Login` command over TCP.

> This bot executes `ChangeMap`, `GetClientReferenceData("SetSectorLayout")`, and `SetSectorLayout`
> over the **TCP RCONv2** connection using `RCON_HOST/RCON_PORT/RCON_PASSWORD`.
> The Django token/URL are available if you later add HTTP-based features.

---

## 🟦 Interactive Map Changing (Buttons)

The control panel now uses **button-based navigation** inspired by your `HLL_Map_Switcher` approach:

1. **Select Server** (dropdown in the panel)
2. Click **Change Map**
3. Tap a **Game Type** button (Warfare / Offensive / Skirmish)
4. Tap a **Map** button (paginated if > 25)
5. Tap a **Variant / Time-of-Day** button to confirm and send `ChangeMap`

You can extend `src/data/available_maps.json` and the UI will adapt automatically.

---

## 🌐 Optional HTTP Adapter (read-only)

This project includes a minimal **HTTP adapter** (`src/crcon_http.py`) that calls your CRCON
**execute** endpoint with the standard envelope:
```json
{ "command": "CommandName", "version": 2, "body": { ... } }
```
- Configure `.env`: `CRCON_BASE_URL` and `CRCON_API_TOKEN_DJANGO`
- Use it for **status/rotation/metadata** without touching the TCP path for writes.

A demo slash command `/rcon_http_ping` is provided to verify connectivity by requesting
`GetClientReferenceData("SetSectorLayout")`.
