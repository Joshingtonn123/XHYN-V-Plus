# Hotfix 2 incremental APK builds

The Test-branch workflow builds an APK from the verified public XHYN V 0.2 Hotfix 2 release, then overlays the current source from this repository. It does not feed the previous build back into the next run: every run downloads the same immutable Hotfix 2 base and applies the current commit's source once.

## What is rebuilt

- modifications/v0.2/java: compiled into a fresh helper DEX which replaces only Hotfix 2's dedicated classes7.dex helper layer.
- modifications/v0.2/native: rebuilds lib/arm64-v8a/libxhyn_v02.so with the pinned NDK.
- modifications/v0.2/assets: copied into the decoded APK as an overlay.
- modifications/v0.2/build-config.json: controls the launcher app name and displayed version. The workflow number is appended to the version and used to make Android versionCode increase on each build.

The builder validates the base APK SHA-256 and checks that Hotfix 2's classes7.dex contains only XHYN helper classes before replacing it. The other DEX files and original game/launcher libraries are not deliberately modified.

## Name and version

Edit modifications/v0.2/build-config.json. The current app_name is "XHYN V Plus", version_name is "0.2.1-dev", version_code_base is 200000, append_build_number is true, and package_name is null.

For example, run 12 produces app version 0.2.1-dev-build12 and a version code derived from 200000 + (12 * 100) + run_attempt. Set append_build_number to false to keep the displayed version name exact while the numeric Android version code still advances. package_name null preserves the Hotfix 2 app ID; set a valid Android application ID only when intentionally changing the app ID.

## One-time signing setup (Android-friendly)

The signing key must stay identical across all future builds. Do not generate a new key for each APK.

1. In the repository, open Settings → Secrets and variables → Actions → New repository secret.
2. Create the secret named XHYN_SIGNING_PASSWORD. Use a strong password of at least 20 characters, and save it privately. Do not put the password in a commit, issue, workflow input, or chat.
3. Open Actions → "Generate XHYN V Plus signing keystore" → Run workflow on branch Test.
4. When the run finishes, open it and download the artifact named XHYNVPLUS-signing-keystore. It contains xhynvplus.p12, encrypted with the password from step 2.
5. Extract the ZIP on your phone. In the repository's Test branch, use Add file → Upload files to upload xhynvplus.p12 into a folder named signing, so the final path is signing/xhynvplus.p12. Commit that file to Test.
6. Keep the XHYN_SIGNING_PASSWORD secret and signing/xhynvplus.p12 unchanged for every future build.

The .p12 file is password-protected, but it is still sensitive signing material. Use a long, unique password; do not share it. If the repository is public, anyone can download the encrypted file and attempt offline password guesses, so a high-entropy password is essential. Consider making the repository private. Never upload an unencrypted keystore.

The generated keystore uses PKCS#12, RSA 3072, and alias XHYNVPLUS. The app's displayed name is controlled separately by build-config.json.

## What is not rerun

Hotfix 2 already contains the original 0.2 native-language, UI and runtime integration patches. Those original-base patch scripts (patch_native_english.py, patch_native_guards.py, apply_ui_english.py and apply_runtime.py) are intentionally not rerun on Hotfix 2: they are not designed to patch an already-patched APK. New ongoing helper behavior should be implemented in the Java/native source layers listed above. Changes requiring edits to original launcher/game smali need a separate Hotfix 2-aware overlay patch and should not be added to those original-base scripts.

## Output

A successful commit to Test creates a newly rebuilt and signed APK plus SHA256SUMS.txt as a GitHub Actions artifact. It is not a renamed copy of Hotfix 2. APK artifacts are retained for 14 days.
