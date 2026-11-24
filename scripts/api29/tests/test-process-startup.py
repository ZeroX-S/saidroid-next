#!/usr/bin/env python3
"""Exercise the actual endpoint wait with a virtual Android clock and registry."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

REPO = Path(__file__).resolve().parents[3]
JAVA_HOME = os.environ.get("JAVA_HOME")
JAVAC = str(Path(JAVA_HOME) / "bin/javac") if JAVA_HOME else shutil.which("javac")
JAVA = str(Path(JAVA_HOME) / "bin/java") if JAVA_HOME else shutil.which("java")

STUBS = {
    "android/os/IBinder.java": """
        package android.os;
        public interface IBinder { boolean isBinderAlive(); }
    """,
    "android/os/IServiceManager.java": """
        package android.os;
        public interface IServiceManager {
            IBinder checkService(String name) throws RemoteException;
        }
    """,
    "android/os/RemoteException.java": """
        package android.os;
        public class RemoteException extends Exception {}
    """,
    "android/os/SystemClock.java": """
        package android.os;
        public final class SystemClock {
            public static long now;
            public static long step = 10000;
            public static long uptimeMillis() {
                long result = now;
                now += step;
                return result;
            }
        }
    """,
    "SdKernelServices.java": """
        import android.os.*;
        public final class SdKernelServices {
            static IServiceManager service;
            public static synchronized IServiceManager registry() { return service; }
        }
    """,
    "ProcessStartupContract.java": """
        import android.os.*;
        public final class ProcessStartupContract {
            static final IBinder LIVE = new IBinder() {
                public boolean isBinderAlive() { return true; }
            };
            static final IBinder DEAD = new IBinder() {
                public boolean isBinderAlive() { return false; }
            };
            public static void main(String[] arguments) throws Exception {
                final String scenario = arguments[0];
                final int[] calls = {0};
                SdKernelServices.service = new IServiceManager() {
                    public IBinder checkService(String name) throws RemoteException {
                        if (!"endpoint".equals(name)) throw new AssertionError(name);
                        calls[0]++;
                        if ("transport".equals(scenario)) throw new RemoteException();
                        if ("immediate".equals(scenario)) return LIVE;
                        if ("late".equals(scenario) && SystemClock.now >= 50000) return LIVE;
                        if ("stale".equals(scenario)) return calls[0] < 4 ? DEAD : LIVE;
                        return null;
                    }
                };
                if ("interrupt".equals(scenario)) Thread.currentThread().interrupt();
                try {
                    IBinder result = SdProcessStartup.awaitEndpoint("endpoint", "deadline proof");
                    if (result != LIVE) throw new AssertionError("Dead endpoint accepted");
                    if ("immediate".equals(scenario) && calls[0] != 1) throw new AssertionError("Unneeded polling");
                    if ("late".equals(scenario) && SystemClock.now <= 30000) throw new AssertionError("Late startup not exercised");
                    if ("stale".equals(scenario) && calls[0] != 4) throw new AssertionError("Dead Binder not retried");
                    if (!"immediate".equals(scenario) && !"late".equals(scenario) && !"stale".equals(scenario)) throw new AssertionError("Failure swallowed");
                } catch (IllegalStateException expected) {
                    if (!"timeout".equals(scenario) || !"deadline proof".equals(expected.getMessage())) throw expected;
                    if (SystemClock.now < SdProcessStartup.TIMEOUT_MS || calls[0] > 14) throw new AssertionError("Unbounded timeout");
                } catch (InterruptedException expected) {
                    if (!"interrupt".equals(scenario)) throw expected;
                } catch (RemoteException expected) {
                    if (!"transport".equals(scenario)) throw expected;
                }
                System.out.println("PROCESS_STARTUP=PASS|case=" + scenario);
            }
        }
    """,
}


@unittest.skipUnless(JAVAC and JAVA, "Set JAVA_HOME to run the Java regression")
class ProcessStartupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix="saildroid-process-startup-")
        cls.root = Path(cls.workspace.name)
        sources = []
        for name, source in STUBS.items():
            path = cls.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(source))
            sources.append(str(path))
        cls.classes = cls.root / "classes"
        cls.classes.mkdir()
        subprocess.run([JAVAC, "--release", "8", "-d", str(cls.classes),
                        str(REPO / "scripts/device/SdProcessStartup.java"), *sources],
                       check=True, capture_output=True, text=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def test_endpoint_wait(self):
        for scenario in ["immediate", "late", "stale", "timeout", "interrupt", "transport"]:
            with self.subTest(scenario=scenario):
                result = subprocess.run([JAVA, "-cp", str(self.classes),
                                         "ProcessStartupContract", scenario],
                                        check=True, capture_output=True, text=True, timeout=10)
                self.assertIn("PROCESS_STARTUP=PASS|case=" + scenario, result.stdout)


if __name__ == "__main__":
    unittest.main()
