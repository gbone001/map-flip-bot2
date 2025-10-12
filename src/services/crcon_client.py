from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import httpx


class CrconClient:
    """
    Async HTTP client for CRCON's documented API surface.

    The client discovers available endpoints from `/api/get_api_documentation`
    so it adapts automatically to deployments that rename map-changing
    endpoints (e.g. `map`, `set_next_map`, `end_map`, `do_end_map`, etc.).
    """

    _DEFAULT_ENDPOINTS = (
        "map",
        "set_next_map",
        "end_map",
        "do_end_map",
        "get_public_info",
        "get_map_rotation",
    )

    def __init__(self, base_url: str, api_token: str, timeout: float = 15.0):
        self.base = base_url.rstrip("/") if base_url else ""
        self.token = api_token
        self._client = httpx.AsyncClient(timeout=timeout)
        self._endpoints: Dict[str, bool] = {}
        self._endpoints_meta: Dict[str, Dict[str, Any]] = {}
        self._catalog_ready = False
        self._auth_scheme: Optional[str] = None  # Either "Bearer" or "Token"

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            scheme = self._auth_scheme or "Bearer"
            headers["Authorization"] = f"{scheme} {self.token}"
        return headers

    def _candidate_urls(self, endpoint: str) -> List[str]:
        if not endpoint:
            return []
        trimmed = endpoint.strip("/")
        variants = []
        prefixes = [f"api/{trimmed}", trimmed]
        for path in prefixes:
            for suffix in ("", "/"):
                candidate = f"{self.base}/{path}{suffix}".rstrip("/")
                if candidate not in variants:
                    variants.append(candidate)
        return variants

    async def _ensure_catalog(self) -> None:
        if self._catalog_ready or not self.base or not self.token:
            self._catalog_ready = True
            return

        self._endpoints = {}
        self._endpoints_meta = {}
        schemes = ("Bearer", "Token")

        for scheme in schemes:
            try:
                response = await self._client.get(
                    self._url("get_api_documentation"),
                    headers={"Authorization": f"{scheme} {self.token}", "Content-Type": "application/json"},
                )
                if response.status_code == 401:
                    continue
                response.raise_for_status()
                data = response.json()
                if isinstance(data, list):
                    for entry in data:
                        name = entry.get("endpoint")
                        if not name:
                            continue
                        self._endpoints[name] = True
                        args = entry.get("args") or entry.get("parameters") or []
                        if isinstance(args, dict):
                            args = list(args.keys())
                        self._endpoints_meta[name] = {
                            "method": entry.get("method"),
                            "args": args,
                        }
                if self._endpoints:
                    self._auth_scheme = scheme
                    break
            except Exception:
                continue

        if not self._endpoints:
            for name in self._DEFAULT_ENDPOINTS:
                self._endpoints[name] = True
                self._endpoints_meta[name] = {}
            if not self._auth_scheme:
                self._auth_scheme = "Bearer"

        self._catalog_ready = True

    def _has(self, name: str) -> bool:
        return self._endpoints.get(name, False)

    def _arg_name_for_map(self, endpoint: str) -> str:
        candidates = ("map_name", "map", "name")
        meta = self._endpoints_meta.get(endpoint, {})
        args = meta.get("args") or []
        if isinstance(args, dict):
            args = list(args.keys())
        for candidate in candidates:
            if candidate in args:
                return candidate
        return candidates[0]

    async def _post(
        self,
        endpoint: str,
        payload: Dict[str, Any],
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        urls = self._candidate_urls(endpoint)
        if not urls:
            return False, "Invalid endpoint", None

        last_error: Tuple[bool, str, Optional[Dict[str, Any]]] = (False, "Request failed", None)

        for idx, url in enumerate(urls):
            try:
                response = await self._client.post(url, json=payload, headers=self._headers())
            except Exception as exc:
                last_error = (False, f"{url} error: {exc}", None)
                continue

            if response.status_code == 404 and idx + 1 < len(urls):
                last_error = (False, f"HTTP 404: {response.text[:200]}", None)
                continue

            if response.status_code // 100 != 2:
                return False, f"HTTP {response.status_code}: {response.text[:200]}", None

            try:
                data = response.json()
            except ValueError as exc:
                return False, f"{url} parse error: {exc}", None

            failed = bool(data.get("failed", False))
            message = data.get("error") or data.get("result") or "ok"
            return (not failed, message, data)

        return last_error

    async def _get(self, endpoint: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        urls = self._candidate_urls(endpoint)
        if not urls:
            return False, "Invalid endpoint", None

        last_error: Tuple[bool, str, Optional[Dict[str, Any]]] = (False, "Request failed", None)

        for idx, url in enumerate(urls):
            try:
                response = await self._client.get(url, headers=self._headers())
            except Exception as exc:
                last_error = (False, f"{url} error: {exc}", None)
                continue

            if response.status_code == 404 and idx + 1 < len(urls):
                last_error = (False, f"HTTP 404: {response.text[:200]}", None)
                continue

            if response.status_code // 100 != 2:
                return False, f"HTTP {response.status_code}: {response.text[:200]}", None

            try:
                data = response.json()
            except ValueError as exc:
                return False, f"{url} parse error: {exc}", None

            failed = bool(data.get("failed", False))
            message = data.get("error") or "ok"
            return (not failed, message, data)

        return last_error

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def get_public_info(self) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        await self._ensure_catalog()
        if not self._has("get_public_info"):
            return False, None, "get_public_info endpoint unavailable"

        ok, msg, data = await self._get("get_public_info")
        if not ok or not isinstance(data, dict):
            return False, None, msg
        return True, data.get("result"), None

    async def get_map_rotation(self) -> Tuple[bool, Optional[Any], Optional[str]]:
        await self._ensure_catalog()
        if not self._has("get_map_rotation"):
            return False, None, "get_map_rotation endpoint unavailable"

        ok, msg, data = await self._get("get_map_rotation")
        if not ok or not isinstance(data, dict):
            return False, None, msg
        return True, data.get("result"), None

    async def change_map(self, map_name: str) -> Tuple[bool, str]:
        await self._ensure_catalog()
        if not self.base or not self.token:
            return False, "CRCON not configured"

        if self._has("map"):
            arg_name = self._arg_name_for_map("map")
            ok, msg, _ = await self._post("map", {arg_name: map_name})
            if ok:
                return True, f"Map change requested via /api/map: {map_name}"

        if self._has("set_next_map"):
            arg_name = self._arg_name_for_map("set_next_map")
            ok_set, msg_set, _ = await self._post("set_next_map", {arg_name: map_name})
            if not ok_set:
                return False, f"set_next_map failed: {msg_set}"

            end_ep = None
            for candidate in ("end_map", "do_end_map"):
                if self._has(candidate):
                    end_ep = candidate
                    break

            if not end_ep:
                return False, "No end_map / do_end_map endpoint available after set_next_map"

            ok_end, msg_end, _ = await self._post(end_ep, {})
            if ok_end:
                return True, f"Next map set and end triggered: {map_name}"
            return False, f"{end_ep} failed: {msg_end}"

        return False, "No supported map-change endpoints found (map / set_next_map)."

    async def change_map_by_id(self, map_id: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        await self._ensure_catalog()
        if not self.base or not self.token:
            return False, "CRCON not configured", None

        payload = {"MapId": map_id}
        ok, message, data = await self._post("commands/execute", {"command": "ChangeMap", "version": 2, "body": payload})
        if ok:
            return True, f"ChangeMap sent for {map_id}", data
        return False, message, data

    async def execute_command(self, command: str, body: Optional[Dict[str, Any]] = None, version: int = 2) -> Dict[str, Any]:
        await self._ensure_catalog()
        payload = {"command": command, "version": version, "body": body or {}}
        ok, message, data = await self._post("commands/execute", payload)
        if not ok:
            raise RuntimeError(message)
        return data or {}

    async def get_client_reference(self, name: str) -> Dict[str, Any]:
        return await self.execute_command("GetClientReferenceData", {"Name": name})

    async def get_available_map_ids(self) -> List[str]:
        data = await self.get_client_reference("AddMapToRotation")
        params = data.get("dialogueParameters") or data.get("DialogueParameters") or []
        for param in params:
            if isinstance(param, dict) and param.get("name") == "MapName":
                member = param.get("valueMember") or param.get("ValueMember")
                if isinstance(member, str):
                    return [item.strip() for item in member.split(",") if item.strip()]
                if isinstance(member, list):
                    return [str(item) for item in member if item]
        return []

    async def get_objective_choices(self) -> List[Dict[str, Any]]:
        data = await self.get_client_reference("SetSectorLayout")
        choices = data.get("choices") or data.get("Choices")
        if isinstance(choices, list):
            return [choice for choice in choices if isinstance(choice, dict)]
        return []

    async def set_objectives(self, selections: List[Dict[str, Any]]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        payload = {"Objectives": selections}
        ok, message, data = await self._post(
            "commands/execute",
            {"command": "SetSectorLayout", "version": 2, "body": payload},
        )
        return ok, message, data

    async def get_sector_layout(self) -> List[Dict[str, Any]]:
        try:
            data = await self.execute_command("GetSectorLayout", {})
        except RuntimeError:
            return []
        result = data.get("result") or data.get("Result") or {}
        layout = result.get("layout") or result.get("Layout")
        if isinstance(layout, list):
            return [item for item in layout if isinstance(item, dict)]
        return []

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "CrconClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()
