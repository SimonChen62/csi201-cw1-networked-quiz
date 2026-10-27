"""阶段 6：多客户端、连接登记和可控关闭。"""

import argparse
import signal
import socket
import threading

from protocol import (
    MessageTooLarge,
    ProtocolError,
    decode_message,
    encode_message,
    extract_messages,
)


def error_response(request_id, code, message):
    return {
        "type": "error",
        "request_id": request_id,
        "error": {"code": code, "message": message},
    }


def send_response(connection, response):
    """编码并发送一条响应；编码或发送失败时返回 False。"""
    try:
        payload = encode_message(response)
    except ProtocolError as exc:
        print(f"无法编码响应：{exc}", flush=True)
        return False

    try:
        connection.sendall(payload)
    except OSError as exc:
        print(f"发送响应失败：{exc}", flush=True)
        return False
    return True

# server class, listen, create close
class Server:

    '''
    description:
    # listener is socket instance to listen port
    return {*}
    '''
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.listener = None
        # use for stopping listening
        self.stop_event = threading.Event()

        self.connections = set()

        # avoid modifing the set simultaneously
        self.connections_lock = threading.Lock()

    '''
    description: create listener
    param {*} self
    return {*}
    '''
    def serve_forever(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            self.listener = listener
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, self.port))
            listener.listen()
            # set block time, accept() is sync/block, if timeout >settimeout, it raise exception and continue again (test whether stop)
            listener.settimeout(0.5)
            host, port = listener.getsockname()
            print(f"LAB_LISTENING {host} {port}", flush=True)

            while not self.stop_event.is_set():
                try:
                    connection, address = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break

                with self.connections_lock:
                    self.connections.add(connection)
                threading.Thread(
                    target=self.handle_client,
                    args=(connection, address),
                    daemon=True,
                ).start()

    def handle_client(self, connection, address):
        try:
            with connection:
                print(f"客户端已连接：{address}", flush=True)
                buffer = bytearray()
                while not self.stop_event.is_set():
                    try:
                        chunk = connection.recv(1024)
                    except OSError:
                        break
                    if not chunk:
                        break
                    buffer.extend(chunk)
                    try:
                        frames = extract_messages(buffer)
                    except MessageTooLarge as exc:
                        send_response(
                            connection,
                            error_response(None, "MESSAGE_TOO_LARGE", str(exc)),
                        )
                        break

                    for frame in frames:
                        response = Server.make_response(frame)
                        if not send_response(connection, response):
                            return
                print("客户端已断开，本次连接结束。", flush=True)
        finally:
            with self.connections_lock:
                self.connections.discard(connection)

    '''
    description: make response
    return {*}
    '''
    @staticmethod
    def make_response(frame):
        try:
            message = decode_message(frame)
        except ProtocolError as exc:
            return error_response(None, "MALFORMED_MESSAGE", str(exc))

        request_id = message.get("request_id")
        if message.get("type") != "echo":
            return error_response(
                request_id, "UNKNOWN_COMMAND", str(message.get("type"))
            )
        if not isinstance(message.get("text"), str):
            return error_response(
                request_id, "INVALID_MESSAGE", "text must be a string"
            )
        return {
            "type": "response",
            "request_id": request_id,
            "ok": True,
            "data": {"text": message["text"]},
        }

    def shutdown(self, *_):
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        if self.listener is not None:
            try:
                self.listener.close()
            except OSError:
                pass
        with self.connections_lock:
            # make a copy
            connections = list(self.connections)
        for connection in connections:
            try:
                # close both read and write, in the tcp(transport layer)
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                connection.close()
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description="阶段 6：可控关闭的 TCP JSON 服务器")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    server = Server(args.host, args.port)
    # ctrl c stop
    signal.signal(signal.SIGINT, server.shutdown)
    try:
        server.serve_forever()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
