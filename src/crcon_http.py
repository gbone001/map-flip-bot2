import aiohttp, json
from typing import Any, Dict, Optional

class CrconHttpClient:
    """
    Minimal HTTP adapter for CRCON's current 'execute' endpoint.
    Use for read-only/status-style UI while keeping TCP RCONv2 for authoritative writes.
    """
    def __init__(self, base_url: str, token: str, timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    async def execute(self, command: str, body: Optional[Dict[str, Any]] = None, version: int = 2) -> Dict[str, Any]:
        url = f"{self.base_url}/api/commands/execute"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        payload = {"command": command, "version": version, "body": (body or {})}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as s:
            async with s.post(url, headers=headers, json=payload) as r:
                text = await r.text()
                try:
                    return json.loads(text)
                except Exception:
                    return {"status": r.status, "text": text}

    # Convenience wrappers (adjust command names to your CRCON build if needed)
    async def get_client_reference(self, name: str) -> Dict[str, Any]:
        return await self.execute("GetClientReferenceData", {"Name": name})

    async def get_server_info(self) -> Dict[str, Any]:
        # Common pattern; rename if your build differs
        return await self.execute("GetServerInfo", {})

    async def get_map_rotation(self) -> Dict[str, Any]:
        # Example; adjust command name if necessary
        return await self.execute("GetMapRotation", {})
