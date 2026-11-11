import socket
import threading
import queue
from typing import Dict, Any, Optional

import sys
from pathlib import Path

# Ensure protocol.py and state.py can be found
sys.path.insert(0, str(Path(__file__).resolve().parents[1])) 
sys.path.insert(0, str(Path(__file__).resolve().parent))

from protocol import encode_message, extract_messages, decode_message, ProtocolError
from state import ClientState


class Connection:
    def __init__(self, state: ClientState):
        self.state = state
        self.sock: Optional[socket.socket] = None
        self.is_running = False
        
        # Thread locks: protect sending, request matching, and cleanup logic respectively
        self.send_lock = threading.Lock()
        self.pending_lock = threading.Lock()
        self.cleanup_lock = threading.Lock()
        
        # RPC synchronization mechanism: request_id -> threading.Event
        self.pending_requests: Dict[str, threading.Event] = {}
        self.responses: Dict[str, dict] = {}
        
        # Async event queue for E (UI) to consume
        self.event_queue = queue.Queue()
        
        self._request_id_counter = 0

    def connect(self, host: str, port: int, user_id: str, name: str) -> bool:
        """Establish a connection and send the hello request"""
        try:
            self.sock = socket.create_connection((host, port), timeout=5)
            # Set a 0.5-second timeout so the receive thread can periodically wake up and check the is_running flag, preventing deadlock
            self.sock.settimeout(0.5) 
            self.is_running = True
            
            # Start the background receive thread
            threading.Thread(target=self._receive_loop, daemon=True).start()
            
            # Send hello and wait for server confirmation
            resp = self.send_request("hello", {"user_id": user_id, "name": name})
            if resp and resp.get("ok"):
                self.state.set_connected(user_id, name)
                return True
            else:
                # Handshake failed (e.g., duplicate ID); actively disconnect
                self.disconnect()
                return False
        except Exception as e:
            print(f"Connection failed: {e}")
            self.disconnect()
            return False

    def send_request(self, req_type: str, data: dict, timeout: float = 5.0) -> dict:
        """Send a request and synchronously wait for the response (Blocking)"""
        if not self.is_running or not self.sock:
            return self._make_error_response("NOT_CONNECTED", "Not connected to server")

        # Generate a unique request_id
        with self.pending_lock:
            self._request_id_counter += 1
            req_id = str(self._request_id_counter)
            event = threading.Event()
            self.pending_requests[req_id] = event

        # Assemble and send the message
        message = {"type": req_type, "request_id": req_id, **data}
        try:
            payload = encode_message(message)
            with self.send_lock:  # Prevent multiple threads from writing to the socket simultaneously and causing frame interleaving
                if not self.sock:
                    raise ConnectionError("Socket is closed")
                self.sock.sendall(payload)
        except Exception as e:
            with self.pending_lock:
                self.pending_requests.pop(req_id, None)
            self._cleanup_connection()
            return self._make_error_response("NETWORK_ERROR", str(e))

        # Wait for the background receive thread to wake it up
        if event.wait(timeout):
            with self.pending_lock:
                resp = self.responses.pop(req_id, None)
                if resp is not None:
                    return resp
                # Event was set but there is no data, indicating the connection is lost
                return self._make_error_response("CONNECTION_LOST", "Server disconnected")
        else:
            # Timeout protection
            with self.pending_lock:
                self.pending_requests.pop(req_id, None)
            return self._make_error_response("TIMEOUT", "Request timed out")

    def _receive_loop(self):
        """Background receive thread: handle sticky/partial packets and dispatch responses and events"""
        buffer = bytearray()
        while self.is_running and self.sock:
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break  # Server closed the connection normally (EOF)
                
                buffer.extend(chunk)
                for frame in extract_messages(buffer):
                    message = decode_message(frame)
                    msg_type = message.get("type")
                    
                    if msg_type == "response":
                        req_id = message.get("request_id")
                        with self.pending_lock:
                            if req_id in self.pending_requests:
                                self.responses[req_id] = message
                                self.pending_requests[req_id].set()  # Wake up the waiting main thread
                                
                    elif msg_type == "event":
                        # 1. Put into the queue for UI consumption
                        self.event_queue.put(message)
                        # 2. Automatically update local state
                        self._handle_event_state_update(message)
                        
            except socket.timeout:
                # This is normal polling caused by settimeout(0.5); continue the loop
                continue
            except (ConnectionError, ProtocolError, OSError) as e:
                # Filter out system-level errors caused by active disconnect or forced close (Windows: 10038, 10054)
                win_err = getattr(e, 'winerror', None)
                if win_err in (10038, 10054):
                    break
                if self.is_running:
                    print(f"Network error in receiver: {e}")
                break
                
        self._cleanup_connection()

    def _handle_event_state_update(self, message: dict):
        """Update local state by calling state methods according to server events"""
        event = message.get("event")
        data = message.get("data", {})
        
        # Strictly match event names defined by B/C
        if event == "room_update":
            self.state.update_room_players(data.get("players", []))
        elif event == "question":
            self.state.set_question(data)
        elif event == "question_result":
            self.state.set_question_result(data)
        elif event == "leaderboard":
            self.state.finish_game(data.get("leaderboard", []))

    def disconnect(self):
        """Cleanup method called when UI exits normally"""
        self._cleanup_connection()

    def _cleanup_connection(self):
        """Handle disconnect cleanup work (thread-safe, guaranteed to execute only once)"""
        with self.cleanup_lock:
            if not self.is_running and not self.sock:
                return  # Already cleaned up
            
            self.is_running = False
            
            # Safely close socket
            if self.sock:
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    self.sock.close()
                except OSError:
                    pass
                self.sock = None
            
            # Wake up all send requests blocked in wait() to avoid UI thread deadlock
            with self.pending_lock:
                for event in self.pending_requests.values():
                    event.set()
                self.pending_requests.clear()
                
            self.state.set_disconnected()
            
            # Notify the UI thread: the server has disconnected, and the main loop can exit
            self.event_queue.put({"type": "event", "event": "server_shutdown", "data": {}})

    @staticmethod
    def _make_error_response(code: str, msg: str) -> dict:
        """Generate a local error response consistent with the server format"""
        return {
            "type": "error",
            "ok": False,
            "error": {"code": code, "message": msg}
        }
