from __future__ import annotations

import asyncio
from typing import Dict, Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv

from src.config import ServerConfig, Settings, load_settings
from src.handlers.control_panel import ControlPanel, setup as setup_control_panel
from src.services.crcon_client import CrconClient


load_dotenv()
settings = load_settings()


def _prepare_servers(config: Settings) -> Dict[str, ServerConfig]:
    servers = dict(config.servers)
    if servers:
        return servers

    if config.crcon_base and config.crcon_token:
        fallback = ServerConfig(
            id="default",
            name="Default Server",
            crcon_base=config.crcon_base,
            token=config.crcon_token,
            host=config.rcon_host,
            port=config.rcon_port,
            rcon_password=config.rcon_password,
        )
        servers[fallback.id] = fallback
    return servers


servers = _prepare_servers(settings)
settings.servers = servers

intents = discord.Intents.none()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

panel_cog: Optional[ControlPanel] = None
clients: Dict[str, CrconClient] = {}

for server_id, server in servers.items():
    if server.crcon_base and server.token:
        clients[server_id] = CrconClient(server.crcon_base, server.token)


async def _fetch_channel() -> Optional[discord.abc.Messageable]:
    channel = bot.get_channel(settings.channel_id)
    if channel:
        return channel  # type: ignore[return-value]
    try:
        fetched = await bot.fetch_channel(settings.channel_id)
        if isinstance(fetched, discord.abc.Messageable):
            return fetched
    except Exception as exc:
        print(f"Unable to fetch channel {settings.channel_id}: {exc}")
    return None


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} (guild={settings.guild_id})")
    if panel_cog is None:
        return
    channel = await _fetch_channel()
    if not channel:
        print("Control panel channel unavailable; check permissions and ID.")
        return
    await panel_cog.ensure_panel_message(channel)


async def main() -> None:
    global panel_cog
    if not clients:
        print("Warning: no CRCON clients configured; interactions will be limited.")
    try:
        panel_cog = await setup_control_panel(bot, settings, clients)
        await bot.start(settings.token)
    finally:
        await asyncio.gather(*(client.aclose() for client in clients.values()), return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
