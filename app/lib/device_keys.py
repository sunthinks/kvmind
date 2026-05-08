"""
V6 device Ed25519 keypair — the device's permanent identity on kdcms.

Replaces the V5 OAuth Bearer JWT scheme. Every request kdkvm sends to kdcms
is now signed with this private key; kdcms verifies against the pubkey it
recorded at :func:`bootstrap.ensure_bootstrapped` time.

**Why Ed25519** (vs HMAC / RSA):
  * Public-key: kdcms owns only the pubkey, so a DB leak does not forge
    device identity. HMAC requires the server to hold the secret.
  * Compact signatures (64 bytes) and ~50 μs verify keep the heartbeat /
    MyClaw hot path cheap.

**Why /etc/kdkvm/**:
  * Same directory as ``device.uid`` — one "device identity" concept, one
    place. Survives OTA of the read-only root partition.
  * ``remount_rw`` helper already exists, so the write path doesn't need a
    new platform integration.

Files:
  * ``/etc/kdkvm/device_ed25519.key`` — PKCS8 PEM private key, mode 0600.
  * ``/etc/kdkvm/device_ed25519.pub`` — X.509 SubjectPublicKeyInfo PEM, 0644.

Signed-string format (**strictly byte-equal with kdcms**
:class:`DeviceSignatureVerifier#buildSignedString`):
::

    uid + "\n" + ts + "\n" + nonce + "\n" + METHOD + "\n" + path + "\n" + sha256_hex(body_bytes)

Headers produced:
  * ``X-Device-Uid`` — device UID
  * ``X-Device-Ts`` — unix seconds
  * ``X-Device-Nonce`` — 128-bit hex random, single-use
  * ``X-Device-Sig`` — base64 Ed25519 signature
  * ``X-Device-Sig-Version`` — always ``1`` today
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .remount import remount_rw

log = logging.getLogger(__name__)

KEY_PATH = os.environ.get("KVMIND_DEVICE_KEY_PATH", "/etc/kdkvm/device_ed25519.key")
PUB_PATH = os.environ.get("KVMIND_DEVICE_PUB_PATH", "/etc/kdkvm/device_ed25519.pub")

SIG_VERSION = "1"

# In-process cache for the loaded private key. The disk file is small but
# every MyClaw / heartbeat call wants to sign, and parsing PEM on every
# request is wasted CPU. Guarded by a lock so first-boot generation doesn't
# race between the heartbeat startup tick and the MyClaw first-call.
_cached_sk: Optional[Ed25519PrivateKey] = None
_cached_sk_lock = threading.Lock()


def ensure_keypair() -> Ed25519PrivateKey:
    """Load the device keypair, generating it on first boot if absent.

    Idempotent and safe to call from multiple places during startup. On
    first boot both files are created atomically: we write the .key file
    first (0600, primary artifact) and only then the .pub file (0644,
    derived). If anything fails mid-way, the next call reads whichever
    artifact exists and — if they don't match — regenerates both.

    Returns the ``Ed25519PrivateKey`` instance; callers normally don't
    need the object because :func:`sign_request` reads the cache.
    """
    global _cached_sk
    with _cached_sk_lock:
        if _cached_sk is not None:
            return _cached_sk

        key_p = Path(KEY_PATH)
        pub_p = Path(PUB_PATH)

        if key_p.exists():
            try:
                sk = _load_private_key(key_p)
                # Refresh the pub file if missing or out-of-sync (e.g. someone
                # deleted it). The source of truth is the private key, which
                # uniquely determines the public key.
                expected_pub = _public_pem(sk.public_key())
                current_pub = pub_p.read_text() if pub_p.exists() else ""
                if current_pub.strip() != expected_pub.strip():
                    _write_pub(pub_p, expected_pub)
                _cached_sk = sk
                return sk
            except Exception as e:
                # Corrupt key → regenerate. Leaving a truncated file here
                # would wedge the device permanently since every bootstrap
                # attempt would fail to parse.
                log.warning("[device_keys] failed to load %s (%s), regenerating", key_p, e)

        sk = Ed25519PrivateKey.generate()
        _write_private_key(key_p, sk)
        _write_pub(pub_p, _public_pem(sk.public_key()))
        log.info("[device_keys] generated new Ed25519 keypair at %s", key_p)
        _cached_sk = sk
        return sk


def load_signing_key() -> Ed25519PrivateKey:
    """Return the in-process signing key, loading on first call.

    Thin alias for :func:`ensure_keypair` kept separate so call sites that
    only need to sign (not create) read more clearly at the caller.
    """
    return ensure_keypair()


def pubkey_pem() -> str:
    """Return the Ed25519 public key as a PEM string.

    This is what kdkvm sends to kdcms at :func:`bootstrap.ensure_bootstrapped`
    — kdcms stores it verbatim in ``device_keys.public_key`` and passes it
    back into :class:`DeviceSignatureVerifier#loadEd25519PublicKey` per
    request. Must be valid PEM (``-----BEGIN PUBLIC KEY-----`` framed).
    """
    return _public_pem(ensure_keypair().public_key())


def delete_keypair() -> None:
    """Wipe the on-disk keypair + process cache. Used by ``kdkvm reset``.

    Next :func:`ensure_keypair` call will generate a fresh pair. The caller
    is responsible for also clearing ``kv.bootstrap_done`` so the new key
    gets re-registered with kdcms.
    """
    global _cached_sk
    with _cached_sk_lock:
        _cached_sk = None
        for p in (Path(KEY_PATH), Path(PUB_PATH)):
            if p.exists():
                with remount_rw(str(p)):
                    try:
                        p.unlink()
                    except OSError as e:
                        log.warning("[device_keys] failed to unlink %s: %s", p, e)


def sign_request(
    sk: Ed25519PrivateKey,
    uid: str,
    method: str,
    path: str,
    body_bytes: bytes,
    *,
    ts: Optional[int] = None,
    nonce: Optional[str] = None,
) -> dict[str, str]:
    """Build the five X-Device-* headers for a kdcms request.

    ``ts`` and ``nonce`` are parameters (not internal randoms) so tests can
    produce deterministic fixtures and so the same signature can be asserted
    against kdcms's :class:`DeviceSignatureVerifier` test expectations.

    ``path`` **must** be the URI path kdcms will read from
    ``HttpServletRequest.getRequestURI()`` — that is, the bare path with no
    scheme / host / query string (``/api/myclaw/start``, not the full URL).
    The signed string and kdcms's reconstructed string must match
    byte-for-byte or verify returns false.
    """
    ts_str = str(int(ts if ts is not None else time.time()))
    nonce_str = nonce if nonce is not None else secrets.token_hex(16)
    body_hash = hashlib.sha256(body_bytes or b"").hexdigest()
    signed_string = (
        f"{uid}\n{ts_str}\n{nonce_str}\n"
        f"{method.upper()}\n{path}\n{body_hash}"
    )
    sig = sk.sign(signed_string.encode("utf-8"))
    return {
        "X-Device-Uid": uid,
        "X-Device-Ts": ts_str,
        "X-Device-Nonce": nonce_str,
        "X-Device-Sig": base64.b64encode(sig).decode("ascii"),
        "X-Device-Sig-Version": SIG_VERSION,
    }


# ── internal helpers ──────────────────────────────────────────────────────


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    pem = path.read_bytes()
    sk = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(sk, Ed25519PrivateKey):
        raise ValueError(f"{path} is not an Ed25519 private key")
    return sk


def _write_private_key(path: Path, sk: Ed25519PrivateKey) -> None:
    pem = sk.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with remount_rw(str(path)):
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write+rename so a crash mid-write never leaves a partial key.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(pem)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)


def _write_pub(path: Path, pem: str) -> None:
    with remount_rw(str(path)):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(pem)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)


def _public_pem(pk: Ed25519PublicKey) -> str:
    pem = pk.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return pem.decode("ascii")


# ── R5-HB-01 (2026-04-26) Heartbeat 响应验签 ────────────────────────────────
# kdcms 在响应离开前对权益载荷做 Ed25519 签名（HeartbeatSigner.signInPlace），
# 设备端用 /etc/kdkvm/heartbeat_verify.pub 验签后才把 features 落到本地，
# 消除 kdcms / nginx 被攻陷后任意下发权益的纵深漏洞。
import json as _json  # 局部别名避免覆盖文件首部 import

HEARTBEAT_VERIFY_KEY_PATH = os.environ.get(
    "KVMIND_HEARTBEAT_VERIFY_KEY_PATH", "/etc/kdkvm/heartbeat_verify.pub"
)

_heartbeat_pub: Optional[Ed25519PublicKey] = None
_heartbeat_pub_lock = threading.Lock()


def _load_heartbeat_pub() -> Optional[Ed25519PublicKey]:
    """缓存式加载心跳验签公钥；缺失或损坏时返回 None 让上层降级处理。"""
    global _heartbeat_pub
    with _heartbeat_pub_lock:
        if _heartbeat_pub is not None:
            return _heartbeat_pub
        try:
            path = Path(HEARTBEAT_VERIFY_KEY_PATH)
            if not path.exists():
                return None
            pk = serialization.load_pem_public_key(path.read_bytes())
            if not isinstance(pk, Ed25519PublicKey):
                log.error("Heartbeat verify key at %s is not Ed25519", path)
                return None
            _heartbeat_pub = pk
            return pk
        except Exception as e:
            log.error("Failed to load heartbeat verify key %s: %s",
                      HEARTBEAT_VERIFY_KEY_PATH, e)
            return None


def verify_heartbeat_response(uid: str, data: dict) -> bool:
    """对 kdcms 心跳响应的 ``data`` 字段做 Ed25519 验签。

    返回 ``True`` 表示签名有效（或处于"旧 kdcms 不签"兼容期）；
    返回 ``False`` 表示签名存在但无效，调用方应拒绝把响应数据落地。

    签名 payload 形式（必须与 kdcms ``HeartbeatSigner.signInPlace`` 字节相等）::

        uid|signedAt|sha256(canonical_json(authoritative_fields))

    其中 ``authoritative_fields`` 是 8 个权威字段的字典，由 Python
    ``json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)``
    生成与 Jackson ``ORDER_MAP_ENTRIES_BY_KEYS`` 同款的规范化输出。
    """
    sig_b64 = data.get("signature")
    signed_at = data.get("signedAt")

    if not sig_b64 or not signed_at:
        # 兼容期：旧版 kdcms 不签 → 接受 + warn。kdcms 升级后此分支应不再触发，
        # 若一直触发说明部署链路出了问题，加 warn 让运维看见。
        log.warning(
            "[HeartbeatVerify] response missing signature/signedAt (kdcms not upgraded?)"
        )
        return True

    pub = _load_heartbeat_pub()
    if pub is None:
        # 公钥本应由 install.sh / OTA 包部署到 /etc/kdkvm/heartbeat_verify.pub。
        # 缺失说明部署不完整 —— 拒绝接受响应，强制运维补齐而不是默默放行。
        log.error(
            "[HeartbeatVerify] verify key %s missing — refusing signed response",
            HEARTBEAT_VERIFY_KEY_PATH,
        )
        return False

    if not isinstance(sig_b64, str) or not sig_b64.startswith("ed25519:"):
        log.warning("[HeartbeatVerify] unexpected signature format")
        return False
    try:
        sig_bytes = base64.b64decode(sig_b64[len("ed25519:"):])
    except Exception:
        log.warning("[HeartbeatVerify] signature base64 decode failed")
        return False

    # 字段集合必须与 kdcms HeartbeatSigner.authoritativeFields 一致。
    fields = {
        "claimState":             data.get("claimState"),
        "entitlementState":       data.get("entitlementState"),
        "assignedSubscriptionId": data.get("assignedSubscriptionId"),
        "features":               data.get("features"),
        "tunnelToken":            data.get("tunnelToken"),
        "tunnelId":               data.get("tunnelId"),
        "customerCleared":        data.get("customerCleared"),
        "deletionRequestId":      data.get("deletionRequestId"),
    }
    canonical = _json.dumps(
        fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    fields_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    payload = f"{uid}|{signed_at}|{fields_hash}".encode("utf-8")

    try:
        pub.verify(sig_bytes, payload)
        return True
    except Exception as e:
        log.warning("[HeartbeatVerify] Ed25519 verify failed: %s", e)
        return False
