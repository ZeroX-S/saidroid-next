/** Exercise ART-owned mappings independently of an application's kernel stack. */
public final class ArtSignalStackOwnership {
    private static native int exercise(int mode, int iterations);
    public static void main(String[] args) throws Exception {
        String expected = System.getProperty("stack.art");
        boolean mapped = false;
        for (String line : java.nio.file.Files.readAllLines(java.nio.file.Paths.get("/proc/self/maps"))) {
            if (line.endsWith("/libart.so")) {
                if (!line.endsWith(" " + expected)) throw new AssertionError(line);
                mapped = true;
            }
        }
        if (!mapped) throw new AssertionError("ART mapping missing");
        System.load(System.getProperty("stack.helper"));
        int mode = Integer.parseInt(args[0]);
        int count = exercise(mode, 64);
        if (count != 64) throw new AssertionError("mode=" + mode + " result=" + count);
        System.out.println("ART_STACK_OWNERSHIP=PASS|mode=" + mode + "|threads=" + count
                + "|art=" + expected);
        System.out.flush();
        System.exit(0);
    }
}
