# GitHub Actions APK build setup

The `Test` branch already contains the published 0.2 Hotfix 2 public source layout:
`modifications/v0.2/`, `assets/`, `docs/`, `notices/` and `verification/`.
Do not nest or duplicate these directories: the build driver expects their paths from
the repository root.

The workflow at `.github/workflows/build-apk.yml` runs on every push to `Test`
and can also be started manually. It uses `modifications/v0.2/build.py`, downloads
the pinned public toolchain, verifies its hashes, runs the prepackage checks and
uploads the resulting APK as a GitHub Actions artifact.

## Required base APK secret

Add this repository Actions secret:

- `XHYN_BASE_APK_URL`: a private/direct download URL for the exact original XHYN V
  1.7.26 APK. The build driver accepts only SHA-256
  `da730ee5b153cdf9a162d2dacd7bec45f0bf8a143f928a29d359c5c97ae51191`.

A same-version download with a different hash will be rejected. Do not upload a
proprietary APK or game data into this public repository. Use a source you are
authorized to access and a URL that GitHub Actions can download without exposing
credentials in logs.

## Optional signing secrets

Without signing secrets, the workflow produces an **unsigned APK artifact**.
Android normally will not install an unsigned APK. To produce a signed APK, add
all three secrets:

- `XHYN_SIGNING_KEY_BASE64`: base64 encoding of the release PKCS#12 keystore.
- `XHYN_SIGNING_KEY_ALIAS`: alias inside that keystore.
- `XHYN_SIGNING_PASSWORD`: keystore/key password expected by apksigner.

For an update over an existing installation, the keystore must match the signing
certificate already used by that installed app. A newly generated key will not
match the existing release certificate. Never commit the keystore or password to
the repository.

## Artifact and limitations

After a successful run, open **Actions → the completed build run → Artifacts** and
download `XHYN-V-0.2-Hotfix2-APK`. Build reports are uploaded separately.

A successful host build is not proof of gameplay, Vulkan rendering or device
compatibility. Physical-device testing is still required. The workflow cannot
build until the exact original base APK secret is configured.
