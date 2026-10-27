r'''
Author: SimonChen62 430395359@qq.com
Date: 2026-10-27 01:28:20
LastEditors: SimonChen62 430395359@qq.com
LastEditTime: 2026-10-27 22:17:14
FilePath: \Codes\protocol.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''


import json


MAX_MESSAGE_BYTES = 64 * 1024


class ProtocolError(ValueError):
    """not utf-8 json format"""

# messgaetoolagr extends protocal
class MessageTooLarge(ProtocolError):
    """number of bytes exceed restriction"""

# description: a func to split the message according to b'\n', and keep the remaining part, one message should not >= 64kb
# keep the remaining part in original buffer
# param {bytearray} buffer
# return {*}
def extract_messages(buffer: bytearray) -> list[bytes]:
    messages = []
    while True:
        # find split position
        newline = buffer.find(b"\n")
        if newline == -1:
            if len(buffer) > MAX_MESSAGE_BYTES:
                raise MessageTooLarge("message exceeds 64 KB")
            return messages
        if newline > MAX_MESSAGE_BYTES:
            raise MessageTooLarge("message exceeds 64 KB")
        messages.append(bytes(buffer[:newline]))
        del buffer[:newline + 1]

'''
description: get the error dic info, transfer to json
param {dict} message
param {*} object
return {*}
'''
def encode_message(message: dict[str, object]) -> bytes:
    try:
        # turn to json, payload cont
        payload = json.dumps(
            message,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ProtocolError(f"cannot encode message: {exc}") from exc
    if len(payload) > MAX_MESSAGE_BYTES:
        raise MessageTooLarge("message exceeds 64 KB")
    return payload + b"\n"


'''
description: successfully get, decode, json to dict
param {bytes} payload
return {*}
'''
def decode_message(payload: bytes) -> dict[str, object]:
    if len(payload) > MAX_MESSAGE_BYTES:
        raise MessageTooLarge("message exceeds 64 KB")
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"invalid JSON message: {exc}") from exc
    if not isinstance(message, dict):
        raise ProtocolError("message must be a JSON object")
    return message
