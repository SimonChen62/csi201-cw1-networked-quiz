"""Fake Server for testing client network robustness."""
import socket
import threading
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol import encode_message, extract_messages, decode_message

class FakeServer(threading.Thread):
    def __init__(self, mode: str = "normal", port: int = 0):
        super().__init__(daemon=True)
        self.mode = mode
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(("127.0.0.1", port))
        self.port = self.server_sock.getsockname()[1]
        self.server_sock.listen(1)
        print(f"[FakeServer] Listening on 127.0.0.1:{self.port} mode={self.mode}")

    def run(self):
        conn = None
        try:
            conn, _ = self.server_sock.accept()
            print(f"[FakeServer] Client connected")
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

                    if self.mode == "disconnect":
                        # Close while a request is pending, rather than timing out
                        # or racing the client's initial send.
                        return
                    if self.mode == "timeout":
                        continue
                    data = {"msg": "hello"} if req.get("type") == "ping" else {}
                    resp = encode_message({"type": "response", "request_id": req_id, "ok": True, "data": data})
                    if self.mode == "half_packet":
                        midpoint = len(resp) // 2
                        conn.sendall(resp[:midpoint])
                        time.sleep(0.05)
                        conn.sendall(resp[midpoint:])
                    elif self.mode == "event_and_response" and req.get("type") == "list_rooms":
                        event = encode_message({
                            "type": "event", "event": "room_update",
                            "data": {
                                "room_id": "r1",
                                "players": [{"user_id": "u2", "name": "Bob", "ready": False}],
                            },
                        })
                        conn.sendall(event + resp)
                    else:
                        conn.sendall(resp)
        finally:
            if conn:
                try: conn.close()
                except Exception: pass
            try: self.server_sock.close()
            except Exception: pass
            print(f"[FakeServer] Shutting down")

if __name__ == "__main__":
    # 直接运行此文件时，启动一个一直运行的服务器
    server = FakeServer("normal", 5001)
    server.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Server stopped.")
