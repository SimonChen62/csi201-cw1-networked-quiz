"""阶段 9：网络发送失败关闭连接，并通过统一出口通知业务层。"""

import argparse
import signal
import socket
import threading

from server_modules.lobby import Lobby

from protocol import (
    MessageTooLarge,
    ProtocolError,
    decode_message,
    encode_message,
    extract_messages,
)


def failure_response(request_id, code, message):
    """失败与成功同构：都是 response，只有 ok 为假并带 error。"""
    return {
        "type": "response",
        "request_id": request_id,
        "ok": False,
        "error": {"code": code, "message": message},
    }


class ClientSession:
    def __init__(self, connection, address):
        self.connection = connection
        self.address = address
        # Serialize writes to the same socket.
        self.send_lock = threading.Lock()

        # record whether the current session is running
        self.closed = threading.Event()
        self.close_lock = threading.Lock()

    def send(self, response):
        """Send a message through this session.

        Args:
            response: The message dictionary to send.

        Returns:
            True on success, False on encoding or network failure.
        """
        try:
            payload = encode_message(response)
        except ProtocolError as exc:
            print(f"无法编码响应：{exc}", flush=True)
            return False

        try:
            with self.send_lock:
                # should not send message when the socket is closing
                if self.closed.is_set():
                    return False
                self.connection.sendall(payload)
        except OSError as exc:
            print(f"发送响应失败：{exc}", flush=True)
            self.close()
            return False
        return True

    def close(self):
        """close need lock to avoid close in same time"""
        with self.close_lock:
            if self.closed.is_set():
                return
            self.closed.set()
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.connection.close()
            except OSError:
                pass

    def send_event(self, event, data):
        """Notify the client of an event, such as the end of a match."""
        return self.send({
            "type": "event",
            "event": event,
            "data": data,
        })


class Server:
    """Manage listening, client connections and shutdown."""

    def __init__(self, host, port, request_handler=None, on_disconnect=None,
                 question_bank=None):
        """Initialize server state; listener will hold the listening socket."""
        self.host = host
        self.port = port
        self.listener = None
        # Request handler provided by B/C; use echo by default.
        if request_handler is None:
            self.request_handler = self.handle_request
        else:
            self.request_handler = request_handler
        self.on_disconnect = on_disconnect
        self.question_bank = question_bank

        # Signal the server to stop.
        self.stop_event = threading.Event()

        self.sessions = set()
        self.client_threads = set()

        # Protect the session set from concurrent changes.
        self.sessions_lock = threading.Lock()

    def serve_forever(self):
        """Listen for connections and start a thread for each client."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            self.listener = listener
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, self.port))
            listener.listen()
            # accept() blocks; a timeout lets the loop check the stop flag.
            listener.settimeout(0.5)
            host, port = listener.getsockname()
            ready_message = "SERVER_READY" if self.question_bank is not None else "LAB_LISTENING"
            print(f"{ready_message} {host} {port}", flush=True)

            while not self.stop_event.is_set():
                try:
                    connection, address = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break

                # Wrap the accepted socket in a session object.
                # Bound a stalled peer's send/receive without an idle disconnect.
                connection.settimeout(1.0)
                session = ClientSession(connection, address)
                self.start_client(session)

    def start_client(self, session):
        """Register a session and track its worker thread until cleanup ends."""
        worker = threading.Thread(
            target=self.handle_client,
            args=(session,),
            daemon=True,
        )
        with self.sessions_lock:
            self.sessions.add(session)
            self.client_threads.add(worker)
        worker.start()
        return worker

    def handle_client(self, session):
        connection = session.connection
        try:
            print(f"客户端已连接：{session.address}", flush=True)
            buffer = bytearray()
            while not self.stop_event.is_set() and not session.closed.is_set():
                try:
                    chunk = connection.recv(1024)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buffer.extend(chunk)
                try:
                    frames = extract_messages(buffer)
                except MessageTooLarge as exc:
                    session.send(failure_response(None, "MESSAGE_TOO_LARGE", str(exc)))
                    break

                for frame in frames:
                    if self.stop_event.is_set() or session.closed.is_set():
                        return
                    response = self.process_frame(session, frame)
                    if not session.send(response):
                        if session.closed.is_set():
                            return
                        # encode wrong should not close socket
                        fallback = failure_response(None, "INTERNAL_ERROR", "cannot encode server response")
                        if not session.send(fallback):
                            return
        finally:
            session.close()
            with self.sessions_lock:
                was_registered = session in self.sessions
                self.sessions.discard(session)

            if was_registered and self.on_disconnect is not None:
                try:
                    self.on_disconnect(session)
                except Exception as exc:
                    print(f"业务断线清理失败：{exc}", flush=True)
            print(f"客户端已断开：{session.address}", flush=True)
            with self.sessions_lock:
                self.client_threads.discard(threading.current_thread())

    def process_frame(self, session, frame):
        """Decode a frame and return the request handler's response."""
        try:
            message = decode_message(frame)
        except ProtocolError as exc:
            return failure_response(None, "MALFORMED_MESSAGE", str(exc))

        return self.request_handler(session, message)

    # To be replaced by the B/C request handler.
    @staticmethod
    def handle_request(session, message):
        request_id = message.get("request_id")
        if message.get("type") != "echo":
            return failure_response(
                request_id, "UNKNOWN_COMMAND", str(message.get("type"))
            )
        if not isinstance(message.get("text"), str):
            return failure_response(
                request_id, "INVALID_MESSAGE", "text must be a string"
            )
        return {
            "type": "response",
            "request_id": request_id,
            "ok": True,
            "data": {"text": message["text"]},
        }

    def broadcast_event(self, targets, event, data):
        """Send an event to selected clients, such as a room update. record the failure sessions
        Returns:
            A list of sessions whose sends failed.
        """
        # Record failed sends.
        failed = []
        for session in targets:
            if not session.send_event(event, data):
                failed.append(session)
        return failed

    def request_shutdown(self, *_):
        self.stop_event.set()

    def shutdown(self):
        self.stop_event.set()
        if self.listener is not None:
            try:
                self.listener.close()
            except OSError:
                pass
        with self.sessions_lock:
            # Copy the sessions before closing their sockets. it may be changed, but close all of them is right
            sessions = list(self.sessions)
            workers = list(self.client_threads)
        for session in sessions:
            # Shut down both reading and writing, then close the socket.
            session.close()
        for worker in workers:
            if worker is not threading.current_thread():
                worker.join()


def main(argv=None, question_loader=None):
    parser = argparse.ArgumentParser(description="阶段 10：验证题库后启动 TCP 服务器")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--questions", help="题库 JSON 文件路径")
    mode.add_argument(
        "--lab-mode",
        action="store_true",
        help="运行不读取题库的 echo 教学服务器。",
    )
    args = parser.parse_args(argv)

    question_bank = None
    if not args.lab_mode:
        try:
            if question_loader is None:
                from server_modules.question_bank import load_question_bank

                question_loader = load_question_bank
            question_bank = question_loader(args.questions)
            if question_bank is None:
                raise ValueError("题库加载函数没有返回已验证的题库")
        except (ImportError, OSError, ValueError) as exc:
            print(f"题库加载或校验失败：{exc}", flush=True)
            return 1

    lobby = Lobby(question_bank) if question_bank is not None else None
    callbacks = {} if lobby is None else {
        "request_handler": lobby.handle_request,
        "on_disconnect": lobby.on_disconnect,
    }
    server = Server(args.host, args.port, question_bank=question_bank, **callbacks)
    # Request shutdown on Ctrl+C.
    signal.signal(signal.SIGINT, server.request_shutdown)
    try:
        server.serve_forever()
    finally:
        if lobby is not None:
            lobby.request_shutdown()
        server.shutdown()
        if lobby is not None:
            lobby.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
