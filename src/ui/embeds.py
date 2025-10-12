from __future__ import annotations

from typing import Any, Dict, Optional

import discord


def _format_time_remaining(value: Any) -> Optional[str]:
    if isinstance(value, (int, float)):
        mins = int(value // 60)
        secs = int(value % 60)
        return f"{mins:02d}:{secs:02d}"
    return None


def map_status_embed(public_info: Dict[str, Any]) -> discord.Embed:
    current = public_info.get("current_map") or {}
    upcoming = public_info.get("next_map") or {}

    current_name = current.get("map") or "Unknown"
    next_name = upcoming.get("map") or "Unknown"
    embed = discord.Embed(
        title="HLL Map Switcher",
        description="Current / Next map",
        color=0x2B2D31,
    )
    embed.add_field(name="Current", value=f"**{current_name}**", inline=True)
    embed.add_field(name="Next", value=f"**{next_name}**", inline=True)

    time_remaining = _format_time_remaining(public_info.get("time_remaining"))
    if time_remaining:
        embed.add_field(name="Time Remaining", value=time_remaining, inline=True)

    return embed
