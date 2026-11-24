#!/usr/bin/env python3
"""Restore the API28 package updater in an existing private boot runtime."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import zipfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("framework", "r8", "baseline-runtime", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--dexlib-classpath", required=True)
    arguments = parser.parse_args()
    module = Path(__file__).resolve().parent
    source = module / "shared-library-compat/OrgApacheHttpLegacyUpdater.java"
    output = arguments.output.resolve()
    assert digest(arguments.framework) == "cf4aed5e458deb48ddc0ca92fc25156e6f478d9d5c1d948cdd1817a67ee11b32"
    assert digest(arguments.r8) == "59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439"
    assert not output.exists(), "Build output already exists"
    output.mkdir(parents=True)
    classes = output / "classes"
    tools = output / "tools"
    classes.mkdir()
    tools.mkdir()
    commands = []

    def run(command, name):
        commands.append(command)
        result = subprocess.run(command, text=True, encoding="utf-8", capture_output=True)
        (output / name).write_text(result.stdout + result.stderr, encoding="utf-8", newline="\n")
        result.check_returncode()

    run(["javac", "-encoding", "UTF-8", "--release", "8", "-nowarn", "-sourcepath", "",
         "-classpath", str(arguments.framework), "-d", str(classes), str(source)], "javac.log")
    classfile = classes / "android/content/pm/OrgApacheHttpLegacyUpdater.class"
    assert list(classes.rglob("*.class")) == [classfile]
    overlay = output / "overlay.jar"
    run(["java", "-Xmx2g", "-cp", str(arguments.r8), "com.android.tools.r8.D8", "--release",
         "--min-api", "28", "--lib", str(arguments.framework), "--output", str(overlay),
         str(classfile)], "d8.log")
    for jar, name in ((arguments.baseline_runtime, "baseline.dex"), (overlay, "overlay.dex")):
        with zipfile.ZipFile(jar) as archive:
            (output / name).write_bytes(archive.read("classes.dex"))
    run(["javac", "-classpath", arguments.dexlib_classpath, "-d", str(tools),
         str(module / "MergeRuntimeDex.java")], "merger-javac.log")
    tool_classpath = str(tools) + os.pathsep + arguments.dexlib_classpath
    run(["java", "-cp", tool_classpath, "MergeRuntimeDex", str(output / "baseline.dex"),
         str(output / "overlay.dex"), str(output / "merged.dex")], "merge.log")
    merged = output / "merged.jar"
    with zipfile.ZipFile(merged, "x", zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo("classes.dex", (1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, (output / "merged.dex").read_bytes())

    spec = importlib.util.spec_from_file_location("platform_encoder", module / "encode-platform-dex.py")
    encoder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(encoder)
    runtime = output / "runtime.jar"
    flags = encoder.encode_jar(merged, [arguments.baseline_runtime], runtime)
    _, before_flags, _, _ = encoder.read_members((output / "baseline.dex").read_bytes())
    with zipfile.ZipFile(runtime) as archive:
        (output / "candidate.dex").write_bytes(archive.read("classes.dex"))
    _, after_flags, _, _ = encoder.read_members((output / "candidate.dex").read_bytes())
    assert all(after_flags[name] == value for name, value in before_flags.items())
    added_members = sorted(after_flags.keys() - before_flags.keys())
    descriptor = "Landroid/content/pm/OrgApacheHttpLegacyUpdater;"
    assert added_members == [descriptor + "-><init>()V",
                             descriptor + "->updatePackage(Landroid/content/pm/PackageParser$Package;)V"]
    assert flags["preserved"] == len(before_flags) and flags["private"] == 2
    for label, dex in (("baseline", "baseline.dex"), ("candidate", "candidate.dex")):
        run(["java", "-cp", arguments.dexlib_classpath, "org.jf.baksmali.Main", "disassemble",
             "--api", "28", "--output", str(output / (label + "-smali")), str(output / dex)],
            label + "-baksmali.log")
    before = {path.relative_to(output / "baseline-smali").as_posix(): path.read_bytes()
              for path in (output / "baseline-smali").rglob("*.smali")}
    after = {path.relative_to(output / "candidate-smali").as_posix(): path.read_bytes()
             for path in (output / "candidate-smali").rglob("*.smali")}
    assert all(after[name] == data for name, data in before.items()), "Existing runtime class changed"
    assert after.keys() - before.keys() == {"android/content/pm/OrgApacheHttpLegacyUpdater.smali"}
    record = {
        "passed": True,
        "upstream": "android-9.0.0_r1",
        "upstream_url": "https://android.googlesource.com/platform/frameworks/base/+/android-9.0.0_r1/core/java/android/content/pm/OrgApacheHttpLegacyUpdater.java",
        "source_sha256": digest(source),
        "baseline_runtime_sha256": digest(arguments.baseline_runtime),
        "runtime_sha256": digest(runtime),
        "framework_sha256": digest(arguments.framework),
        "r8_sha256": digest(arguments.r8),
        "javac_version": subprocess.check_output(["javac", "-version"], text=True).strip(),
        "existing_classes_identical": len(before),
        "runtime_classes": len(after),
        "added_class": descriptor,
        "hidden_api_members_preserved": len(before_flags),
        "added_private_members": added_members,
        "commands": commands,
    }
    (output / "build-result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key: value for key, value in record.items() if key != "commands"}, indent=2))


if __name__ == "__main__":
    main()
