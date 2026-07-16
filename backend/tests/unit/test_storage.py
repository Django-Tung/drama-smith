"""本地 FileStore 单测:落盘 / 读 / 删 + HS256 签名 URL 签发与校验(M3;design D2/D10)。

纯单测(无 DB):`LocalFileStore` 落 `tmp_path`,验证 user_id 路径隔离、save/read/delete 往返、
签名 URL 签发与校验(对 / 错 media_id、篡改 token、错 secret、过期均正确判真伪)+ URL 拼装格式。
"""

from __future__ import annotations

import time
from pathlib import Path

import jwt

from drama_smith.storage import LocalFileStore, build_signed_url


def test_save_read_delete_round_trip(tmp_path: Path) -> None:
    fs = LocalFileStore(tmp_path, "secret", 300)
    key = fs.save(user_id=7, data=b"\x89PNG hello", ext="png")
    # storage_key 含 user_id 分段 + 年月分桶 + uuid 文件名
    assert key.startswith("7/")
    assert key.endswith(".png")
    assert fs.read(key) == b"\x89PNG hello"
    fs.delete(key)
    fs.delete(key)  # best-effort:删不存在的 key 不报错


def test_save_path_user_isolation(tmp_path: Path) -> None:
    fs = LocalFileStore(tmp_path, "secret", 300)
    a = fs.save(user_id=1, data=b"a", ext="jpg")
    b = fs.save(user_id=2, data=b"b", ext="jpg")
    assert a.split("/")[0] == "1"
    assert b.split("/")[0] == "2"


def test_ensure_root_creates_dir(tmp_path: Path) -> None:
    root = tmp_path / "media"
    fs = LocalFileStore(root, "secret", 300)
    fs.ensure_root()
    assert root.is_dir()


def test_sign_verify_round_trip(tmp_path: Path) -> None:
    fs = LocalFileStore(tmp_path, "secret", 300)
    token, exp = fs.sign(42)
    assert isinstance(exp, int)
    assert fs.verify(token, 42) is True


def test_verify_rejects_wrong_media_id(tmp_path: Path) -> None:
    fs = LocalFileStore(tmp_path, "secret", 300)
    token, _ = fs.sign(42)
    assert fs.verify(token, 43) is False


def test_verify_rejects_tampered_token(tmp_path: Path) -> None:
    fs = LocalFileStore(tmp_path, "secret", 300)
    token, _ = fs.sign(42)
    assert fs.verify(token + "x", 42) is False


def test_verify_rejects_wrong_secret(tmp_path: Path) -> None:
    fs = LocalFileStore(tmp_path, "secret", 300)
    token, _ = fs.sign(42)
    other = LocalFileStore(tmp_path, "other-secret", 300)
    assert other.verify(token, 42) is False


def test_verify_rejects_expired(tmp_path: Path) -> None:
    fs = LocalFileStore(tmp_path, "secret", 300)
    past = int(time.time()) - 10
    expired = jwt.encode({"sub": "42", "exp": past}, "secret", algorithm="HS256")
    assert fs.verify(expired, 42) is False


def test_build_signed_url_format() -> None:
    url = build_signed_url(42, "tok", 1700000000)
    assert url == "/api/media/42/content?token=tok&exp=1700000000"
