import unittest

from src.services.crcon_client import CrconClient


class ChangeMapTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        if hasattr(self, "_client"):
            await self._client.aclose()

    async def test_direct_map_endpoint(self) -> None:
        client = CrconClient("https://example.com", "token")
        self._client = client
        client._catalog_ready = True  # type: ignore[attr-defined]
        client._endpoints = {"map": True}  # type: ignore[attr-defined]
        client._endpoints_meta = {"map": {"args": ["map_name"]}}  # type: ignore[attr-defined]

        async def fake_post(endpoint: str, payload: dict):
            self.assertEqual(endpoint, "map")
            self.assertEqual(payload, {"map_name": "Foy Warfare"})
            return True, "queued", {}

        client._post = fake_post  # type: ignore[assignment]
        ok, message = await client.change_map("Foy Warfare")

        self.assertTrue(ok)
        self.assertIn("Foy Warfare", message)

    async def test_fallback_to_set_next_map(self) -> None:
        client = CrconClient("https://example.com", "token")
        self._client = client
        client._catalog_ready = True  # type: ignore[attr-defined]
        client._endpoints = {  # type: ignore[attr-defined]
            "map": False,
            "set_next_map": True,
            "end_map": True,
        }
        client._endpoints_meta = {"set_next_map": {"args": ["map"]}}  # type: ignore[attr-defined]

        calls: list[tuple[str, dict]] = []

        async def fake_post(endpoint: str, payload: dict):
            calls.append((endpoint, payload))
            if endpoint == "set_next_map":
                return True, "set", {}
            if endpoint == "end_map":
                return True, "ended", {}
            return False, "unexpected", {}

        client._post = fake_post  # type: ignore[assignment]
        ok, message = await client.change_map("Hill 400 Warfare")

        self.assertTrue(ok)
        self.assertIn("Hill 400 Warfare", message)
        self.assertEqual(
            calls,
            [
                ("set_next_map", {"map": "Hill 400 Warfare"}),
                ("end_map", {}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
