from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional

import discord
from discord.ext import commands

from src.config import ServerConfig, Settings
from src.data.maps import MapEntry, available_game_types, maps_for_game_type, variants_for_map
from src.services.crcon_client import CrconClient


@dataclass
class PanelState:
    active_server_id: str
    message_id: Optional[int] = None


class ControlPanel(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        settings: Settings,
        clients: Dict[str, CrconClient],
    ) -> None:
        self.bot = bot
        self.settings = settings
        self.clients = clients
        self.panel_state = PanelState(active_server_id=self._default_server_id())
        self.server_preferences: Dict[int, str] = {}
        self._map_cache: Dict[str, List[str]] = {}
        self._map_cache_lock = asyncio.Lock()

        # Register persistent view so interactions survive restarts.
        if self.panel_state.active_server_id:
            bot.add_view(ControlPanelView(self, self.panel_state.active_server_id))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _default_server_id(self) -> str:
        if self.settings.servers:
            return next(iter(self.settings.servers.keys()))
        return "default"

    def server_config(self, server_id: str) -> Optional[ServerConfig]:
        return self.settings.servers.get(server_id)

    def get_client(self, server_id: str) -> Optional[CrconClient]:
        return self.clients.get(server_id)

    async def remember_selection(self, user_id: int, server_id: str) -> None:
        self.server_preferences[user_id] = server_id

    def user_selection(self, user_id: int) -> Optional[str]:
        return self.server_preferences.get(user_id)

    # ------------------------------------------------------------------
    # Panel message management
    # ------------------------------------------------------------------
    async def ensure_panel_message(self, channel: discord.abc.Messageable) -> discord.Message:
        message = None
        if self.panel_state.message_id:
            try:
                message = await channel.fetch_message(self.panel_state.message_id)  # type: ignore[attr-defined]
            except Exception:
                message = None

        if message is None:
            embed = await self.build_panel_embed(self.panel_state.active_server_id)
            view = ControlPanelView(self, self.panel_state.active_server_id)
            message = await channel.send(embed=embed, view=view)
            self.panel_state.message_id = message.id
        else:
            await self.refresh_panel_message(channel, self.panel_state.active_server_id)
        return message

    async def refresh_panel_message(
        self,
        channel: discord.abc.Messageable,
        server_id: Optional[str] = None,
    ) -> None:
        if server_id:
            self.panel_state.active_server_id = server_id
        message_id = self.panel_state.message_id
        if not message_id:
            return
        try:
            message = await channel.fetch_message(message_id)  # type: ignore[attr-defined]
        except Exception:
            return

        server_to_use = server_id or self.panel_state.active_server_id
        embed = await self.build_panel_embed(server_to_use)
        view = ControlPanelView(self, server_to_use)
        try:
            await message.edit(embed=embed, view=view)
        except Exception:
            pass

    async def build_panel_embed(self, server_id: str) -> discord.Embed:
        server_cfg = self.server_config(server_id)
        display_name = server_cfg.name if server_cfg else server_id
        client = self.get_client(server_id)
        embed = discord.Embed(title=f"HLL Control Panel — {display_name}", color=0x2B2D31)

        if not client:
            embed.description = "CRCON client not configured for this server."
            return embed

        ok, info, _ = await client.get_public_info()
        if ok and info:
            current = info.get("current_map") or {}
            next_map = info.get("next_map") or {}

            def fmt(entry: dict) -> str:
                if not isinstance(entry, dict):
                    return "Unknown"
                map_id = entry.get("id") or entry.get("map_id") or entry.get("mapId") or "Unknown"
                mode = entry.get("game_mode") or entry.get("gameMode")
                env = entry.get("environment") or entry.get("Environment")
                parts = [str(map_id)]
                if mode:
                    parts.append(str(mode))
                if env:
                    parts.append(str(env))
                return " | ".join(parts)

            embed.add_field(name="Current Map", value=fmt(current), inline=False)
            embed.add_field(name="Next Map", value=fmt(next_map), inline=False)

            time_remaining = info.get("time_remaining")
            if isinstance(time_remaining, (int, float)):
                mins = int(time_remaining // 60)
                secs = int(time_remaining % 60)
                embed.add_field(name="Time Remaining", value=f"{mins:02d}:{secs:02d}", inline=False)
        else:
            embed.add_field(name="Current Map", value="Unavailable", inline=False)

        layout = await client.get_sector_layout()
        if layout:
            formatted = []
            for item in layout:
                index = item.get("Index") or item.get("index") or len(formatted) + 1
                value = item.get("Value") or item.get("value") or "?"
                formatted.append(f"{index}. {value}")
            embed.add_field(name="Objectives", value="\n".join(formatted), inline=False)
        else:
            embed.add_field(name="Objectives", value="Unavailable", inline=False)

        embed.set_footer(text="Select a server to refresh status; buttons open interactive flows.")
        return embed

    # ------------------------------------------------------------------
    # Map availability helpers
    # ------------------------------------------------------------------
    async def map_ids_for_server(self, server_id: str) -> List[str]:
        async with self._map_cache_lock:
            if server_id in self._map_cache:
                return self._map_cache[server_id]
            client = self.get_client(server_id)
            if not client:
                self._map_cache[server_id] = []
                return []
            try:
                ids = await client.get_available_map_ids()
            except Exception:
                ids = []
            self._map_cache[server_id] = ids
            return ids

    def invalidate_map_cache(self, server_id: str) -> None:
        self._map_cache.pop(server_id, None)

    # ------------------------------------------------------------------
    # Interaction entry points
    # ------------------------------------------------------------------
    async def handle_server_selected(self, interaction: discord.Interaction, server_id: str) -> None:
        await self.remember_selection(interaction.user.id, server_id)  # type: ignore[arg-type]
        channel = interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message("Unable to identify channel.", ephemeral=True)
            return
        embed = await self.build_panel_embed(server_id)
        view = ControlPanelView(self, server_id)
        self.panel_state.active_server_id = server_id
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

    async def handle_change_map(self, interaction: discord.Interaction, server_id: str) -> None:
        client = self.get_client(server_id)
        if not client:
            await interaction.response.send_message("CRCON not configured for this server.", ephemeral=True)
            return

        map_ids = await self.map_ids_for_server(server_id)
        game_types = available_game_types(map_ids)
        if not game_types:
            await interaction.response.send_message("No maps available from CRCON.", ephemeral=True)
            return

        view = ChangeMapGameTypeView(self, server_id, map_ids, game_types)
        await interaction.response.send_message("Choose a game type", view=view, ephemeral=True)

    async def handle_objectives(self, interaction: discord.Interaction, server_id: str) -> None:
        client = self.get_client(server_id)
        if not client:
            await interaction.response.send_message("CRCON not configured for this server.", ephemeral=True)
            return
        try:
            choices = await client.get_objective_choices()
        except Exception as exc:
            await interaction.response.send_message(f"Failed to fetch objective choices: {exc}", ephemeral=True)
            return

        processed = []
        for item in choices:
            label = item.get("Label") or item.get("label") or item.get("Name")
            value = item.get("Value") or item.get("value") or item.get("Code")
            if label and value:
                processed.append((str(label), str(value)))

        if len(processed) < 3:
            processed = [(letter, letter) for letter in ("A", "B", "C")]

        view = ObjectivesView(self, server_id, processed)
        await interaction.response.send_message(
            "Select five objectives (each dropdown offers the same three options).",
            view=view,
            ephemeral=True,
        )

    async def apply_objectives(self, interaction: discord.Interaction, server_id: str, selections: List[str]) -> None:
        client = self.get_client(server_id)
        if not client:
            await interaction.response.edit_message(content="CRCON not configured for this server.", view=None)
            return

        payload = [{"Index": idx + 1, "Value": value} for idx, value in enumerate(selections)]
        ok, message, _ = await client.set_objectives(payload)
        if ok:
            content = "✅ Objectives applied."
            channel = interaction.channel
            if isinstance(channel, discord.abc.Messageable):
                await self.refresh_panel_message(channel, server_id)
        else:
            content = f"❌ Failed to set objectives: {message}"
        await interaction.response.edit_message(content=content, view=None)

    async def execute_map_change(
        self,
        interaction: discord.Interaction,
        server_id: str,
        variant_entry: MapEntry,
    ) -> None:
        client = self.get_client(server_id)
        if not client:
            await interaction.response.edit_message(content="CRCON not configured for this server.", view=None)
            return

        ok, message, _ = await client.change_map_by_id(variant_entry.map_id)
        if ok:
            content = f"✅ Map change requested: {variant_entry.map_pretty} ({variant_entry.variant})"
            self.invalidate_map_cache(server_id)
            channel = interaction.channel
            if isinstance(channel, discord.abc.Messageable):
                await self.refresh_panel_message(channel, server_id)
        else:
            content = f"❌ Failed: {message}"
        await interaction.response.edit_message(content=content, view=None)


# ----------------------------------------------------------------------
# Persistent Control Panel View
# ----------------------------------------------------------------------


class ControlPanelView(discord.ui.View):
    def __init__(self, controller: ControlPanel, active_server_id: str):
        super().__init__(timeout=None)
        self.controller = controller
        self.active_server_id = active_server_id

        self.add_item(ServerSelect(controller, active_server_id))
        self.add_item(ChangeMapButton(controller, active_server_id))
        self.add_item(SetObjectivesButton(controller, active_server_id))


class ServerSelect(discord.ui.Select):
    def __init__(self, controller: ControlPanel, active_server_id: str):
        options = []
        for sid, server in controller.settings.servers.items():
            options.append(discord.SelectOption(label=server.name, value=sid, default=(sid == active_server_id)))
        if not options:
            options.append(discord.SelectOption(label="Default", value="default", default=True))
        super().__init__(
            placeholder="Select Server",
            min_values=1,
            max_values=1,
            options=options[:25],
            custom_id="cp:server",
        )
        self.controller = controller

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.values[0]
        await self.controller.handle_server_selected(interaction, selected)


class ChangeMapButton(discord.ui.Button):
    def __init__(self, controller: ControlPanel, server_id: str):
        label = "Change Map"
        super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=f"cp:change:{server_id}")
        self.controller = controller
        self.server_id = server_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.controller.handle_change_map(interaction, self.server_id)


class SetObjectivesButton(discord.ui.Button):
    def __init__(self, controller: ControlPanel, server_id: str):
        super().__init__(label="Set Objectives", style=discord.ButtonStyle.secondary, custom_id=f"cp:obj:{server_id}")
        self.controller = controller
        self.server_id = server_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.controller.handle_objectives(interaction, self.server_id)


# ----------------------------------------------------------------------
# Change Map Flow
# ----------------------------------------------------------------------


class ChangeMapGameTypeView(discord.ui.View):
    def __init__(self, controller: ControlPanel, server_id: str, map_ids: List[str], game_types: List[str]):
        super().__init__(timeout=180)
        self.controller = controller
        self.server_id = server_id
        self.map_ids = map_ids
        select = discord.ui.Select(
            placeholder="Select Game Type",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=gt, value=gt) for gt in game_types[:25]],
        )

        async def on_select(interaction: discord.Interaction) -> None:
            game_type = select.values[0]
            maps = maps_for_game_type(game_type, self.map_ids)
            if not maps:
                await interaction.response.edit_message(content="No maps available for that game type.", view=None)
                return
            view = ChangeMapMapView(self.controller, self.server_id, self.map_ids, game_type, maps)
            await interaction.response.edit_message(content=f"{game_type}: select map", view=view)

        select.callback = on_select  # type: ignore[assignment]
        self.add_item(select)


class ChangeMapMapView(discord.ui.View):
    def __init__(
        self,
        controller: ControlPanel,
        server_id: str,
        map_ids: List[str],
        game_type: str,
        maps: List[str],
    ) -> None:
        super().__init__(timeout=180)
        self.controller = controller
        self.server_id = server_id
        self.map_ids = map_ids
        self.game_type = game_type
        select = discord.ui.Select(
            placeholder="Select Map",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=name, value=name) for name in maps[:25]],
        )

        async def on_select(interaction: discord.Interaction) -> None:
            map_name = select.values[0]
            variants = variants_for_map(self.game_type, map_name, self.map_ids)
            if not variants:
                await interaction.response.edit_message(content="No variants available for that map.", view=None)
                return
            view = ChangeMapVariantView(self.controller, self.server_id, variants)
            await interaction.response.edit_message(
                content=f"{self.game_type} → {map_name}: choose variant",
                view=view,
            )

        select.callback = on_select  # type: ignore[assignment]
        self.add_item(select)


class ChangeMapVariantView(discord.ui.View):
    def __init__(self, controller: ControlPanel, server_id: str, variants: List[MapEntry]):
        super().__init__(timeout=180)
        self.controller = controller
        self.server_id = server_id
        options = [
            discord.SelectOption(label=f"{variant.variant}", value=variant.map_id, description=variant.map_pretty)
            for variant in variants[:25]
        ]
        self._variant_lookup = {variant.map_id: variant for variant in variants}

        select = discord.ui.Select(
            placeholder="Select Variant / Time of Day",
            min_values=1,
            max_values=1,
            options=options,
        )

        async def on_select(interaction: discord.Interaction) -> None:
            map_id = select.values[0]
            variant_entry = self._variant_lookup[map_id]
            await self.controller.execute_map_change(interaction, self.server_id, variant_entry)

        select.callback = on_select  # type: ignore[assignment]
        self.add_item(select)


# ----------------------------------------------------------------------
# Objectives Flow
# ----------------------------------------------------------------------


class ObjectivesView(discord.ui.View):
    def __init__(self, controller: ControlPanel, server_id: str, options: List[tuple[str, str]]):
        super().__init__(timeout=300)
        self.controller = controller
        self.server_id = server_id
        self.selects: List[discord.ui.Select] = []

        for idx in range(5):
            select = discord.ui.Select(
                placeholder=f"Objective {idx + 1}",
                min_values=1,
                max_values=1,
                options=[discord.SelectOption(label=label, value=value) for label, value in options],
            )
            self.add_item(select)
            self.selects.append(select)

        submit = discord.ui.Button(label="Apply Objectives", style=discord.ButtonStyle.primary)

        async def on_submit(interaction: discord.Interaction) -> None:
            values = []
            for select in self.selects:
                if not select.values:
                    await interaction.response.send_message("Please select all five objectives before applying.", ephemeral=True)
                    return
                values.append(select.values[0])
            await self.controller.apply_objectives(interaction, self.server_id, values)

        submit.callback = on_submit  # type: ignore[assignment]
        self.add_item(submit)


async def setup(bot: commands.Bot, settings: Settings, clients: Dict[str, CrconClient]) -> ControlPanel:
    cog = ControlPanel(bot, settings, clients)
    await bot.add_cog(cog)
    return cog
