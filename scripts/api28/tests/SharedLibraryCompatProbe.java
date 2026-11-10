import android.content.pm.PackageBackwardCompatibility;
import android.content.pm.PackageParser;
import java.util.ArrayList;
import java.util.Arrays;

/** Exercise the framework's real package compatibility entry point. */
public final class SharedLibraryCompatProbe {
    private static final String APACHE = "org.apache.http.legacy";
    private static int passed;

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static PackageParser.Package packageFor(int target) {
        PackageParser.Package pkg = new PackageParser.Package("saildroid.compat.probe");
        pkg.applicationInfo.targetSdkVersion = target;
        return pkg;
    }

    private static int occurrences(ArrayList<String> libraries) {
        int count = 0;
        if (libraries != null) {
            for (String library : libraries) {
                if (APACHE.equals(library)) count++;
            }
        }
        return count;
    }

    private static void run(String name, Runnable test) {
        test.run();
        passed++;
        System.out.println("SHARED_LIBRARY_CASE=PASS|" + name);
    }

    public static void main(String[] arguments) {
        run("modern_optional_declaration", () -> {
            PackageParser.Package pkg = packageFor(34);
            pkg.usesOptionalLibraries = new ArrayList<>(Arrays.asList(APACHE));
            PackageBackwardCompatibility.modifySharedLibraries(pkg);
            check(occurrences(pkg.usesOptionalLibraries) == 1,
                  "Compatibility updater discarded the declared optional library");
            check(occurrences(pkg.usesLibraries) == 0, "Optional library became required");
        });
        run("module_selected", () -> {
            check(!PackageBackwardCompatibility.bootClassPathContainsOAHL(),
                  "Framework selected the boot-classpath fallback");
        });
        run("modern_required_declaration", () -> {
            PackageParser.Package pkg = packageFor(34);
            pkg.usesLibraries = new ArrayList<>(Arrays.asList(APACHE));
            PackageBackwardCompatibility.modifySharedLibraries(pkg);
            check(occurrences(pkg.usesLibraries) == 1, "Required library was discarded");
        });
        run("modern_undeclared_library", () -> {
            PackageParser.Package pkg = packageFor(34);
            PackageBackwardCompatibility.modifySharedLibraries(pkg);
            check(occurrences(pkg.usesLibraries) + occurrences(pkg.usesOptionalLibraries) == 0,
                  "Modern application received an undeclared library");
        });
        run("api28_optional_declaration", () -> {
            PackageParser.Package pkg = packageFor(28);
            pkg.usesOptionalLibraries = new ArrayList<>(Arrays.asList(APACHE));
            PackageBackwardCompatibility.modifySharedLibraries(pkg);
            check(occurrences(pkg.usesOptionalLibraries) == 1, "API28 declaration was discarded");
            check(occurrences(pkg.usesLibraries) == 0, "API28 optional library became required");
        });
        run("api28_undeclared_library", () -> {
            PackageParser.Package pkg = packageFor(28);
            PackageBackwardCompatibility.modifySharedLibraries(pkg);
            check(occurrences(pkg.usesLibraries) + occurrences(pkg.usesOptionalLibraries) == 0,
                  "Implicit compatibility crossed the API28 boundary");
        });
        run("api27_implicit_library", () -> {
            PackageParser.Package pkg = packageFor(27);
            pkg.usesLibraries = new ArrayList<>(Arrays.asList("probe.other.library"));
            PackageBackwardCompatibility.modifySharedLibraries(pkg);
            check(occurrences(pkg.usesLibraries) == 1, "Legacy application lost implicit support");
            check(APACHE.equals(pkg.usesLibraries.get(0)), "Implicit library was not prefixed");
            check(pkg.usesLibraries.contains("probe.other.library"), "Other library was discarded");
        });
        run("api27_optional_library", () -> {
            PackageParser.Package pkg = packageFor(27);
            pkg.usesOptionalLibraries = new ArrayList<>(Arrays.asList(APACHE));
            PackageBackwardCompatibility.modifySharedLibraries(pkg);
            check(occurrences(pkg.usesOptionalLibraries) == 1, "Legacy optional library was discarded");
            check(occurrences(pkg.usesLibraries) == 0, "Legacy optional declaration was duplicated");
        });
        run("api27_required_library", () -> {
            PackageParser.Package pkg = packageFor(27);
            pkg.usesLibraries = new ArrayList<>(Arrays.asList(APACHE));
            PackageBackwardCompatibility.modifySharedLibraries(pkg);
            check(occurrences(pkg.usesLibraries) == 1, "Legacy required declaration was duplicated");
        });
        run("repeated_compatibility_update", () -> {
            PackageParser.Package pkg = packageFor(27);
            PackageBackwardCompatibility.modifySharedLibraries(pkg);
            PackageBackwardCompatibility.modifySharedLibraries(pkg);
            check(occurrences(pkg.usesLibraries) == 1, "Repeated update duplicated the library");
        });
        System.out.println("SHARED_LIBRARY_COMPAT=PASS|cases=" + passed);
    }
}
