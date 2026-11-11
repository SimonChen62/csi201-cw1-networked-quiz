"""Fake Server for testing client network robustness."""
import socket
import threading
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol import encode_message, extract_messages, decode_message

class FakeServer(threading.Thread):
    def __init__(self, mode: str):
        super().__init__(daemon=True)
        self.mode = mode
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(("127.0.0.1", 0))
        self.port = self.server_sock.getsockname()[1]
        self.server_sock.listen(1)

    def run(self):
        conn = None
        try:
            conn, _ = self.server_sock.accept()
            buffer = bytearray()
            while True:
                try:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                except Exception:
                    break

                buffer.extend(chunk)
                frames = extract_messages(buffer)
                
                for frame in frames:
                    req = decode_message(frame)
                    req_id = req.get("request_id", "1")

                    if self.mode == "normal":
                        resp = encode_message({"type": "response", "request_id": req_id, "ok": True})
                        conn.sendall(resp)
                        
                    elif self.mode == "half_packet":
                        # Intentionally split a complete message into two halves and send them
                        resp = encode_message({"type": "response", "request_id": req_id, "ok": True, "data": {"msg": "hello"}})
                        conn.sendall(resp[:10])
                        time.sleep(0.1)
                        conn.sendall(resp[10:])
                        
                    elif self.mode == "event_and_response":
                        # Send an event first, then send a response (sticky-packet combined send)
                        event = encode_message({"type": "event", "event": "room_update", "data": {"players": [{"user_id": "u2", "name": "Bob"}]}})
                        resp = encode_message({"type": "response", "request_id": req_id, "ok": True})
                        conn.sendall(event + resp)
                        
                    elif self.mode == "disconnect":
                        conn.close()
                        return
                        
                    elif self.mode == "timeout":
                        time.sleep(3)
                        
        finally:
            if conn:
                try: conn.close()
                except Exception: pass
            try: self.server_sock.close()
            except Exception: pass
