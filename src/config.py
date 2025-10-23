from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Dict, List


@dataclass
class Settings:
    token: str
    guild_id: int
    channel_id: int
    allowed_roles: List[int]
    crcon_base: str
    crcon_token: str
    rcon_host: str | None
    rcon_port: int | None
    rcon_password: str | None
    servers: Dict[str, "ServerConfig"]


@dataclass
class ServerConfig:
    id: str
    name: str
    crcon_base: str
    token: str
    host: str | None = None
    port: int | None = None
    rcon_password: str | None = None


def _load_servers(data_dir: Path) -> Dict[str, ServerConfig]:
    primary = data_dir / "servers.json"
    fallback = data_dir / "servers.example.json"

    if primary.exists():
        payload_path = primary
    elif fallback.exists():
        payload_path = fallback
    else:
        return {}

    with payload_path.open("r", encoding="utf-8") as handle:
        raw_servers = json.load(handle)

    servers: Dict[str, ServerConfig] = {}
    for entry in raw_servers:
        server_id = entry.get("id")
        name = entry.get("name")
        base = entry.get("crconBase")
        token = entry.get("token")
        if not (server_id and name and base and token):
            continue
        servers[server_id] = ServerConfig(
            id=server_id,
            name=name,
            crcon_base=base.rstrip("/"),
            token=token,
            host=entry.get("host"),
            port=int(entry["port"]) if str(entry.get("port", "")).isdigit() else None,
            rcon_password=entry.get("rconPassword"),
        )
    return servers


def load_settings() -> Settings:
    roles_raw = os.getenv("DISCORD_ALLOWED_ROLE_IDS", "").strip()
    allowed_roles = [int(part) for part in roles_raw.split(",") if part.strip().isdigit()]

    data_dir = Path(__file__).resolve().parent / "data"
    servers = _load_servers(data_dir)

    return Settings(
        token=os.environ["DISCORD_BOT_TOKEN"],
        guild_id=int(os.environ["DISCORD_GUILD_ID"]),
        channel_id=int(os.environ["DISCORD_CHANNEL_ID"]),
        allowed_roles=allowed_roles,
        crcon_base=os.environ.get("CRCON_BASE_URL", "").rstrip("/"),
        crcon_token=os.environ.get("CRCON_API_TOKEN_DJANGO", ""),
        rcon_host=os.getenv("RCON_HOST"),
        rcon_port=int(os.getenv("RCON_PORT")) if os.getenv("RCON_PORT") else None,
        rcon_password=os.getenv("RCON_PASSWORD"),
        servers=servers,
    )
