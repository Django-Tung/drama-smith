"""`core/crypto.py` 单元测试:信封加解密往返、随机性、错 MEK / 篡改失败、脱敏边界(design D1 A2)。"""

from __future__ import annotations

import base64
import os

import pytest
from cryptography.exceptions import InvalidTag

from drama_smith.core.crypto import Envelope, decrypt, encrypt, mask_key

# 与 backend/.env 同源的 32B MEK(仅测试用,非生产凭证)。
_MEK = base64.b64decode("QWJbiPKm68kYceNBkZtXz5p60mbtF2LtZWE/B85+JxY=")


class TestEnvelope:
    def test_roundtrip(self) -> None:
        key = "sk-proj-abcdef1234567890XYZ"
        assert decrypt(encrypt(key, _MEK), _MEK) == key

    def test_each_encrypt_uses_fresh_dek_and_nonce(self) -> None:
        key = "sk-samekey-samekey-samekey-1234"
        a, b = encrypt(key, _MEK), encrypt(key, _MEK)
        # 随机 DEK + 两层随机 nonce:即便明文相同,两层 blob 也都不同。
        assert a.key_blob != b.key_blob
        assert a.dek_blob != b.dek_blob

    def test_different_plaintexts_produce_different_blobs(self) -> None:
        a = encrypt("sk-key-one-1234567890", _MEK)
        b = encrypt("sk-key-two-1234567890", _MEK)
        assert a.key_blob != b.key_blob

    def test_wrong_mek_fails(self) -> None:
        env = encrypt("sk-secret-1234567890", _MEK)
        with pytest.raises(InvalidTag):
            decrypt(env, os.urandom(32))

    def test_tampered_ciphertext_fails(self) -> None:
        env = encrypt("sk-secret-1234567890", _MEK)
        tampered = Envelope(
            key_blob=bytes([env.key_blob[0] ^ 1]) + env.key_blob[1:],
            dek_blob=env.dek_blob,
        )
        with pytest.raises(InvalidTag):
            decrypt(tampered, _MEK)

    def test_plaintext_not_in_ciphertext(self) -> None:
        # GCM 密文不含明文连续子串;dek_blob 是加密后的 DEK,与明文无关,故只断言 key_blob。
        plaintext = "sk-proj-supersecretkey-1234567890abcdef"
        env = encrypt(plaintext, _MEK)
        assert plaintext.encode() not in env.key_blob
        assert decrypt(env, _MEK) == plaintext


class TestMaskKey:
    def test_normal(self) -> None:
        assert mask_key("sk-proj-1234567890abcd") == "sk-…abcd"

    def test_empty_and_short_fully_masked(self) -> None:
        assert mask_key("") == "…"
        assert mask_key("sk-123") == "…"

    def test_boundary_seven_reveals_nothing_full(self) -> None:
        # 7 位:首 3 + 末 4 会拼出全串 → 回退 …,避免泄露。
        assert mask_key("1234567") == "…"

    def test_boundary_eight_hides_one(self) -> None:
        # 8 位:露首 3 末 4,藏中间 1 位。
        assert mask_key("12345678") == "123…5678"
