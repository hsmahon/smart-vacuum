"""Sign requests to the authorized Tuya cloud project."""
import hashlib
import hmac
import json
import time
import urllib.request
import uuid

ENDPOINTS = {
    "western-america": "https://openapi.tuyaus.com",
    "eastern-america": "https://openapi-ueaz.tuyaus.com",
}


def request(base_url, access_id, secret, path, payload=None, access_token=""):
    timestamp = str(time.time_ns() // 1_000_000)
    nonce = uuid.uuid4().hex
    method = "GET" if payload is None else "POST"
    body = b"" if payload is None else json.dumps(payload).encode()
    body_hash = hashlib.sha256(body).hexdigest()
    signature_input = f"{access_id}{access_token}{timestamp}{nonce}{method}\n{body_hash}\n\n{path}"
    signature = hmac.new(secret.encode(), signature_input.encode(), "sha256").hexdigest().upper()
    headers = {
        "client_id": access_id,
        "t": timestamp,
        "nonce": nonce,
        "sign_method": "HMAC-SHA256",
        "sign": signature,
    }
    if access_token:
        headers["access_token"] = access_token
    if payload is not None:
        headers["Content-Type"] = "application/json"

    call = urllib.request.Request(
        base_url + path, data=body if payload is not None else None,
        headers=headers, method=method,
    )
    with urllib.request.urlopen(call, timeout=15) as response:
        result = json.load(response)
    if not result.get("success"):
        raise RuntimeError(f"Tuya returned {result.get('code')}: {result.get('msg')}")
    return result["result"]
