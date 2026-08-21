# Partner health steward Linux deployment

This package installs only the `partner` Hermes profile and the health sidecar. It never
starts services during `install`; production cut-over belongs to Ticket 15 and requires a
separate approval.

The staged partner unit declares a `0700` `/run/partner-health-steward-export` runtime
directory for owner JSON exports. The application verifies that it is Linux tmpfs before
writing a `0600` file, removes that file after the send attempt, and the enabled hourly cleanup
timer (`Persistent=true`) sweeps orphaned export files before the 24-hour upper boundary; tmpfiles is a
second cleanup layer. This is a release contract, not evidence that a live
host has been deployed or that a delivered Weixin copy can be recalled.

## Ticket 23 hard No-Go

Do **not** run the Ticket 23 install/start commands below for scheduled health
Jobs. The pinned, unmodified Hermes scheduler has no supported, unforgeable
per-execution Job identity available to the pre-run script or plugin. The
research mirror's identity injection is an uncommitted core modification; a
same-UID HMAC proof cannot distinguish a valid native Job from another Cron or
plugin. The commands remain draft deployment material only until an upstream
identity contract is pinned, or the no-core-patch condition is explicitly
re-scoped with a reviewed OS-isolation design.

## Required operator inputs

- `release-id`: immutable identifier for one allow-listed release. Reusing an identifier
  with different bytes fails closed.
- `receipt-public-key`: raw 32-byte Ed25519 public key used by the sidecar to verify inbound
  gateway receipts. The signing private key is not copied into the sidecar.
- `sidecar-python`: absolute Python interpreter containing `cryptography` for the sidecar.
- `hermes-python`: absolute Python interpreter used by the installed Hermes runtime.
- `partner-exec-start`: existing partner gateway command, migrated unchanged except for the
  restricted service account and `HERMES_HOME`.
- `expected-owner-sender-id`: the authenticated Weixin sender ID that owns the health profile.
- `expected-viewer-sender-id`: the only sender ID eligible for a read-only grant. It must be
  different from the owner ID; Linux administrator identity grants neither role.
- `health-model-config`: a five-field, non-secret health-model snapshot (`provider`, HTTPS
  `endpoint`, `model_id`, `privacy_mode`, and `auth_profile`). The installer copies the same
  bytes into the partner and sidecar configuration trees so the two fixed Jobs and the
  sidecar dispatcher bind to one explicit model recipient. Its `auth_profile` must be
  `partner`, the only profile permitted to load the partner-only plugin.
- The 04:00 native Job carries only an opaque one-time capability. After that capability is
  verified, the sidecar reloads the authoritative snapshot and makes the pinned fresh daily
  model call using its own restricted credential; no health snapshot is put into the outer
  Hermes agent context. A model or source failure is persisted content-free. The sidecar may
  make exactly one recovery attempt only in the tightly bounded `+10 minute` window (with one
  minute of clock-skew grace) and only after a newly verified daily/dispatcher Job action has
  renewed its short Gateway lease. A sidecar restart restores pending state but never runs a
  health-model retry by itself while the Gateway or host is unavailable; no third native Cron
  Job is created.
- During install, a random 32-byte-or-longer Job-action delegation key is created under the
  partner private home and copied as a separate `0400` sidecar-owned file. The plugin consumes
  the scheduler capability first, then uses that key to issue a short-lived, one-time proof for
  the sidecar. The sidecar consumes the proof nonce durably before it runs daily review or
  dispatch. This key is not health data, is never put in a prompt or ordinary chat configuration,
  and is distinct from the health-data, model, and inbound-receipt keys.
- `health-source-catalog`: the partner-facing keyword-to-exact-HTTPS source catalog.
- `sidecar-source-metadata`: sidecar-owned exact-URL metadata for downloads. It contains the
  type, title, bounded excerpt, and six required tag categories for each approved URL; an
  unlisted URL or redirect is refused.
- `sidecar-health-model-api-key` and `sidecar-weixin-token`: separate `0600` input files. They
  are copied only to `/etc/health-sidecar/` as `0400` sidecar-owned files and never appear in
  `partner.env`, the partner home, manifests, or evidence.
- `receipt-signer-socket`: the pre-existing, gateway-only Unix socket used by the partner
  ingress control path; this deployment does not create a signer service.
- `hermes-source-root` and `accepted-hermes-version`: the approved Hermes installation root and
  exact runtime version used for the iLink delivery surface. Ticket 14/15 must still verify the
  actual host's pin and clean-core status before any canary.
- `weixin-base-url` and `weixin-cdn-base-url`: the explicitly approved HTTPS iLink endpoints.

The partner plugin makes the effective Weixin DM allowlist exactly these owner and viewer
sender IDs, overriding a migrated profile's older `dm_policy/allow_from` values. This keeps
the configured viewer reachable while preventing an administrator or historic viewer from
reaching the private control handler.

## Operation order

Run every command as root on a non-production Linux host, from the release source directory.
The common arguments shown below are required for every action:

```text
python scripts/deploy_health_steward.py preflight \
  --source-root /path/to/partner-health-steward \
  --release-id 2026.08.09.1 \
  --receipt-public-key /secure/input/receipt-public.key \
  --sidecar-python /usr/local/lib/hermes-agent/venv/bin/python \
  --hermes-python /usr/local/lib/hermes-agent/venv/bin/python \
  --expected-owner-sender-id '<owner-weixin-sender-id>' \
  --expected-viewer-sender-id '<viewer-weixin-sender-id>' \
  --health-model-config /secure/input/health-model.json \
  --health-source-catalog /secure/input/health-source-catalog.json \
  --sidecar-source-metadata /secure/input/sidecar-source-metadata.json \
  --sidecar-health-model-api-key /secure/input/sidecar-health-model.key \
  --sidecar-weixin-token /secure/input/sidecar-weixin.token \
  --receipt-signer-socket /run/partner-health-steward/receipt-signer.sock \
  --hermes-source-root /opt/hermes-agent \
  --accepted-hermes-version '<accepted-hermes-version>' \
  --weixin-base-url 'https://approved-weixin-endpoint.example/api' \
  --weixin-cdn-base-url 'https://approved-weixin-cdn.example' \
  --partner-exec-start '/usr/local/lib/hermes-agent/venv/bin/python -m hermes_cli.main --profile partner gateway run'
```

1. `preflight` is read-only and validates the exact partner source, key type, release assets,
   and absolute runtime commands.
2. `install` creates the two restricted accounts, stages an immutable allow-listed release,
   copies only `/root/.hermes/profiles/partner` to the restricted home, writes two systemd
   units, installs exactly the two managed Jobs, and does not start either service.
3. `verify-static` checks release hashes and the account/file/unit isolation contract.
4. `start` is for an already-approved non-production cut-over. It starts sidecar before the
   restricted partner gateway; it does not stop or change default Hermes.
5. `verify-runtime` checks process accounts, socket owner/group/mode, direct file denial,
   absence of a sidecar TCP listener, and exactly two conforming health Jobs.
6. `upgrade` stages a new immutable release and preserves encrypted state and key paths.
   `rollback` switches to the previous manifest and reinstalls only its partner plugin/scripts.
7. `restore --backup-name NAME` accepts only a basename inside the sidecar backup directory,
   rejects plaintext SQLite, keeps an encrypted pre-restore copy, and restarts in sidecar-first
   order.
8. Run `python scripts/verify_health_steward_lifecycle.py`. It uses an isolated temporary
   store to prove encrypted backup restore, immediate profile-key destruction, backup
   undecryptability, and physical deletion at day 30 without reading live health content.
   The scheduled daily review also runs the same 30-day encrypted-backup purge and records only
   metadata counts, so retention is enforced during normal operation rather than only by a manual check.
9. After the next scheduled 04:00 owner-time daily review has completed, run the fixed
   `scripts/linux_health_smoke_wizard.sh` from the active immutable release as root. It first performs
   runtime isolation checks and records metadata-only evidence, verifies the current day's daily Job, fresh Hermes
   session, and sidecar audit path, then asks for confirmation before triggering the
   dispatcher once. It does not install, edit configuration, or bypass the daily-review
   time contract.

Operation evidence is JSON under `/var/lib/partner-health-steward/evidence`. It contains only
action, result, release identifier, UTC time, and boolean checks. Secrets, message text,
profile content, key bytes, and command output are never copied into evidence.
