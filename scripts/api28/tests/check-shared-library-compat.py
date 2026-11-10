#!/usr/bin/env python3
"""Run the real API28 package updater on the host with an Android logging stub."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


LOG_STUB = """package android.util;
public final class Log {
    public static int i(String tag, String message) { return 0; }
    public static int e(String tag, String message, Throwable failure) { return 0; }
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", type=Path, required=True)
    parser.add_argument("--without-updater", action="store_true")
    arguments = parser.parse_args()
    module = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="saildroid-shared-library-test-") as temporary:
        work = Path(temporary)
        log = work / "android/util/Log.java"
        log.parent.mkdir(parents=True)
        log.write_text(LOG_STUB, encoding="utf-8", newline="\n")
        classes = work / "classes"
        classes.mkdir()
        sources = [log, module / "tests/SharedLibraryCompatProbe.java"]
        if not arguments.without_updater:
            sources.append(module / "shared-library-compat/OrgApacheHttpLegacyUpdater.java")
        subprocess.run(["javac", "-encoding", "UTF-8", "--release", "8", "-nowarn",
                        "-sourcepath", "", "-classpath", str(arguments.framework), "-d", str(classes),
                        *map(str, sources)], check=True)
        subprocess.run(["java", "-cp", str(classes) + os.pathsep + str(arguments.framework),
                        "SharedLibraryCompatProbe"], check=True)


if __name__ == "__main__":
    main()
