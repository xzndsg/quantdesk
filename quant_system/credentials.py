from __future__ import annotations

import base64
import ctypes
import json
from ctypes import wintypes
from pathlib import Path


CREDENTIAL_PATH = Path.home() / ".quantdesk" / "deepseek.json"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _crypt(data: bytes, *, protect: bool) -> bytes:
    buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(
        len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))
    )
    output_blob = _DataBlob()
    function = (
        ctypes.windll.crypt32.CryptProtectData
        if protect
        else ctypes.windll.crypt32.CryptUnprotectData
    )
    function.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    function.restype = wintypes.BOOL
    succeeded = function(
        ctypes.byref(input_blob),
        "QuantDesk DeepSeek API Key" if protect else None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    if not succeeded:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


def save_api_key(api_key: str) -> None:
    cleaned_key = api_key.strip()
    if len(cleaned_key) < 5:
        raise ValueError("DeepSeek API Key 不能为空")
    encrypted = _crypt(cleaned_key.encode("utf-8"), protect=True)
    CREDENTIAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIAL_PATH.write_text(
        json.dumps(
            {
                "version": 1,
                "protected_key": base64.b64encode(encrypted).decode("ascii"),
            }
        ),
        encoding="utf-8",
    )


def load_api_key() -> str:
    try:
        payload = json.loads(CREDENTIAL_PATH.read_text(encoding="utf-8"))
        encrypted = base64.b64decode(payload["protected_key"], validate=True)
        return _crypt(encrypted, protect=False).decode("utf-8")
    except FileNotFoundError:
        return ""
    except Exception:
        # 凭据损坏时不阻断页面，用户可重新输入并覆盖保存。
        return ""
