import unittest

from src.config import ServerConfig, Settings
from src.data.maps import MapEntry
from src.handlers.control_panel import ControlPanel


class FakeClient:
    def __init__(self):
        self.last_map_id = None
        self.objective_payload = None

    async def change_map_by_id(self, map_id: str):
        self.last_map_id = map_id
        return True, "ok", {}

    async def set_objectives(self, selections):
        self.objective_payload = selections
        return True, "ok", {}

    async def get_public_info(self):
        return True, {"current_map": {"map": "Foo"}, "next_map": {"map": "Bar"}, "time_remaining": 120}, None

    async def get_sector_layout(self):
        return [{"Index": 1, "Value": "A"}]


class FakeResponse:
    def __init__(self):
        self.edits = []

    async def edit_message(self, content=None, view=None):
        self.edits.append({"content": content, "view": view})


class FakeInteraction:
    def __init__(self):
        self.user = type("User", (), {"id": 1})()
        self.channel = None
        self.response = FakeResponse()


class ControlPanelFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        server = ServerConfig(
            id="primary",
            name="Primary",
            crcon_base="https://example.com",
            token="token",
        )
        settings = Settings(
            token="x",
            guild_id=1,
            channel_id=123,
            allowed_roles=[],
            crcon_base="",
            crcon_token="",
            rcon_host=None,
            rcon_port=None,
            rcon_password=None,
            servers={"primary": server},
        )
        self.client = FakeClient()

        class DummyBot:
            def __init__(self):
                self.views = []

            def add_view(self, view):
                self.views.append(view)

        self.bot = DummyBot()
        self.panel = ControlPanel(self.bot, settings, {"primary": self.client})

    async def test_execute_map_change_records_map_id(self):
        interaction = FakeInteraction()
        variant = MapEntry(game_type="Warfare", map_pretty="Hill 400", variant="Day", map_id="hill400_day")

        await self.panel.execute_map_change(interaction, "primary", variant)

        self.assertEqual(self.client.last_map_id, "hill400_day")
        self.assertTrue(interaction.response.edits)
        self.assertIn("Hill 400", interaction.response.edits[0]["content"])

    async def test_apply_objectives_sends_payload(self):
        interaction = FakeInteraction()
        selections = ["A", "B", "C", "A", "B"]

        await self.panel.apply_objectives(interaction, "primary", selections)

        self.assertEqual(
            self.client.objective_payload,
            [
                {"Index": 1, "Value": "A"},
                {"Index": 2, "Value": "B"},
                {"Index": 3, "Value": "C"},
                {"Index": 4, "Value": "A"},
                {"Index": 5, "Value": "B"},
            ],
        )
        self.assertTrue(interaction.response.edits)
        self.assertIn("Objectives applied", interaction.response.edits[0]["content"])


if __name__ == "__main__":
    unittest.main()
