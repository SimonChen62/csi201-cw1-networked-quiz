"""阶段 3：同一个 TCP 连接上连续发送多条消息。"""

import os
import json
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import unittest


CODES = Path(__file__).resolve().parents[1]


class EchoTest(unittest.TestCase):
    def test_ten_simultaneous_clients_receive_independent_responses(self):
        environment = {**os.environ, "PYTHONUTF8": "1"}
        with subprocess.Popen(
            [sys.executable, "-u", str(CODES / "server.py"),
             "--host", "127.0.0.1", "--port", "0", "--lab-mode"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", env=environment,
        ) as server:
            clients = []
            readers = []
            try:
                ready = server.stdout.readline().strip()
                self.assertTrue(ready.startswith("LAB_LISTENING "), ready)
                _, host, port = ready.split()
                clients = [
                    socket.create_connection((host, int(port)), timeout=5)
                    for _ in range(10)
                ]
                # All ten TCP connections are established before any request is sent.
                requests = [
                    {"type": "echo", "request_id": 1, "text": f"client-{index}"}
                    for index in range(10)
                ]
                for client, request in zip(clients, requests):
                    client.sendall((json.dumps(request) + "\n").encode("utf-8"))

                readers = [client.makefile("rb") for client in clients]
                responses = [json.loads(reader.readline()) for reader in readers]
                self.assertEqual(
                    [response["data"]["text"] for response in responses],
                    [request["text"] for request in requests],
                )
                self.assertEqual(
                    [response["request_id"] for response in responses],
                    [1] * 10,
                )
            finally:
                for reader in readers:
                    reader.close()
                for client in clients:
                    client.close()
                if server.poll() is None:
                    server.terminate()
                    server.wait(timeout=5)

    def test_json_responses_and_malformed_message_error_share_connection(self):
        environment = {**os.environ, "PYTHONUTF8": "1"}
        with subprocess.Popen(
            [sys.executable, "-u", str(CODES / "server.py"),
             "--host", "127.0.0.1", "--port", "0", "--lab-mode"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", env=environment,
        ) as server:
            try:
                lines = queue.Queue()
                threading.Thread(
                    target=lambda: lines.put(server.stdout.readline()), daemon=True,
                ).start()
                try:
                    ready = lines.get(timeout=5).strip()
                except queue.Empty:
                    self.fail("服务器没有在 5 秒内报告监听地址")
                self.assertTrue(ready.startswith("LAB_LISTENING "), ready)
                _, host, port = ready.split()
                client = subprocess.run(
                    [sys.executable, str(CODES / "tests" / "server_temp_test.py"),
                     "--server", host, "--port", port,
                     "--message", "first", "--message", "second",
                     "--send-malformed"],
                    capture_output=True, text=True, encoding="utf-8",
                    env=environment, timeout=5,
                )
                self.assertEqual(client.returncode, 0, client.stderr)
                self.assertIn('"request_id": 1', client.stdout)
                self.assertIn('"request_id": 2', client.stdout)
                self.assertIn('"code": "MALFORMED_MESSAGE"', client.stdout)
                server.terminate()
                server.wait(timeout=5)
            finally:
                if server.poll() is None:
                    server.kill()
                    server.wait(timeout=5)

    def test_two_clients_receive_their_own_responses(self):
        environment = {**os.environ, "PYTHONUTF8": "1"}
        with subprocess.Popen(
            [sys.executable, "-u", str(CODES / "server.py"),
             "--host", "127.0.0.1", "--port", "0", "--lab-mode"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", env=environment,
        ) as server:
            try:
                ready = server.stdout.readline().strip()
                self.assertTrue(ready.startswith("LAB_LISTENING "), ready)
                _, host, port = ready.split()
                clients = [
                    subprocess.Popen(
                        [sys.executable, str(CODES / "tests" / "server_temp_test.py"),
                         "--server", host, "--port", port,
                         "--message", text],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, encoding="utf-8", env=environment,
                    )
                    for text in ("client one", "client two")
                ]
                outputs = []
                for client in clients:
                    output, error = client.communicate(timeout=5)
                    self.assertEqual(client.returncode, 0, error)
                    outputs.append(output)
                self.assertIn('"text": "client one"', outputs[0])
                self.assertIn('"text": "client two"', outputs[1])
            finally:
                if server.poll() is None:
                    server.terminate()
                    server.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
