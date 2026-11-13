"""成员 A 的临时实验客户端，不是 D/E 负责的正式客户端。"""

import argparse
import json
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol import decode_message, encode_message, extract_messages


def receive_replies(connection, expected_replies):
    buffer = bytearray()
    replies = 0
    while replies < expected_replies:
        chunk = connection.recv(1024)
        if not chunk:
            raise RuntimeError("服务器在回复完所有消息前关闭了连接")
        buffer.extend(chunk)
        for frame in extract_messages(buffer):
            message = decode_message(frame)
            text = json.dumps(message, ensure_ascii=False)
            if message.get("type") == "event":
                print(f"收到事件：{text}")
            elif message.get("type") == "response":
                label = "收到响应" if message.get("ok") else "收到失败"
                print(f"{label}：{text}")
                replies += 1
            else:
                raise RuntimeError(f"未知的服务器消息类型：{message.get('type')}")


def main():
    parser = argparse.ArgumentParser(description="阶段 8：发送请求，区分回复和主动事件")
    parser.add_argument("--server", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--message", action="append")
    parser.add_argument("--send-malformed", action="store_true")
    args = parser.parse_args()

    with socket.create_connection((args.server, args.port), timeout=5) as connection:
        messages = args.message or ["hello server", "second message"]
        payload = b"".join(
            encode_message({"type": "echo", "request_id": index, "text": message})
            for index, message in enumerate(messages, start=1)
        )
        if args.send_malformed:
            payload += b"{bad json}\n"

        for index, message in enumerate(messages, start=1):
            print(f"发出请求：{{'type': 'echo', 'request_id': {index}, 'text': {message!r}}}")
        connection.sendall(payload)
        receive_replies(connection, len(messages) + int(args.send_malformed))


if __name__ == "__main__":
    main()
