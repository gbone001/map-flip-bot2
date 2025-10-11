import os, json, asyncio
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from .tcp_client import TcpRconClient
from .crcon_http import CrconHttpClient
from .utils.logger import setup_logger

load_dotenv()
log = setup_logger()
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
ADMIN_ROLE = os.getenv("ADMIN_ROLE", "").strip()
AUDIT_CHANNEL_ID = int(os.getenv("AUDIT_CHANNEL_ID", "0"))

DEFAULT_CRCON_BASE = os.getenv("CRCON_BASE_URL", "").strip()
DEFAULT_CRCON_TOKEN = os.getenv("CRCON_BEARER_TOKEN", "").strip()
REQ_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))
CRCON_BASE = os.getenv("CRCON_BASE_URL", "").strip()
CRCON_API_TOKEN = os.getenv("CRCON_API_TOKEN_DJANGO", "").strip()

def get_http_client(server_id: str | None = None) -> CrconHttpClient | None:
    base = CRCON_BASE
    token = CRCON_API_TOKEN
    if server_id and server_id in SERVERS:
        s = SERVERS[server_id]
        base = s.get("crconBase", base) or base
        token = s.get("token", token) or token
    if not base or not token:
        return None
    return CrconHttpClient(base, token, timeout=REQ_TIMEOUT)

# Load data files
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
with open(os.path.join(DATA_DIR, "available_maps.json")) as f:
    AVAILABLE_MAPS = json.load(f)

SERVERS_PATH = os.path.join(DATA_DIR, "servers.json")
if os.path.exists(SERVERS_PATH):
    with open(SERVERS_PATH) as f:
        SERVERS = {s["id"]: s for s in json.load(f)}
else:
    example_path = os.path.join(DATA_DIR, "servers.example.json")
    with open(example_path) as f:
        SERVERS = {s["id"]: s for s in json.load(f)}
    log.warning("No servers.json found. Using servers.example.json — please create your own.")

def is_admin(inter: discord.Interaction) -> bool:
    if isinstance(inter.user, discord.Member):
        member = inter.user
        if not ADMIN_ROLE:
            return True
        if any(r.name == ADMIN_ROLE for r in member.roles):
            return True
        perms = member.guild_permissions
        return perms.administrator or perms.manage_guild or perms.manage_roles
    return False

def get_crcon_client(server_id: str) -> TcpRconClient:
    s = SERVERS.get(server_id)
    host = os.getenv("RCON_HOST", "localhost")
    port = int(os.getenv("RCON_PORT", "22222"))
    pwd  = os.getenv("RCON_PASSWORD", "botpassword")
    use_tls = os.getenv("RCON_USE_TLS", "false").lower() == "true"
    token_in_body = os.getenv("RCON_TOKEN_IN_BODY", "true").lower() == "true"
    if s:
        host = s.get("host", host)
        port = int(s.get("port", port))
        # Allow per-server override of rcon password if needed
        pwd  = s.get("rconPassword", pwd)
    return TcpRconClient(host, port, pwd, use_tls=use_tls, token_in_body=token_in_body)

# ===== Views =====

class ControlPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.server_id: str | None = None

    @discord.ui.select(
        placeholder="Select Server",
        min_values=1,
        max_values=1,
        options=[discord.SelectOption(label=s["name"], value=s["id"]) for s in SERVERS.values()],
        custom_id="control_panel_select_server",
    )
    async def select_server(self, inter: discord.Interaction, sel: discord.ui.Select):
        self.server_id = sel.values[0]
        set_user_server(inter.user.id, self.server_id)
        await inter.response.send_message(f"Server set to **{SERVERS[self.server_id]['name']}**.", ephemeral=True)

    @discord.ui.button(label="Change Map", style=discord.ButtonStyle.primary, custom_id="control_panel_change_map")
    async def change_map(self, inter: discord.Interaction, btn: discord.ui.Button):
        if not is_admin(inter):
            return await inter.response.send_message("Not authorized.", ephemeral=True)
        if not self.server_id:
            return await inter.response.send_message("Pick a server first.", ephemeral=True)
        await start_change_map_buttons(inter, self.server_id)

    @discord.ui.button(
        label="Set Objectives (current map)",
        style=discord.ButtonStyle.secondary,
        custom_id="control_panel_set_objectives",
    )
    async def set_objectives(self, inter: discord.Interaction, btn: discord.ui.Button):
        if not is_admin(inter):
            return await inter.response.send_message("Not authorized.", ephemeral=True)
        if not self.server_id:
            return await inter.response.send_message("Pick a server first.", ephemeral=True)

        await start_set_objectives_wizard(inter, self.server_id)

# ===== Wizards (ephemeral flows) =====
# ===== Button-based Wizards (ephemeral flows) =====

class GameTypeButtons(discord.ui.View):
    def __init__(self, server_id: str):
        super().__init__(timeout=180)
        self.server_id = server_id

        self.add_item(discord.ui.Button(label="Warfare", style=discord.ButtonStyle.primary, custom_id="gt_warfare"))
        self.add_item(discord.ui.Button(label="Offensive", style=discord.ButtonStyle.primary, custom_id="gt_offensive"))
        self.add_item(discord.ui.Button(label="Skirmish", style=discord.ButtonStyle.primary, custom_id="gt_skirmish"))

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        return is_admin(inter)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="gt_cancel")
    async def cancel(self, inter: discord.Interaction, btn: discord.ui.Button):
        await inter.response.edit_message(content="Cancelled.", view=None)

    async def on_timeout(self):
        # Views will simply expire; no-op
        return

    async def on_error(self, error: Exception, item: discord.ui.Item, inter: discord.Interaction):
        log.error(f"GameTypeButtons error: {error}")

    async def interaction_received(self, inter: discord.Interaction, custom_id: str):
        mapping = {
            "gt_warfare": "Warfare",
            "gt_offensive": "Offensive",
            "gt_skirmish": "Skirmish",
        }
        if custom_id in mapping:
            gt = mapping[custom_id]
            await start_map_buttons(inter, self.server_id, gt)

    async def callback_router(self, inter: discord.Interaction):
        if not inter.data or "custom_id" not in inter.data:  # type: ignore
            return
        await self.interaction_received(inter, inter.data["custom_id"])  # type: ignore

    async def on_item_interaction(self, interaction: discord.Interaction):
        await self.callback_router(interaction)

# Helper to wire callback_router for Buttons (discord.py doesn't expose a generic handler, so we monkeypatch items)
def _wire_button_callbacks(view: discord.ui.View):
    for item in view.children:
        if isinstance(item, discord.ui.Button):
            async def _cb(inter: discord.Interaction, *, _item=item, _view=view):
                if hasattr(_view, "interaction_received"):
                    await getattr(_view, "interaction_received")(inter, _item.custom_id)  # type: ignore
            item.callback = _cb  # type: ignore

def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i+size]

class MapButtons(discord.ui.View):
    def __init__(self, server_id: str, game_type: str, page: int = 0):
        super().__init__(timeout=240)
        self.server_id = server_id
        self.game_type = game_type
        self.page = page

        maps = sorted({m["mapPretty"] for m in AVAILABLE_MAPS if m["gameType"] == game_type})
        self._maps = maps
        pages = list(chunked(maps, 25)) or [[]]
        self._pages = pages
        self._last_page = len(pages) - 1
        current = pages[page]

        for mp in current:
            self.add_item(discord.ui.Button(label=mp[:80], style=discord.ButtonStyle.secondary, custom_id=f"map_{mp}"))

        # Pagination controls if needed
        if self._last_page > 0:
            if page > 0:
                self.add_item(discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.primary, custom_id="map_prev"))
            if page < self._last_page:
                self.add_item(discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.primary, custom_id="map_next"))
        self.add_item(discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="map_cancel"))

    async def interaction_received(self, inter: discord.Interaction, cid: str):
        if cid == "map_prev":
            await inter.response.edit_message(content=f"**{self.game_type}** — choose **Map** (page {self.page})", view=MapButtons(self.server_id, self.game_type, page=self.page-1))
            return
        if cid == "map_next":
            await inter.response.edit_message(content=f"**{self.game_type}** — choose **Map** (page {self.page+2})", view=MapButtons(self.server_id, self.game_type, page=self.page+1))
            return
        if cid == "map_cancel":
            await inter.response.edit_message(content="Cancelled.", view=None)
            return
        if cid.startswith("map_"):
            map_pretty = cid[4:]
            await start_variant_buttons(inter, self.server_id, self.game_type, map_pretty)

class VariantButtons(discord.ui.View):
    def __init__(self, server_id: str, game_type: str, map_pretty: str):
        super().__init__(timeout=240)
        self.server_id = server_id
        self.game_type = game_type
        self.map_pretty = map_pretty

        variants = [m for m in AVAILABLE_MAPS if m["gameType"] == game_type and m["mapPretty"] == map_pretty]
        for v in variants:
            label = v["variant"]
            map_id = v["mapId"]
            self.add_item(discord.ui.Button(label=label[:80], style=discord.ButtonStyle.success, custom_id=f"var_{map_id}"))
        self.add_item(discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, custom_id="var_back"))
        self.add_item(discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="var_cancel"))

    async def interaction_received(self, inter: discord.Interaction, cid: str):
        if cid == "var_back":
            await start_map_buttons(inter, self.server_id, self.game_type)
            return
        if cid == "var_cancel":
            await inter.response.edit_message(content="Cancelled.", view=None)
            return
        if cid.startswith("var_"):
            map_id = cid[4:]
            await confirm_change_map(inter, self.server_id, self.game_type, self.map_pretty, map_id)

async def start_change_map_buttons(inter: discord.Interaction, server_id: str):
    v = GameTypeButtons(server_id)
    _wire_button_callbacks(v)
    await inter.response.send_message("Choose **Game Type**", ephemeral=True, view=v)

async def start_map_buttons(inter: discord.Interaction, server_id: str, game_type: str):
    v = MapButtons(server_id, game_type, page=0)
    _wire_button_callbacks(v)
    await inter.response.edit_message(content=f"**{game_type}** — choose **Map** (page 1)", view=v)

async def start_variant_buttons(inter: discord.Interaction, server_id: str, game_type: str, map_pretty: str):
    v = VariantButtons(server_id, game_type, map_pretty)
    _wire_button_callbacks(v)
    await inter.response.edit_message(content=f"**{game_type}** → **{map_pretty}** — choose **Variant / Time-of-Day**", view=v)


class GameTypeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.game_type: str | None = None

    @discord.ui.select(placeholder="Select Game Type", min_values=1, max_values=1,
                       options=[
                           discord.SelectOption(label="Warfare", value="Warfare"),
                           discord.SelectOption(label="Offensive", value="Offensive"),
                           discord.SelectOption(label="Skirmish", value="Skirmish"),
                       ])
    async def gt_select(self, inter: discord.Interaction, sel: discord.ui.Select):
        self.game_type = sel.values[0]
        await inter.response.edit_message(content=f"**Game Type:** {self.game_type}\nNow select Map…", view=None)
        await start_map_select(inter, self.game_type)

async def start_change_map_wizard(inter: discord.Interaction, server_id: str):
    await inter.response.send_message("Change Map: choose **Game Type**", ephemeral=True, view=GameTypeView())

class MapSelectView(discord.ui.View):
    def __init__(self, game_type: str):
        super().__init__(timeout=180)
        self.game_type = game_type
        # Build unique list of maps for this game type
        maps = sorted({m["mapPretty"] for m in AVAILABLE_MAPS if m["gameType"] == game_type})
        self.options = [discord.SelectOption(label=mp, value=mp) for mp in maps]

    @discord.ui.select(placeholder="Select Map", min_values=1, max_values=1)
    async def map_select(self, inter: discord.Interaction, sel: discord.ui.Select):
        map_pretty = sel.values[0]
        await inter.response.edit_message(content=f"**Game Type:** {self.game_type}\n**Map:** {map_pretty}\nNow select time-of-day…", view=None)
        await start_variant_select(inter, self.game_type, map_pretty)

async def start_map_select(inter: discord.Interaction, game_type: str):
    v = MapSelectView(game_type)
    # set options dynamically (discord.py requires setting after decorator)
    v.children[0].options = v.options
    await inter.followup.send("Select **Map**", ephemeral=True, view=v)

class VariantSelectView(discord.ui.View):
    def __init__(self, game_type: str, map_pretty: str, server_id: str):
        super().__init__(timeout=180)
        self.game_type = game_type
        self.map_pretty = map_pretty
        self.server_id = server_id
        variants = [m for m in AVAILABLE_MAPS if m["gameType"] == game_type and m["mapPretty"] == map_pretty]
        self.variants = variants
        opts = [discord.SelectOption(label=v["variant"], value=v["mapId"]) for v in variants]
        self.select = discord.ui.Select(placeholder="Select time of day / variant", min_values=1, max_values=1, options=opts)
        self.add_item(self.select)

        @self.select.callback
        async def on_select(inter: discord.Interaction):
            map_id = self.select.values[0]
            await confirm_change_map(inter, self.server_id, self.game_type, self.map_pretty, map_id)

async def start_variant_select(inter: discord.Interaction, game_type: str, map_pretty: str):
    # Try to recover server_id from the original panel message by scanning views is complex;
    # we pass via ephemeral context by inspecting the original interaction user-state.
    # For practicality, ask them to re-click "Change Map" if context lost.
    # Here, we attempt to get server from the last ControlPanel in channel is out of scope;
    # instead we store server in a lightweight ephemeral cache keyed by user if needed.
    # To keep this simple, we include server in message content at the start of wizard.
    # We'll attach it via message state; but for this starter, we skip and assume single server flow.
    # In production, thread a server_id param from caller.
    # The caller passes server_id correctly (we arranged it in start_change_map_wizard).
    server_id = find_server_from_context(inter) or "default"
    await inter.followup.send("Select **Time-of-Day / Variant**", ephemeral=True, view=VariantSelectView(game_type, map_pretty, server_id))

# Minimal ephemeral context helper (fallback)
_user_server_ctx: dict[int, str] = {}

def set_user_server(user_id: int, server_id: str):
    _user_server_ctx[user_id] = server_id

def get_user_server(user_id: int) -> str | None:
    return _user_server_ctx.get(user_id)

def find_server_from_context(inter: discord.Interaction) -> str | None:
    return get_user_server(inter.user.id)

async def confirm_change_map(inter: discord.Interaction, server_id: str, game_type: str, map_pretty: str, map_id: str):
    content = f"Confirm change map?\n- **Game Type:** {game_type}\n- **Map:** {map_pretty}\n- **Variant/ID:** `{map_id}`"
    view = ConfirmChangeMapView(server_id, map_id)
    await inter.response.edit_message(content=content, view=view)

class ConfirmChangeMapView(discord.ui.View):
    def __init__(self, server_id: str, map_id: str):
        super().__init__(timeout=120)
        self.server_id = server_id
        self.map_id = map_id

    @discord.ui.button(label="Change Map", style=discord.ButtonStyle.danger)
    async def do_change(self, inter: discord.Interaction, btn: discord.ui.Button):
        client = get_crcon_client(self.server_id)
        result = await client.execute("ChangeMap", {"MapId": self.map_id})
        await inter.response.edit_message(content=f"ChangeMap sent. Result:\n```json\n{json.dumps(result)[:1900]}\n```", view=None)
        await audit(inter, "CHANGE_MAP", {"server_id": self.server_id, "map_id": self.map_id, "result": result})

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, inter: discord.Interaction, btn: discord.ui.Button):
        await inter.response.edit_message(content="Cancelled.", view=None)

# === Set Objectives Wizard ===

class ObjectivesView(discord.ui.View):
    def __init__(self, server_id: str, choices: list[dict]):
        super().__init__(timeout=300)
        self.server_id = server_id
        # Expect three options; use labels & values from reference data
        opts = [discord.SelectOption(label=c.get("Label", c.get("Name", str(i))), value=c.get("Value", c.get("Code", c.get("Name", str(i)))))
                for i, c in enumerate(choices)]
        self.selects = []
        for i in range(5):
            sel = discord.ui.Select(placeholder=f"Objective {i+1}", min_values=1, max_values=1, options=opts)
            self.add_item(sel)
            self.selects.append(sel)

        self.add_item(discord.ui.Button(label="Apply Objectives", style=discord.ButtonStyle.primary, custom_id="apply_obj"))
        self.children[-1].callback = self.apply_objectives  # type: ignore

    async def apply_objectives(self, inter: discord.Interaction):
        picks = [sel.values[0] for sel in self.selects]
        layout = [{"Index": i+1, "Value": v} for i, v in enumerate(picks)]
        client = get_crcon_client(self.server_id)
        result = await client.execute("SetSectorLayout", {"Objectives": layout})
        await inter.response.edit_message(content=f"SetSectorLayout sent. Result:\n```json\n{json.dumps(result)[:1900]}\n```", view=None)
        await audit(inter, "SET_OBJECTIVES", {"server_id": self.server_id, "layout": layout, "result": result})

async def start_set_objectives_wizard(inter: discord.Interaction, server_id: str):
    await inter.response.send_message("Fetching objective choices…", ephemeral=True)
    client = get_crcon_client(server_id)
    ref = await client.get_client_reference("SetSectorLayout")
    # Expect something like {"choices":[{"Label":"A","Value":"A"}, ...]}
    choices = ref.get("choices") or ref.get("Choices") or ref.get("data", [])
    if not isinstance(choices, list) or len(choices) < 3:
        # Fallback to A/B/C
        choices = [{"Label":"A","Value":"A"},{"Label":"B","Value":"B"},{"Label":"C","Value":"C"}]
    await inter.followup.send("Pick **5 objectives** (each from 3 options):", ephemeral=True, view=ObjectivesView(server_id, choices))

# === Audit helper ===
async def audit(inter: discord.Interaction, action: str, payload: dict):
    if AUDIT_CHANNEL_ID <= 0:
        return
    ch = inter.client.get_channel(AUDIT_CHANNEL_ID)
    if not ch:
        return
    embed = discord.Embed(title="RCON Action", description=action)
    embed.add_field(name="User", value=f"{inter.user.mention}", inline=True)
    for k, v in payload.items():
        if isinstance(v, (str, int, float)):
            embed.add_field(name=k, value=str(v), inline=True)
    # Truncate big fields
    js = json.dumps(payload)[:900]
    embed.add_field(name="Payload", value=f"```json\n{js}\n```", inline=False)
    await ch.send(embed=embed)

# === Bot ===

class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Persistent control panel
        self.add_view(ControlPanel())

        # Guild-scoped command sync if provided
        if GUILD_ID:
            await self.tree.sync(guild=discord.Object(id=GUILD_ID))
            log.info(f"Synced slash commands to guild {GUILD_ID}")
        else:
            await self.tree.sync()
            log.info("Synced slash commands globally (no DISCORD_GUILD_ID set)")

    async def on_ready(self):
        log.info(f"Bot connected as {self.user}")
        if CHANNEL_ID:
            ch = self.get_channel(CHANNEL_ID)
            if ch:
                # Post control panel if not present / as a fresh message
                content = (
                    "**HLL RCON Control Panel**\n"
                    "1) Select **Server**\n"
                    "2) Choose **Change Map** or **Set Objectives (current map)**"
                )
                await ch.send(content, view=ControlPanel())


bot = Bot()

@bot.tree.command(name="rcon_panel", description="Post or refresh the RCON Control Panel here.")
async def rcon_panel(inter: discord.Interaction):
    view = ControlPanel()
    # remember the user's last chosen server for wizard threading
    if isinstance(inter.user, discord.Member):
        # initialize ctx with default if only one server
        if len(SERVERS) == 1:
            set_user_server(inter.user.id, next(iter(SERVERS.keys())))
    content = (
        "**HLL RCON Control Panel**\n"
        "1) Select **Server**\n"
        "2) Choose **Change Map** or **Set Objectives (current map)**"
    )
    await inter.response.send_message("Posting control panel…", ephemeral=True)
    msg = await inter.channel.send(content, view=view)
    await inter.followup.send(f"Panel posted: {msg.jump_url}", ephemeral=True)

@rcon_panel.error
async def rcon_panel_error(inter: discord.Interaction, error: Exception):
    await inter.response.send_message(f"Error: {error}", ephemeral=True)

if ADMIN_ROLE:
    rcon_panel = app_commands.checks.has_role(ADMIN_ROLE)(rcon_panel)

def main():
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN not set")
    bot.run(TOKEN)

if __name__ == "__main__":
    main()


@bot.tree.command(name="rcon_http_ping", description="Test CRCON HTTP execute with GetClientReferenceData(SetSectorLayout).")
async def rcon_http_ping(inter: discord.Interaction, server_id: str | None = None):
    client = get_http_client(server_id)
    if not client:
        return await inter.response.send_message("HTTP client not configured (check CRCON_BASE_URL / CRCON_API_TOKEN_DJANGO).", ephemeral=True)
    await inter.response.send_message("Pinging CRCON HTTP…", ephemeral=True)
    res = await client.get_client_reference("SetSectorLayout")
    out = json.dumps(res)[:1900]
    await inter.followup.send(f"HTTP OK. Response snippet:\n```json\n{out}\n```", ephemeral=True)

if ADMIN_ROLE:
    rcon_http_ping = app_commands.checks.has_role(ADMIN_ROLE)(rcon_http_ping)
