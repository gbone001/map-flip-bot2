import asyncio, json, os, ssl
from typing import Any, Dict, Optional

class TcpRconClient:
    """
    TCP client for HLL RCONv2 with session login + per-command token injection.
    This implementation is intentionally adaptable:
      - Framing: default is 4-byte big-endian length prefix + UTF-8 JSON payload
      - Token placement: header or body (controlled by env RCON_TOKEN_IN_BODY)
    """
    def __init__(self, host: str, port: int, password: str, use_tls: bool=False, token_in_body: bool=True):
        self.host = host
        self.port = port
        self.password = password
        self.use_tls = use_tls
        self.token_in_body = token_in_body

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._token: str | None = None
        self._lock = asyncio.Lock()

    async def connect(self):
        if self._writer is not None and not self._writer.is_closing():
            return
        ssl_ctx = None
        if self.use_tls:
            ssl_ctx = ssl.create_default_context()
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port, ssl=ssl_ctx)

    async def close(self):
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None

    # --- Framing ---
    def build_header(self, payload_bytes: bytes) -> bytes:
        """
        Default framing: 4-byte big-endian length of payload.
        If your server uses a custom fixed header (magic bytes, version, flags, etc.),
        modify this function accordingly.
        """
        length = len(payload_bytes)
        return length.to_bytes(4, byteorder="big")

    async def read_frame(self) -> bytes:
        """
        Default framing: read 4-byte big-endian length then that many bytes.
        Adjust as needed to your deployment.
        """
        assert self._reader is not None
        header = await self._reader.readexactly(4)
        n = int.from_bytes(header, "big")
        if n <= 0 or n > 32_000_000:
            raise ValueError(f"Invalid frame length: {n}")
        return await self._reader.readexactly(n)

    async def send_envelope(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        # Serialize
        data = json.dumps(envelope).encode("utf-8")
        header = self.build_header(data)
        assert self._writer is not None
        self._writer.write(header + data)
        await self._writer.drain()
        # Read response
        raw = await self.read_frame()
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {"ok": False, "raw": raw.decode("utf-8", errors="replace")}

    # --- Protocol ops ---
    async def login(self):
        # Some deployments use ServerConnect first; include if needed:
        # await self.execute("ServerConnect", {"Client":"DiscordBot"})
        res = await self.execute("Login", {"Password": self.password}, include_token=False)
        # Expecting a token in response; adjust key as needed
        self._token = res.get("token") or res.get("Token") or res.get("access_token")
        return res

    async def execute(self, command: str, body: Optional[Dict[str, Any]]=None, include_token: bool=True) -> Dict[str, Any]:
        async with self._lock:
            if self._writer is None or self._writer.is_closing():
                await self.connect()
            if include_token and not self._token:
                await self.login()

            body = body or {}

            env: Dict[str, Any] = {"command": command, "version": 2, "body": body}

            # Inject token either into body (if required) or adjust build_header to place in header
            if include_token and self._token:
                if self.token_in_body:
                    env["body"]["Token"] = self._token
                else:
                    # Optionally place token in a "meta" field or handle in build_header()
                    env["meta"] = {"token": self._token}

            return await self.send_envelope(env)
