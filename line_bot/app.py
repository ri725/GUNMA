from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, request

import logic

load_dotenv(Path(__file__).with_name(".env"))

app = Flask(__name__)


def _secret() -> str:
    return os.environ.get("LINE_CHANNEL_SECRET", "").strip()


def _token() -> str:
    return os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()


def _verified(body: bytes, signature: str) -> bool:
    secret = _secret()
    signature = signature.strip()
    if not secret or not signature:
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)


def _is_webhook_check(body: bytes) -> bool:
    try:
        data = json.loads(body.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    events = data.get("events") if isinstance(data, dict) else None
    return isinstance(events, list) and len(events) == 0


def _reply(token: str, message: dict) -> None:
    payload = json.dumps({"replyToken": token, "messages": [message]}).encode()
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/reply",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_token()}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        response.read()


@app.get("/health")
def health():
    return {"ok": True, "revision": "webhook-200"}


@app.post("/callback")
def callback():
    body = request.get_data()
    # LINEの「検証」は events が空。署名が無い、または未設定でも 200 を返す。
    if _is_webhook_check(body):
        return "OK", 200
    signature = request.headers.get("X-Line-Signature", "")
    if not _verified(body, signature):
        abort(400)
    data = json.loads(body.decode())
    for event in data.get("events", []):
        reply_token = event.get("replyToken")
        if not reply_token or reply_token == "00000000000000000000000000000000":
            continue
        message = None
        if event.get("type") == "message" and event.get("message", {}).get("type") == "text":
            message = logic.handle_text(event["message"].get("text", ""))
        elif event.get("type") == "postback":
            message = logic.handle_postback(event.get("postback", {}).get("data", ""))
        if message:
            _reply(reply_token, message)
    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
