import aiohttp, os, json
from typing import Any, Dict, Optional

class CrconHttpClient:
    """HTTP client for CRCONv2 'execute commands' style API.
    Expects a POST endpoint that accepts JSON envelopes: {command, version, body}.
    """
    def __init__(self, base_url: str, token: str, timeout: int = 10):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.timeout = timeout

    async def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        ) as s:
            async with s.post(url, headers=headers, json=payload) as r:
                text = await r.text()
                try:
                    return json.loads(text)
                except Exception:
                    return {"status": r.status, "text": text}

    async def execute(self, command: str, body: Optional[Dict[str, Any]] = None, version: int = 2) -> Dict[str, Any]:
        payload = {"command": command, "version": version, "body": (body or {})}
        # Adjust the path below to match your CRCON tool's "execute" endpoint
        return await self._post("/api/commands/execute", payload)

    async def get_client_reference(self, name: str) -> Dict[str, Any]:
        # Standardized via the same execute endpoint
        return await self.execute("GetClientReferenceData", {"Name": name})
