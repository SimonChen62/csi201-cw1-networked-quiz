"""D's TCP client, with response/state hand-off used by E's CLI."""

from dataclasses import dataclass, field
from pathlib import Path
import queue
import socket
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol import encode_message, extract_messages, decode_message, ProtocolError

try:
    from .state import ClientState
except ImportError:  # Existing tests import this module directly.
    from state import ClientState


@dataclass
class PendingRequest:
    request_type: str
    data: dict
    event: threading.Event = field(default_factory=threading.Event)
    response: dict | None = None


class Connection:
    def __init__(self, state: ClientState):
        self.state = state
        self.sock = None
        self.is_running = False
        self.send_lock = threading.Lock()
        self.pending_lock = threading.Lock()
        self.cleanup_lock = threading.Lock()
        self.pending_requests = {}
        self.event_queue = queue.Queue()
        self._request_id_counter = 0
        self._reader = None
        self._cancelled = threading.Event()
        self.last_error = None

    def connect(self, host: str, port: int, user_id: str, name: str) -> bool:
        """Blocking connect/hello. E calls this from its request worker."""
        try:
            sock = socket.create_connection((host, port), timeout=5)
            sock.settimeout(0.5)
            with self.cleanup_lock:
                if self._cancelled.is_set():
                    sock.close()
                    return False
                self.sock = sock
                self.is_running = True
            self._reader = threading.Thread(target=self._receive_loop, daemon=True)
            self._reader.start()
            response = self.send_request("hello", {"user_id": user_id, "name": name})
            if response.get("ok") and self.is_running:
                return True
            self.last_error = response
            self._cleanup_connection("login_failed")
        except OSError as exc:
            self.last_error = self._make_error_response("CONNECT_FAILED", str(exc))
            self._cleanup_connection("connect_failed")
        return False

    def send_request(self, req_type: str, data: dict, timeout: float = 5.0) -> dict:
        """Wait for one correlated response; never call on the UI event loop."""
        if not self.is_running or self.sock is None:
            return self._make_error_response("NOT_CONNECTED", "Not connected to server")
        if not isinstance(data, dict) or {"type", "request_id"} & data.keys():
            return self._make_error_response("INVALID_REQUEST", "Reserved request fields")
        with self.pending_lock:
            self._request_id_counter += 1
            request_id = str(self._request_id_counter)
            pending = PendingRequest(req_type, dict(data))
            self.pending_requests[request_id] = pending
        try:
            try:
                payload = encode_message({"type": req_type, "request_id": request_id, **data})
            except ProtocolError as exc:
                return self._make_error_response("INVALID_REQUEST", str(exc), request_id)
            try:
                with self.send_lock:
                    sock = self.sock
                    if sock is None:
                        raise ConnectionError("Socket is closed")
                    sock.sendall(payload)
            except OSError as exc:
                self._cleanup_connection("network_error")
                return self._make_error_response("NETWORK_ERROR", str(exc), request_id)
            pending.event.wait(timeout)
            # The same lock resolves a response arriving at the timeout boundary.
            with self.pending_lock:
                self.pending_requests.pop(request_id, None)
                if pending.response is not None:
                    return pending.response
                return self._make_error_response(
                    "TIMEOUT", "Request timed out; server outcome is unknown", request_id
                )
        finally:
            with self.pending_lock:
                self.pending_requests.pop(request_id, None)

    def _receive_loop(self):
        buffer = bytearray()
        reason = "connection_closed"
        try:
            while self.is_running and self.sock is not None:
                try:
                    sock = self.sock
                    if sock is None:
                        break
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                    for frame in extract_messages(buffer):
                        message = decode_message(frame)
                        msg_type = message.get("type")
                        if msg_type == "response":
                            self._complete_request(message)
                        elif msg_type == "event":
                            data = message.get("data", {})
                            if not isinstance(data, dict):
                                raise ProtocolError("Event data must be an object")
                            if message.get("event") == "server_shutdown":
                                self._cleanup_connection(
                                    data.get("reason", "server_shutdown"), message
                                )
                                return
                            # State is updated before the UI can consume this event.
                            if self._handle_event_state_update(message):
                                self.event_queue.put(message)
                        else:
                            self.event_queue.put({
                                "type": "client_notice", "code": "UNKNOWN_MESSAGE",
                                "message": f"Unsupported message type: {msg_type}",
                            })
                except socket.timeout:
                    continue
        except (OSError, ProtocolError, ValueError, TypeError, KeyError) as exc:
            reason = "network_error"
            if self.is_running:
                self.last_error = self._make_error_response("RECEIVE_ERROR", str(exc))
        finally:
            self._cleanup_connection(reason)

    def _complete_request(self, message):
        request_id = message.get("request_id")
        if not isinstance(request_id, str):
            self.event_queue.put({
                "type": "client_notice",
                "code": message.get("error", {}).get("code", "UNMATCHED_RESPONSE"),
                "message": message.get("error", {}).get("message", "Response has no matching request ID"),
            })
            return
        with self.pending_lock:
            pending = self.pending_requests.get(request_id)
            if pending is None:
                self.event_queue.put({
                    "type": "client_notice", "code": "LATE_RESPONSE",
                    "message": f"Late response for request {request_id}; refresh room status before retrying.",
                })
                return
            if message.get("ok") and self.is_running:
                try:
                    self._apply_response_state(pending, message.get("data", {}))
                except (ValueError, TypeError, KeyError) as exc:
                    message = self._make_error_response("INVALID_RESPONSE", str(exc), request_id)
            pending.response = message
            pending.event.set()

    def _apply_response_state(self, pending, data):
        """Apply successful replies in receive order, before subsequent events."""
        if not isinstance(data, dict):
            raise ValueError("Response data must be an object")
        command, sent = pending.request_type, pending.data
        if command == "hello":
            self.state.set_connected(sent["user_id"], sent["name"])
        elif command == "list_quizzes" and "quizzes" in data:
            self.state.update_quizzes(data["quizzes"])
        elif command == "list_rooms" and "rooms" in data:
            self.state.update_rooms(data["rooms"])
        elif command in ("create_room", "join_room"):
            room = data.get("room")
            if not isinstance(room, dict):
                raise ValueError("Room response must contain data.room")
            self.state.enter_room(
                room["room_id"], room["host_user_id"], room["players"],
                quiz_id=room.get("quiz_id"), phase=room.get("state", "WAITING"),
            )
        elif command in ("inspect_room", "ready") and "room" in data:
            self.state.update_room(data["room"])
        elif command == "start_game":
            snapshot = self.state.get_snapshot()
            if snapshot["current_room_id"] == sent.get("room_id") and snapshot["room_phase"] == "WAITING":
                self.state.start_game()
        elif command == "answer" and data.get("accepted", True):
            self.state.mark_answered(sent.get("question_id"), sent.get("room_id"))
        elif command == "leave_room":
            if self.state.get_snapshot()["current_room_id"] == sent.get("room_id"):
                self.state.leave_room()

    def _handle_event_state_update(self, message):
        event, data = message.get("event"), message.get("data", {})
        if event == "question":
            required = ("question_id", "text", "options", "time_limit", "points")
            if any(key not in data for key in required) or not isinstance(data["options"], dict):
                raise ProtocolError("Question event is missing required fields")
        if event == "question_result" and any(key not in data for key in ("question_id", "answer", "scores")):
            raise ProtocolError("Question result is missing required fields")
        snapshot = self.state.get_snapshot()
        room_id = data.get("room_id")
        if room_id is not None and room_id != snapshot["current_room_id"]:
            return False
        if event == "room_update":
            return self.state.update_room(data)
        if event == "question":
            return self.state.set_question(data)
        if event == "question_result":
            return self.state.set_question_result(data)
        if event == "leaderboard":
            self.state.finish_game(data.get("leaderboard", []))
        return True

    def disconnect(self):
        self._cancelled.set()
        self._cleanup_connection("client_quit")
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(timeout=1)

    def _cleanup_connection(self, reason="connection_closed", notification=None):
        with self.cleanup_lock:
            if not self.is_running and self.sock is None:
                return
            self.is_running = False
            sock, self.sock = self.sock, None
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()
            with self.pending_lock:
                for request_id, pending in self.pending_requests.items():
                    if pending.response is None:
                        pending.response = self._make_error_response(
                            "CONNECTION_LOST", "Server disconnected", request_id
                        )
                    pending.event.set()
                self.pending_requests.clear()
            self.state.set_disconnected()
            self.event_queue.put(notification or {
                "type": "event", "event": "server_shutdown", "data": {"reason": reason},
            })

    @staticmethod
    def _make_error_response(code, message, request_id=None):
        return {
            "type": "response", "request_id": request_id, "ok": False,
            "error": {"code": code, "message": message},
        }
