from __future__ import annotations

import base64
import hashlib
import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import websocket

log = logging.getLogger(__name__)


class ObsError(RuntimeError):
    pass


class ObsConnectionError(ObsError):
    pass


class ObsRequestError(ObsError):
    def __init__(self, request_type: str, code: int | None, comment: str):
        self.request_type = request_type
        self.code = code
        self.comment = comment
        super().__init__(f"{request_type} failed ({code}): {comment}")


@dataclass
class _Pending:
    ready: threading.Event = field(default_factory=threading.Event)
    response: dict[str, Any] | None = None
    error: Exception | None = None


class ObsClient:
    """Small thread-safe obs-websocket 5.x client with request correlation."""

    EVENT_SUBSCRIPTIONS = 0x7FF

    def __init__(self, request_timeout: float = 5.0) -> None:
        self.request_timeout = request_timeout
        self._ws = None
        self._reader: threading.Thread | None = None
        self._send_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._pending: dict[str, _Pending] = {}
        self._event_callbacks: list[Callable[[str, dict], None]] = []
        self._disconnect_callbacks: list[Callable[[Exception | None], None]] = []
        self._connected = False
        self._closing = False
        self.obs_version = ""
        self.websocket_version = ""

    @property
    def connected(self) -> bool:
        return self._connected

    def on_event(self, callback: Callable[[str, dict], None]) -> Callable:
        self._event_callbacks.append(callback)
        return callback

    def on_disconnect(self, callback: Callable[[Exception | None], None]) -> Callable:
        self._disconnect_callbacks.append(callback)
        return callback

    def connect(self, host: str, port: int, password: str = "") -> None:
        self.close()
        self._closing = False
        ws = None
        try:
            ws = websocket.create_connection(
                f"ws://{host}:{port}", timeout=self.request_timeout,
                enable_multithread=True,
            )
            hello = json.loads(ws.recv())
            if hello.get("op") != 0:
                raise ObsConnectionError("OBS did not send a WebSocket Hello message")
            identify: dict[str, Any] = {
                "rpcVersion": 1,
                "eventSubscriptions": self.EVENT_SUBSCRIPTIONS,
            }
            authentication = hello["d"].get("authentication")
            if authentication:
                identify["authentication"] = self._authentication_response(
                    password, authentication["salt"], authentication["challenge"],
                )
            ws.send(json.dumps({"op": 1, "d": identify}))
            identified = json.loads(ws.recv())
            if identified.get("op") != 2:
                raise ObsConnectionError("OBS rejected authentication or protocol negotiation")
            self._ws = ws
            self._connected = True
            self._reader = threading.Thread(
                target=self._reader_loop, name="OBS WebSocket", daemon=True,
            )
            self._reader.start()
            version = self.call("GetVersion")
            self.obs_version = version.get("obsVersion", "")
            self.websocket_version = version.get("obsWebSocketVersion", "")
        except Exception:
            self._connected = False
            try:
                if ws is not None:
                    ws.close()
            except Exception:
                pass
            raise

    @staticmethod
    def _authentication_response(password: str, salt: str, challenge: str) -> str:
        secret = base64.b64encode(hashlib.sha256(
            (password + salt).encode("utf-8")
        ).digest()).decode("ascii")
        return base64.b64encode(hashlib.sha256(
            (secret + challenge).encode("utf-8")
        ).digest()).decode("ascii")

    def close(self) -> None:
        self._closing = True
        self._connected = False
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        reader = self._reader
        if reader and reader.is_alive() and reader is not threading.current_thread():
            reader.join(timeout=1.0)
        self._reader = None
        self._fail_pending(ObsConnectionError("OBS connection closed"))

    def call(
        self, request_type: str, request_data: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if not self._connected or self._ws is None:
            raise ObsConnectionError("Not connected to OBS")
        request_id = str(uuid.uuid4())
        pending = _Pending()
        with self._state_lock:
            self._pending[request_id] = pending
        data: dict[str, Any] = {
            "requestType": request_type,
            "requestId": request_id,
        }
        if request_data is not None:
            data["requestData"] = request_data
        try:
            with self._send_lock:
                self._ws.send(json.dumps({"op": 6, "d": data}))
        except Exception as exc:
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise ObsConnectionError(str(exc)) from exc
        if not pending.ready.wait(timeout or self.request_timeout):
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(f"Timed out waiting for OBS request {request_type}")
        if pending.error:
            raise pending.error
        response = pending.response or {}
        status = response.get("requestStatus", {})
        if not status.get("result"):
            raise ObsRequestError(
                request_type, status.get("code"), status.get("comment", "Unknown error"),
            )
        return response.get("responseData", {})

    def _reader_loop(self) -> None:
        error: Exception | None = None
        try:
            while self._connected and self._ws is not None:
                message = json.loads(self._ws.recv())
                opcode = message.get("op")
                data = message.get("d", {})
                if opcode == 7:
                    with self._state_lock:
                        pending = self._pending.pop(data.get("requestId", ""), None)
                    if pending:
                        pending.response = data
                        pending.ready.set()
                elif opcode == 5:
                    for callback in tuple(self._event_callbacks):
                        try:
                            callback(data.get("eventType", ""), data.get("eventData", {}))
                        except Exception:
                            log.exception("OBS event callback failed")
        except Exception as exc:
            error = exc
            if not self._closing:
                log.warning("OBS WebSocket disconnected: %s", exc)
        finally:
            self._connected = False
            self._fail_pending(ObsConnectionError(str(error or "OBS disconnected")))
            if not self._closing:
                for callback in tuple(self._disconnect_callbacks):
                    try:
                        callback(error)
                    except Exception:
                        log.exception("OBS disconnect callback failed")

    def _fail_pending(self, error: Exception) -> None:
        with self._state_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for item in pending:
            item.error = error
            item.ready.set()
