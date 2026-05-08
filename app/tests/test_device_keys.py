"""Tests for lib/device_keys.py — Ed25519 keypair generation, signing headers.

The core contract we need to preserve across kdkvm edits:

  1. ``ensure_keypair`` generates a fresh Ed25519 keypair on first call and
     loads the same one thereafter. Without this the device would drift
     identity every restart and kdcms would see an unknown pubkey on every
     heartbeat — immediate 401 cascade.
  2. ``sign_request`` produces bytes that kdcms's
     :class:`DeviceSignatureVerifier#buildSignedString` reconstructs
     byte-identically. The pytest here doesn't run the Java side, but we
     assert the signed-string format directly so drift from the kdcms
     regex gets caught at kdkvm PR time.
  3. ``delete_keypair`` wipes both files + the in-process cache, so the
     next ``ensure_keypair`` call genuinely generates a new pair.
"""
from __future__ import annotations

import base64
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from lib import device_keys as dk


@pytest.fixture
def tmp_keypair_paths(tmp_path, monkeypatch):
    """Redirect the keypair onto a writable tmp location + reset the in-mem cache."""
    key = tmp_path / "device_ed25519.key"
    pub = tmp_path / "device_ed25519.pub"
    monkeypatch.setattr(dk, "KEY_PATH", str(key))
    monkeypatch.setattr(dk, "PUB_PATH", str(pub))
    monkeypatch.setattr(dk, "_cached_sk", None)
    yield key, pub
    # Safety: drop the cache again so another test doesn't accidentally
    # inherit a key that points at a now-vanished tmp directory.
    monkeypatch.setattr(dk, "_cached_sk", None)


class TestEnsureKeypair:
    def test_first_call_creates_both_files(self, tmp_keypair_paths):
        key, pub = tmp_keypair_paths
        assert not key.exists()
        assert not pub.exists()

        sk = dk.ensure_keypair()

        assert isinstance(sk, Ed25519PrivateKey)
        assert key.exists()
        assert pub.exists()
        # Private key must be 0600 — leaking the private key file to every
        # local user would be a catastrophic downgrade from the in-process
        # memory protection the OS already provides.
        assert (os.stat(str(key)).st_mode & 0o777) == 0o600

    def test_second_call_returns_same_key(self, tmp_keypair_paths):
        """Caching the key across calls prevents a generate/reload per request."""
        sk1 = dk.ensure_keypair()
        sk2 = dk.ensure_keypair()
        # The in-memory instance must be identical — otherwise each call
        # would pay the PEM parse cost per heartbeat.
        assert sk1 is sk2

    def test_pub_file_regenerated_if_missing(self, tmp_keypair_paths):
        """Losing the .pub file (e.g. accidental delete) must not break signing."""
        key, pub = tmp_keypair_paths
        dk.ensure_keypair()
        pub.unlink()
        # Reset cache so the reload path actually runs.
        dk._cached_sk = None
        dk.ensure_keypair()
        assert pub.exists()

    def test_corrupt_key_regenerates(self, tmp_keypair_paths):
        """A truncated .key file must be replaced, not wedge the device."""
        key, pub = tmp_keypair_paths
        key.write_bytes(b"not a real pem")
        dk._cached_sk = None
        sk = dk.ensure_keypair()
        assert isinstance(sk, Ed25519PrivateKey)
        # The newly-written key must parse on the next load.
        dk._cached_sk = None
        sk2 = dk.ensure_keypair()
        # We don't compare sk == sk2 because Ed25519PrivateKey has no __eq__;
        # the byte-level round trip through the PEM is the actual check.
        from cryptography.hazmat.primitives import serialization as _s
        pem1 = sk.private_bytes(
            encoding=_s.Encoding.PEM, format=_s.PrivateFormat.PKCS8,
            encryption_algorithm=_s.NoEncryption(),
        )
        pem2 = sk2.private_bytes(
            encoding=_s.Encoding.PEM, format=_s.PrivateFormat.PKCS8,
            encryption_algorithm=_s.NoEncryption(),
        )
        assert pem1 == pem2


class TestPubkeyPem:
    def test_pem_is_valid_ed25519_pubkey(self, tmp_keypair_paths):
        pem = dk.pubkey_pem()
        assert "BEGIN PUBLIC KEY" in pem
        # Confirm round-trip through cryptography's loader — the exact same
        # thing kdcms does server-side before handing the pubkey to
        # Signature.verify.
        pk = load_pem_public_key(pem.encode("ascii"))
        assert pk is not None


class TestSignRequest:
    def test_signed_string_matches_kdcms_format(self, tmp_keypair_paths):
        """Plan §'签名规范': the string kdcms rebuilds must match byte-for-byte."""
        sk = dk.ensure_keypair()
        uid = "KVM-TEST-UID"
        body = b'{"foo":"bar"}'
        headers = dk.sign_request(sk, uid, "POST", "/api/myclaw/start", body,
                                  ts=1712345678, nonce="deadbeef")

        # The headers we emit must be the five kdcms reads from DeviceSigFilter.
        assert headers["X-Device-Uid"] == uid
        assert headers["X-Device-Ts"] == "1712345678"
        assert headers["X-Device-Nonce"] == "deadbeef"
        assert headers["X-Device-Sig-Version"] == "1"

        # Reconstruct the signed string the same way kdcms does.
        body_hash = hashlib.sha256(body).hexdigest()
        expected = (
            f"{uid}\n1712345678\ndeadbeef\n"
            f"POST\n/api/myclaw/start\n{body_hash}"
        )

        # Verify the signature ourselves using the device pubkey — proves
        # the signed string we would reproduce server-side is what the
        # private key actually signed.
        sig_bytes = base64.b64decode(headers["X-Device-Sig"])
        sk.public_key().verify(sig_bytes, expected.encode("utf-8"))

    def test_method_is_uppercased(self, tmp_keypair_paths):
        """kdcms always upcases method — we must too, or verify mismatches."""
        sk = dk.ensure_keypair()
        h_lower = dk.sign_request(sk, "u", "post", "/p", b"",
                                   ts=1, nonce="n")
        h_upper = dk.sign_request(sk, "u", "POST", "/p", b"",
                                   ts=1, nonce="n")
        assert h_lower["X-Device-Sig"] == h_upper["X-Device-Sig"]

    def test_empty_body_hashes_to_empty_sha256(self, tmp_keypair_paths):
        """GET-like requests with no body: kdcms hashes ``new byte[0]``."""
        sk = dk.ensure_keypair()
        headers = dk.sign_request(sk, "u", "POST", "/p", b"",
                                   ts=1, nonce="n")
        empty_hash = hashlib.sha256(b"").hexdigest()
        expected = f"u\n1\nn\nPOST\n/p\n{empty_hash}"
        sig_bytes = base64.b64decode(headers["X-Device-Sig"])
        sk.public_key().verify(sig_bytes, expected.encode("utf-8"))

    def test_nonce_is_random_when_absent(self, tmp_keypair_paths):
        """Nonce defaults must be high-entropy — a constant would enable replay."""
        sk = dk.ensure_keypair()
        h1 = dk.sign_request(sk, "u", "POST", "/p", b"", ts=1)
        h2 = dk.sign_request(sk, "u", "POST", "/p", b"", ts=1)
        assert h1["X-Device-Nonce"] != h2["X-Device-Nonce"]
        # 128 bits of hex = 32 chars — anything shorter is a bug.
        assert len(h1["X-Device-Nonce"]) >= 32

    def test_body_bytes_change_produces_different_sig(self, tmp_keypair_paths):
        sk = dk.ensure_keypair()
        h1 = dk.sign_request(sk, "u", "POST", "/p", b'{"x":1}',
                              ts=1, nonce="n")
        h2 = dk.sign_request(sk, "u", "POST", "/p", b'{"x":2}',
                              ts=1, nonce="n")
        assert h1["X-Device-Sig"] != h2["X-Device-Sig"]


class TestDeleteKeypair:
    def test_deletes_files_and_clears_cache(self, tmp_keypair_paths):
        key, pub = tmp_keypair_paths
        dk.ensure_keypair()
        assert key.exists() and pub.exists()

        dk.delete_keypair()
        assert not key.exists()
        assert not pub.exists()
        assert dk._cached_sk is None

    def test_delete_missing_is_noop(self, tmp_keypair_paths):
        # Delete-before-create must not explode — the CLI reset path may
        # run on a device that never finished first-boot generation.
        dk.delete_keypair()  # no files yet
        # And a fresh ensure_keypair after delete still works.
        sk = dk.ensure_keypair()
        assert isinstance(sk, Ed25519PrivateKey)
