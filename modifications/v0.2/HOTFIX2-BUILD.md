# Hotfix 2 incremental APK builds

The Test-branch workflow builds an APK from the verified public XHYN V 0.2 Hotfix 2 release, then overlays the current source from this repository. It does not feed the previous build back into the next run: every run downloads the same immutable Hotfix 2 base and applies the current commit's source once.

## What is rebuilt

- modifications/v0.2/java: compiled into a fresh helper DEX which replaces only Hotfix 2's dedicated classes7.dex helper layer.
- modifications/v0.2/native: rebuilds lib/arm64-v8a/libxhyn_v02.so with the pinned NDK.
- modifications/v0.2/assets: copied into the decoded APK as an overlay.
- modifications/v0.2/build-config.json: controls the launcher app name and displayed version. The workflow number is appended to the version and used to make Android versionCode increase on each build.

The builder validates the base APK SHA-256 and checks that Hotfix 2's classes7.dex contains only XHYN helper classes before replacing it. The other DEX files and original game/launcher libraries are not deliberately modified.

## Name and version

Edit modifications/v0.2/build-config.json. The defaults are app_name "XHYN V Reborn", version_name "0.2.1-dev", version_code_base 200000, append_build_number true, and package_name null.

For example, run 12 produces app version 0.2.1-dev-build12 and a version code derived from 200000 + (12 * 100) + run_attempt. Set append_build_number to false to keep the displayed version name exact while the numeric Android version code still advances. package_name null preserves the Hotfix 2 app ID; set a valid Android application ID only when intentionally changing the app ID.

## Signing requirement

Every modified APK must be signed. Configure these repository Actions secrets once:

- XHYN_SIGNING_KEY_BASE64: Base64-encoded PKCS#12 keystore file.
- XHYN_SIGNING_KEY_ALIAS: key alias inside that keystore.
- XHYN_SIGNING_PASSWORD: keystore/key password used by apksigner.

Keep using the same keystore for all future builds so Android accepts them as updates to your previous fork build. The private key is not stored in the repository or uploaded as an artifact. Because the fork cannot sign with the upstream release's private key, the first install of the fork may require uninstalling the upstream Hotfix 2 app first, especially when retaining its package ID. After that, keep the fork keystore unchanged.

## What is not rerun

Hotfix 2 already contains the original 0.2 native-language, UI and runtime integration patches. Those original-base patch scripts (patch_native_english.py, patch_native_guards.py, apply_ui_english.py and apply_runtime.py) are intentionally not rerun on Hotfix 2: they are not designed to patch an already-patched APK. New ongoing helper behavior should be implemented in the Java/native source layers listed above. Changes requiring edits to original launcher/game smali need a separate Hotfix 2-aware overlay patch and should not be added to those original-base scripts.

## Output

A successful commit to Test creates a newly rebuilt and signed APK plus SHA256SUMS.txt as a GitHub Actions artifact. It is not a renamed copy of Hotfix 2. Artifacts are retained for 14 days.
