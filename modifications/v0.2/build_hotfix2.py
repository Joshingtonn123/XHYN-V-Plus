#!/usr/bin/env python3
"""Incrementally rebuild XHYN V from the verified 0.2 Hotfix 2 APK.

Hotfix 2 already contains the original 0.2 UI/runtime/native patch layer.
This builder intentionally does not rerun those original-base patch scripts.
It replaces only the dedicated helper DEX, rebuilds the XHYN native helper,
overlays assets, updates app metadata, packages, signs, and checks the APK.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET

BASE_SHA256 = "e2f1862b6deaade281be2b0f5f9c7dbf604462c7dccf2b9b951977327b3518f8"
PACKAGE = Path(__file__).resolve().parent
REPOSITORY = PACKAGE.parents[1]
ANDROID_NS = "http://schemas.android.com/apk/res/android"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def uleb128(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if offset >= len(data) or shift > 28:
            raise ValueError("Invalid DEX ULEB128 value")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7


def dex_class_descriptors(data: bytes) -> list[str]:
    """Read DEX class definitions without requiring an external parser."""
    if len(data) < 0x70 or data[:4] != b"dex\n" or data[7] != 0:
        raise ValueError("Input is not a supported DEX file")
    strings_size, strings_off = struct.unpack_from("<II", data, 0x38)
    types_size, types_off = struct.unpack_from("<II", data, 0x40)
    class_size, class_off = struct.unpack_from("<II", data, 0x60)
    if strings_off + strings_size * 4 > len(data):
        raise ValueError("DEX string table is out of bounds")
    if types_off + types_size * 4 > len(data):
        raise ValueError("DEX type table is out of bounds")
    if class_off + class_size * 32 > len(data):
        raise ValueError("DEX class table is out of bounds")
    strings: list[str] = []
    for index in range(strings_size):
        string_off = struct.unpack_from("<I", data, strings_off + 4 * index)[0]
        _, pos = uleb128(data, string_off)
        end = data.find(b"\0", pos)
        if end < 0:
            raise ValueError("Unterminated DEX string")
        strings.append(data[pos:end].replace(b"\xc0\x80", b"\x00").decode("utf-8", "surrogatepass"))
    types: list[str] = []
    for index in range(types_size):
        descriptor_index = struct.unpack_from("<I", data, types_off + 4 * index)[0]
        if descriptor_index >= len(strings):
            raise ValueError("DEX type references an invalid string")
        types.append(strings[descriptor_index])
    classes: list[str] = []
    for index in range(class_size):
        type_index = struct.unpack_from("<I", data, class_off + 32 * index)[0]
        if type_index >= len(types):
            raise ValueError("DEX class references an invalid type")
        classes.append(types[type_index])
    if len(classes) != len(set(classes)):
        raise ValueError("Duplicate class definition in DEX")
    return classes


def load_config(path: Path, run_number: int, run_attempt: int) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    for key in ("app_name", "version_name", "version_code_base"):
        if not isinstance(config.get(key), (str, int)):
            raise ValueError("build-config.json must define app_name, version_name and version_code_base")
    app_name = str(config["app_name"]).strip()
    version_name = str(config["version_name"]).strip()
    if not app_name or not version_name:
        raise ValueError("app_name and version_name cannot be empty")
    version_code_base = int(config["version_code_base"])
    if version_code_base < 1:
        raise ValueError("version_code_base must be positive")
    version_code = version_code_base + run_number * 100 + run_attempt
    if version_code > 2_100_000_000:
        raise ValueError("Calculated Android versionCode is too large")
    actual_version = f"{version_name}-build{run_number}" if config.get("append_build_number", True) else version_name
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", app_name).strip("-._") or "XHYN-V"
    return {
        "app_name": app_name,
        "version_name": actual_version,
        "version_code": version_code,
        "package_name": config.get("package_name"),
        "apk_filename": f"{slug}-{actual_version}.apk",
    }


def update_manifest(decoded: Path, config: dict) -> None:
    ET.register_namespace("android", ANDROID_NS)
    manifest = decoded / "AndroidManifest.xml"
    tree = ET.parse(manifest)
    root = tree.getroot()
    root.set(f"{{{ANDROID_NS}}}versionCode", str(config["version_code"]))
    root.set(f"{{{ANDROID_NS}}}versionName", str(config["version_name"]))
    if config.get("package_name"):
        package_name = str(config["package_name"]).strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+", package_name):
            raise ValueError("package_name is not a valid Android application ID")
        root.set("package", package_name)
    app = root.find("application")
    if app is None:
        raise ValueError("AndroidManifest.xml has no application element")
    app.set(f"{{{ANDROID_NS}}}label", config["app_name"])
    tree.write(manifest, encoding="utf-8", xml_declaration=True)
    apktool_yml = decoded / "apktool.yml"
    text = apktool_yml.read_text(encoding="utf-8")
    text, code_count = re.subn(
        r"(?m)^([ \t]+versionCode:[ \t]*).*$",
        lambda match: match.group(1) + str(config["version_code"]), text,
    )
    text, name_count = re.subn(
        r"(?m)^([ \t]+versionName:[ \t]*).*$",
        lambda match: match.group(1) + json.dumps(config["version_name"]), text,
    )
    if code_count != 1 or name_count != 1:
        raise ValueError("Could not uniquely update versionCode/versionName in apktool.yml")
    apktool_yml.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-apk", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path, help="Fresh build directory; must not exist")
    parser.add_argument("--tools-dir", required=True, type=Path)
    parser.add_argument("--apktool", required=True, type=Path)
    parser.add_argument("--ndk-root", required=True, type=Path)
    parser.add_argument("--java-home", type=Path, help="JDK 17 home; otherwise use JAVA_HOME/PATH")
    parser.add_argument("--keystore", required=True, type=Path)
    parser.add_argument("--key-alias", required=True)
    parser.add_argument("--password-file", required=True, type=Path)
    args = parser.parse_args()
    original = args.input_apk.resolve(strict=True)
    tools = args.tools_dir.resolve(strict=True)
    apktool = args.apktool.resolve(strict=True)
    ndk = args.ndk_root.resolve(strict=True)
    keystore = args.keystore.resolve(strict=True)
    password_file = args.password_file.resolve(strict=True)
    work = args.work_dir.resolve()
    if work.exists():
        parser.error("work directory already exists; choose a fresh directory")
    if digest(original) != BASE_SHA256:
        parser.error("input APK is not the verified XHYN V 0.2 Hotfix 2 release")
    build_manifest = json.loads((REPOSITORY / "modifications/toolchain-manifest.json").read_text())
    if digest(apktool) != build_manifest["apktool"]["sha256"]:
        parser.error("Apktool checksum does not match the pinned repository manifest")
    android_tools = json.loads((REPOSITORY / "modifications/android-toolchain-manifest.json").read_text())
    for item in android_tools:
        path = tools / item["name"]
        if not path.is_file() or digest(path) != item["sha256"]:
            parser.error("missing or mismatching Android tool: " + item["name"])
    if "27.2.12479018" not in (ndk / "source.properties").read_text():
        parser.error("Use the pinned Android NDK r27c / 27.2.12479018")

    # Prove classes7.dex is the isolated helper layer before replacing it.
    with zipfile.ZipFile(original) as archive:
        names = set(archive.namelist())
        if "classes7.dex" not in names:
            parser.error("Hotfix 2 is missing its dedicated classes7.dex helper layer")
        base_classes = dex_class_descriptors(archive.read("classes7.dex"))
        if not base_classes or any(not name.startswith("Lcom/gtavsource/android/Xhyn") for name in base_classes):
            parser.error("classes7.dex contains non-XHYN classes; refusing to replace it")
        for dex_name in sorted(name for name in names if re.fullmatch(r"classes\d*\.dex", name) and name != "classes7.dex"):
            overlap = set(base_classes).intersection(dex_class_descriptors(archive.read(dex_name)))
            if overlap:
                parser.error("XHYN helper classes overlap another DEX: " + ", ".join(sorted(overlap)[:4]))
        if "lib/arm64-v8a/libxhyn_v02.so" not in names:
            parser.error("Hotfix 2 is missing libxhyn_v02.so")

    run_number = int(os.environ.get("GITHUB_RUN_NUMBER", "1"))
    run_attempt = int(os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
    if run_number < 1 or run_attempt < 1:
        parser.error("GitHub run number/attempt must be positive")
    build_config = load_config(PACKAGE / "build-config.json", run_number, run_attempt)
    env = os.environ.copy()
    java_home = args.java_home.resolve(strict=True) if args.java_home else Path(env.get("JAVA_HOME", "")).resolve() if env.get("JAVA_HOME") else None
    if java_home:
        env["JAVA_HOME"] = str(java_home)
        env["PATH"] = str(java_home / "bin") + os.pathsep + env["PATH"]
    java = shutil.which("java", path=env["PATH"])
    javac = shutil.which("javac", path=env["PATH"])
    if not java or not javac:
        parser.error("A complete JDK 17 is required")
    javac_version = subprocess.run([javac, "-version"], env=env, capture_output=True, text=True, check=True)
    if not re.search(r"javac 17(?:\.|\s|$)", javac_version.stdout + javac_version.stderr):
        parser.error("Use JDK 17 for the documented build")

    work.mkdir(parents=True)
    reports = work / "reports"
    reports.mkdir()
    env.update(XHYN_WORK_DIR=str(work), XHYN_REPO_ROOT=str(REPOSITORY),
               XHYN_INPUT_APK=str(original), XHYN_NDK_ROOT=str(ndk))
    logs = reports / "build-logs"
    logs.mkdir()

    def run(label: str, command: list[object]) -> str:
        print(label, flush=True)
        result = subprocess.run([str(part) for part in command], env=env, capture_output=True, text=True)
        output = result.stdout + result.stderr
        (logs / f"{label}.txt").write_text(output, encoding="utf-8")
        if result.returncode:
            print(output, file=sys.stderr)
            raise subprocess.CalledProcessError(result.returncode, command)
        return output

    decoded = work / "decoded"
    framework = work / "framework"
    run("decode-hotfix2", [java, "-jar", apktool, "d", original, "-o", decoded, "-p", framework])
    existing_smali = decoded / "smali_classes7"
    if not existing_smali.is_dir():
        raise ValueError("Apktool did not decode classes7.dex into smali_classes7")
    shutil.rmtree(existing_smali)

    classes = work / "build/classes"
    stubs = work / "build/stubs"
    dex_dir = work / "build/dex"
    smali_out = work / "build/helper-smali"
    for directory in (classes, stubs, dex_dir):
        directory.mkdir(parents=True)
    android_jar = tools / "android.jar"
    stub_sources = sorted((PACKAGE / "stubs").rglob("*.java"))
    helper_sources = sorted((PACKAGE / "java").rglob("*.java"))
    if not helper_sources:
        raise ValueError("No XHYN Java helper sources were found")
    run("compile-interfaces", [javac, "--release", "8", "-encoding", "UTF-8", "-cp", android_jar, "-d", stubs, *stub_sources])
    run("compile-helpers", [javac, "--release", "8", "-encoding", "UTF-8", "-cp", str(android_jar) + os.pathsep + str(stubs), "-d", classes, *helper_sources])
    run("dex-helpers", [java, "-cp", tools / "r8.jar", "com.android.tools.r8.D8", "--min-api", "30", "--release", "--lib", android_jar, "--classpath", stubs, "--output", dex_dir, *sorted(classes.rglob("*.class"))])
    new_dex = dex_dir / "classes.dex"
    new_classes = dex_class_descriptors(new_dex.read_bytes())
    if not new_classes or any(not name.startswith("Lcom/gtavsource/android/Xhyn") for name in new_classes):
        raise ValueError("Compiled helper DEX contains unexpected class definitions")
    run("disassemble-helpers", [java, "-cp", str(tools / "*"), "org.jf.baksmali.Main", "disassemble", new_dex, "-o", smali_out])
    shutil.copytree(smali_out, decoded / "smali_classes7")

    # Overlay the native helper and project-owned runtime assets.
    for path in (PACKAGE / "assets").rglob("*"):
        if path.is_file():
            target = decoded / "assets" / path.relative_to(PACKAGE / "assets")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    if not (decoded / "lib/arm64-v8a/libxhyn_v02.so").is_file():
        raise ValueError("Decoded Hotfix 2 APK is missing its ARM64 XHYN native helper")
    run("build-native-helper", [sys.executable, PACKAGE / "build_native.py"])
    run("native-component-host-checks", [sys.executable, PACKAGE / "tests/run_native_component.py"])
    update_manifest(decoded, build_config)

    unsigned = work / (Path(build_config["apk_filename"]).stem + "-unsigned.apk")
    run("package", [java, "-jar", apktool, "b", decoded, "-p", framework, "-o", unsigned])
    final = work / build_config["apk_filename"]
    signer = tools / "apksigner.jar"
    run("sign", [java, "-jar", signer, "sign", "--ks", keystore, "--ks-key-alias", args.key_alias,
                 "--ks-pass", "file:" + str(password_file), "--v4-signing-enabled", "false",
                 "--alignment-preserved", "false", "--lib-page-alignment", "16384", "--out", final, unsigned])
    signature = run("signature-verification", [java, "-jar", signer, "verify", "--verbose", "--print-certs", final])
    (reports / "signature-verification.txt").write_text(signature, encoding="utf-8")
    unsigned.unlink(missing_ok=True)  # Only the signed APK is published as the installable artifact.

    with zipfile.ZipFile(final) as built:
        built_names = set(built.namelist())
        if "classes7.dex" not in built_names or "lib/arm64-v8a/libxhyn_v02.so" not in built_names:
            raise ValueError("Final APK is missing its rebuilt DEX or native helper")
        final_classes = dex_class_descriptors(built.read("classes7.dex"))
        if set(final_classes) != set(new_classes):
            raise ValueError("Packaged helper DEX does not match the freshly compiled sources")
    checksum = digest(final)
    (work / "SHA256SUMS.txt").write_text(f"{checksum}  {final.name}\n", encoding="utf-8")
    report = {
        "base_apk_sha256": BASE_SHA256,
        "output_apk": final.name,
        "output_sha256": checksum,
        "app_name": build_config["app_name"],
        "version_name": build_config["version_name"],
        "version_code": build_config["version_code"],
        "helper_class_definitions": len(new_classes),
        "native_helper": "lib/arm64-v8a/libxhyn_v02.so",
        "signed_and_verified": True,
        "build_number": run_number,
        "build_attempt": run_attempt,
        "base_only_patch_scripts_reapplied": False,
    }
    (reports / "hotfix2-build.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
