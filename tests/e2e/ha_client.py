"""Minimal client for a real Home Assistant over REST and websocket.

Own and small on purpose (modelled on the sibling repo ha_innova_hrds): the old
`ha_integration_test_harness` called `requests` without a timeout, so a wedged container hung the
whole run, and it needed docker-compose and a `:stable` image tag.

Rules the client keeps:
- every HTTP and websocket call has a timeout;
- waiting is a poll against a deadline (`time.monotonic`), never a fixed sleep: it returns the
  moment the condition holds and fails with the last observed value when the deadline passes.
"""

from __future__ import annotations

import itertools
import json
import threading
import time
from collections.abc import Callable
from typing import Any

import requests
import websocket

DEFAULT_TIMEOUT = 30  # seconds, per call
POLL_INTERVAL = 0.5  # seconds between two polls of a condition
CLIENT_ID = "http://127.0.0.1:8123/"


class ServiceError(Exception):
    """A websocket command answered with an error (code + message)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class HomeAssistant:
    """One Home Assistant instance, onboarded, with a long-lived token."""

    def __init__(self, base_url: str = "http://127.0.0.1:8123") -> None:
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None
        self._ws: websocket.WebSocket | None = None
        self._ws_lock = threading.Lock()
        self._ids = itertools.count(1)

    # ---- startup -------------------------------------------------------------
    def wait_ready(self, timeout: float = 300) -> None:
        """Wait until the HTTP API answers (200, or 401 without a token)."""
        deadline = time.monotonic() + timeout
        last: object = None
        while time.monotonic() < deadline:
            try:
                resp = requests.get(f"{self.base_url}/api/", timeout=5)
                if resp.status_code in (200, 401):
                    return
                last = resp.status_code
            except requests.RequestException as exc:
                last = exc
            time.sleep(1)
        raise TimeoutError(f"Home Assistant not ready after {timeout}s: {last!r}")

    def wait_running(self, timeout: float = 300) -> None:
        """Wait until HA reports the state RUNNING (entries set up, `start` event fired).

        The API answers long before that, so this is what "booted" means after a restart.
        """
        deadline = time.monotonic() + timeout
        last: object = None
        while time.monotonic() < deadline:
            try:
                resp = requests.get(
                    f"{self.base_url}/api/config", headers=self._headers, timeout=5
                )
                if resp.status_code == 200 and resp.json().get("state") == "RUNNING":
                    return
                last = resp.status_code
            except requests.RequestException as exc:
                last = exc
            time.sleep(1)
        raise TimeoutError(f"Home Assistant not running after {timeout}s: {last!r}")

    def onboard(self, username: str = "ci", password: str = "ci-password") -> None:
        """Create the owner on a fresh instance, finish onboarding, swap to a long-lived token."""
        resp = requests.post(
            f"{self.base_url}/api/onboarding/users",
            json={
                "client_id": CLIENT_ID,
                "name": "CI",
                "username": username,
                "password": password,
                "language": "en",
            },
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        code = resp.json()["auth_code"]
        resp = requests.post(
            f"{self.base_url}/auth/token",
            data={"grant_type": "authorization_code", "code": code, "client_id": CLIENT_ID},
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        self.token = resp.json()["access_token"]
        for step, body in (
            ("core_config", {}),
            ("analytics", {}),
            ("integration", {"client_id": CLIENT_ID, "redirect_uri": CLIENT_ID}),
        ):
            # Finish onboarding so the instance behaves like a normal install afterwards.
            requests.post(
                f"{self.base_url}/api/onboarding/{step}",
                json=body,
                headers=self._headers,
                timeout=DEFAULT_TIMEOUT,
            )
        # The short-lived access token expires; a long-lived one lasts the whole session
        # (and survives container restarts, as it is stored in HA's auth storage).
        self.token = self.ws(
            {"type": "auth/long_lived_access_token", "client_name": "e2e", "lifespan": 1}
        )

    # ---- REST ----------------------------------------------------------------
    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, path: str) -> Any:
        resp = requests.get(
            f"{self.base_url}{path}", headers=self._headers, timeout=DEFAULT_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, body: dict | None = None) -> Any:
        resp = requests.post(
            f"{self.base_url}{path}",
            json=body or {},
            headers=self._headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code >= 400:
            raise requests.HTTPError(f"{resp.status_code} {path}: {resp.text}")
        return resp.json()

    def get_state(self, entity_id: str) -> dict | None:
        """The entity's state object, or None if it does not exist."""
        resp = requests.get(
            f"{self.base_url}/api/states/{entity_id}",
            headers=self._headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def states(self) -> dict[str, dict]:
        """All state objects by entity id."""
        return {s["entity_id"]: s for s in self.get("/api/states")}

    # ---- config entries ------------------------------------------------------
    def flow_start(self, handler: str) -> dict:
        return self.post("/api/config/config_entries/flow", {"handler": handler})

    def flow_configure(self, flow_id: str, data: dict) -> dict:
        return self.post(f"/api/config/config_entries/flow/{flow_id}", data)

    def config_entries(self, domain: str | None = None) -> list[dict]:
        query = f"?domain={domain}" if domain else ""
        return self.get(f"/api/config/config_entries/entry{query}")

    # ---- websocket -----------------------------------------------------------
    def ws(self, message: dict) -> Any:
        """Send one websocket command and return its result."""
        with self._ws_lock:
            if self._ws is None:
                self._ws = self._ws_connect()
            msg_id = next(self._ids)
            self._ws.send(json.dumps({"id": msg_id, **message}))
            while True:
                reply = json.loads(self._ws.recv())
                if reply.get("id") == msg_id and reply.get("type") == "result":
                    break
        if not reply["success"]:
            err = reply.get("error", {})
            raise ServiceError(err.get("code", "unknown"), err.get("message", ""))
        return reply.get("result")

    def _ws_connect(self) -> websocket.WebSocket:
        url = self.base_url.replace("http", "ws", 1) + "/api/websocket"
        conn = websocket.create_connection(url, timeout=DEFAULT_TIMEOUT)
        json.loads(conn.recv())  # auth_required
        conn.send(json.dumps({"type": "auth", "access_token": self.token}))
        reply = json.loads(conn.recv())
        if reply.get("type") != "auth_ok":
            raise RuntimeError(f"websocket auth failed: {reply}")
        return conn

    def close(self) -> None:
        """Drop the websocket (a container restart kills it anyway)."""
        if self._ws is not None:
            self._ws.close()
            self._ws = None

    def call_service(
        self, domain: str, service: str, entity_id: str | None = None, **data: Any
    ) -> None:
        message: dict[str, Any] = {"type": "call_service", "domain": domain, "service": service}
        if data:
            message["service_data"] = data
        if entity_id:
            message["target"] = {"entity_id": entity_id}
        self.ws(message)

    def entity_registry(self) -> list[dict]:
        return self.ws({"type": "config/entity_registry/list"})

    def entity_registry_update(self, entity_id: str, **changes: Any) -> dict:
        return self.ws(
            {"type": "config/entity_registry/update", "entity_id": entity_id, **changes}
        )

    # ---- waiting -------------------------------------------------------------
    def wait_for(
        self,
        check: Callable[[], Any],
        what: str,
        timeout: float = 30,
    ) -> Any:
        """Poll `check()` until it returns something truthy; return that value.

        On timeout the error names `what` and the last value `check` returned.
        """
        deadline = time.monotonic() + timeout
        while True:
            value = check()
            if value:
                return value
            if time.monotonic() > deadline:
                raise AssertionError(f"timed out after {timeout}s waiting for {what}; last: {value!r}")
            time.sleep(POLL_INTERVAL)

    def wait_stable(self, entity_id: str, quiet: float = 2.0, timeout: float = 30) -> dict:
        """Poll until the entity's state has not changed for `quiet` seconds; return it.

        For a value that settles after a burst of events (an integral after the last input), where
        there is no single state to wait for.
        """
        deadline = time.monotonic() + timeout
        last: str | None = None
        since = time.monotonic()
        while True:
            state = self.get_state(entity_id)
            now = time.monotonic()
            if state is None or state["state"] != last:
                last, since = (state or {}).get("state"), now
            elif now - since >= quiet:
                return state
            if now > deadline:
                raise AssertionError(f"{entity_id} kept changing for {timeout}s; last {last!r}")
            time.sleep(POLL_INTERVAL / 2)

    def assert_entity_state(
        self,
        entity_id: str,
        expected: str | Callable[[dict], bool],
        timeout: float = 30,
    ) -> dict:
        """Poll until the entity's state equals `expected` (or the predicate holds)."""
        last: dict | None = None

        def matches() -> dict | None:
            nonlocal last
            last = self.get_state(entity_id)
            if last is None:
                return None
            ok = expected(last) if callable(expected) else last["state"] == expected
            return last if ok else None

        try:
            return self.wait_for(matches, f"{entity_id} == {expected!r}", timeout)
        except AssertionError as exc:
            shown = None if last is None else {"state": last["state"], "attributes": last["attributes"]}
            raise AssertionError(f"{entity_id}: expected {expected!r} within {timeout}s, last {shown}") from exc
