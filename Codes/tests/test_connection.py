import sys
import unittest
import time
import socket
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client_modules"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from state import ClientState
from connection import Connection
from fake_server import FakeServer

class TestConnection(unittest.TestCase):
    def setUp(self):
        self.state = ClientState()
        self.conn = Connection(self.state)

    def tearDown(self):
        self.conn.disconnect()

    def test_01_normal_connection(self):
        """Test normal connection and handshake"""
        server = FakeServer(mode="normal")
        server.start()
        
        success = self.conn.connect("127.0.0.1", server.port, "u1", "Alice")
        self.assertTrue(success)
        self.assertTrue(self.state.connected)
        self.assertEqual(self.state.user_id, "u1")

    def test_02_half_packet(self):
        """Test half-packet: the server splits one message into two segments, and the client should reassemble it correctly"""
        server = FakeServer(mode="half_packet")
        server.start()
        
        success = self.conn.connect("127.0.0.1", server.port, "u1", "Alice")
        self.assertTrue(success)
        
        # Test a second request to verify continuous communication capability
        resp = self.conn.send_request("ping", {})
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["data"]["msg"], "hello")

    def test_03_event_and_response(self):
        """Test sticky packets and event dispatch: the server sends an event and a response together"""
        server = FakeServer(mode="event_and_response")
        server.start()
        
        success = self.conn.connect("127.0.0.1", server.port, "u1", "Alice")
        self.assertTrue(success)
        
        # Verify the response is matched successfully
        self.state.enter_room("r1", "u1", [])
        resp = self.conn.send_request("list_rooms", {})
        self.assertTrue(resp["ok"])
        
        # Wait briefly for the background thread to put the event into the queue
        time.sleep(0.1)
        self.assertFalse(self.conn.event_queue.empty())
        event = self.conn.event_queue.get()
        self.assertEqual(event["event"], "room_update")
        
        # Verify that state is updated correctly
        self.assertEqual(len(self.state.players_in_room), 1)
        self.assertEqual(self.state.players_in_room["u2"].name, "Bob")

    def test_04_server_disconnect(self):
        """Test sudden server disconnect: the request should return an error immediately to prevent deadlock"""
        server = FakeServer(mode="disconnect")
        server.start()
        
        # The server disconnects directly, so connect should return False
        success = self.conn.connect("127.0.0.1", server.port, "u1", "Alice")
        self.assertFalse(success)
        self.assertFalse(self.state.connected)
        self.assertEqual(self.conn.last_error["error"]["code"], "CONNECTION_LOST")
        
        # There should be a server_shutdown event in the queue
        event = self.conn.event_queue.get(timeout=1)
        self.assertEqual(event["event"], "server_shutdown")

    def test_05_request_timeout(self):
        """Test request timeout: the server does not reply, and the client should return TIMEOUT after the timeout"""
        server = FakeServer(mode="timeout")
        server.start()
        
        # Manually establish the connection
        self.conn.sock = socket.create_connection(("127.0.0.1", server.port))
        self.conn.is_running = True
        threading.Thread(target=self.conn._receive_loop, daemon=True).start()
        
        # Send a request with a timeout of 0.5 seconds
        resp = self.conn.send_request("slow_request", {}, timeout=0.5)
        self.assertFalse(resp["ok"])
       
        self.assertEqual(resp["type"], "response")
        self.assertEqual(resp["error"]["code"], "TIMEOUT")

    def test_06_local_error_response_format(self):
        """Test that locally synthesized network errors use the unified 'response' envelope format"""
        # No connection established, triggering a local NOT_CONNECTED error
        resp = self.conn.send_request("any_command", {})
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["type"], "response")
        self.assertEqual(resp["error"]["code"], "NOT_CONNECTED")

if __name__ == "__main__":
    unittest.main()
