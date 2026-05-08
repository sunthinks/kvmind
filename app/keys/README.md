# kdkvm/app/keys

Public trust roots the device must carry. **Every file in this directory is
public by design — commit freely.** Private counterparts live elsewhere and
are gitignored.

## myclaw_verify.pub

Ed25519 public key matching the kdcms MyClaw signing key
(`dev/kdcms/keys/myclaw_signing.key`). Deployed by `install.sh` step 3 to
`/etc/kdkvm/myclaw_verify.pub`; verified by `lib/myclaw_gateway.py` on every
signed action so the device refuses forged HID actions even if the local
LAN is compromised.

Rotation: a new release bumps this file and the kdcms signing key in
lockstep (deploy.sh regenerates both on a fresh `dev/kdcms/keys/` dir).
Old installs verify until they take the OTA that carries the new pub;
there is no flag-day.

## update-trust-YYYY.pub

Ed25519 public keys for OTA manifest signing. `release/build.sh` generates
the private counterpart under `dev/kdkvm/release/keys/update-trust-YYYY.key`
(gitignored, build-machine-only) on first run, writes the matching `.pub`
here, and signs `latest.json` with it. `install.sh` fans every
`update-trust-*.pub` into `/etc/kdkvm/update.pub.d/`; `kvmind-updater.sh`
then picks the correct one via `manifest.key_id` (see
`app/bin/kvmind-updater.sh` for the multi-key-id verification path).

Rotation: bump `--key-id update-trust-YYYY-N` on `build.sh`. The new
`.pub` is added alongside the existing ones, devices accept both during
the overlap window, then the old private key is destroyed and its `.pub`
is removed in a later release (the update.pub.d directory is additive —
install.sh never deletes pubs so rollback stays possible).
