import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;

/** Independent real ZIP/GZIP I/O, ownership and error cleanup regression. */
public final class ZipCompatibilityContract {
    private static int checks;
    private static void check(boolean value, String detail) {
        if (!value) throw new AssertionError(detail);
        checks++;
    }
    private static byte[] readAll(InputStream input) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[65536];
        for (int n; (n = input.read(buffer)) != -1;) output.write(buffer, 0, n);
        return output.toByteArray();
    }
    public static void run() throws Exception {
        java.lang.reflect.Method nativeRead = ZipFile.class.getDeclaredMethod("read",
                long.class, long.class, long.class, byte[].class, int.class, int.class);
        nativeRead.setAccessible(true);
        for (int[] range : new int[][] {{-1,1},{0,-1},{8,1},{1,8},
                {Integer.MAX_VALUE,1},{1,Integer.MAX_VALUE},{Integer.MAX_VALUE,Integer.MAX_VALUE}}) {
            try {
                nativeRead.invoke(null, 0L, 0L, 0L, new byte[8], range[0], range[1]);
                throw new AssertionError("invalid native range accepted");
            } catch (java.lang.reflect.InvocationTargetException expected) {
                check(expected.getCause() instanceof ArrayIndexOutOfBoundsException,
                        "native range exception: " + expected.getCause());
            }
        }
        try {
            nativeRead.invoke(null, 0L, 0L, 0L, null, 0, 0);
            throw new AssertionError("null native destination accepted");
        } catch (java.lang.reflect.InvocationTargetException expected) {
            check(expected.getCause() instanceof NullPointerException, "native null exception");
        }
        Path dir = Files.createTempDirectory("zip-contract-");
        try {
            Path empty = dir.resolve("empty.zip");
            try (ZipOutputStream out = new ZipOutputStream(Files.newOutputStream(empty))) {}
            check(Files.size(empty) == 22, "empty archive EOCD");
            try (ZipFile zip = new ZipFile(empty.toFile())) {
                check(zip.size() == 0, "empty archive size");
                check(!zip.entries().hasMoreElements(), "empty enumeration");
                check(zip.getEntry("missing") == null, "empty lookup");
            }
            byte[] content = new byte[200000];
            new Random(216).nextBytes(content);
            Path archive = dir.resolve("payload.zip");
            try (ZipOutputStream out = new ZipOutputStream(Files.newOutputStream(archive))) {
                out.putNextEntry(new ZipEntry("payload.bin"));
                out.write(content); out.closeEntry();
            }
            InputStream child;
            ZipFile zip = new ZipFile(archive.toFile());
            try {
                check(zip.size() == 1, "nonempty size");
                ZipEntry entry = zip.getEntry("payload.bin");
                check(entry != null && entry.getSize() == content.length, "entry metadata");
                try (InputStream input = zip.getInputStream(entry)) {
                    byte[] buffer = new byte[65536];
                    int first = input.read(buffer);
                    check(first > 8192, "actual inflater uses large buffer: " + first);
                    ByteArrayOutputStream all = new ByteArrayOutputStream();
                    all.write(buffer, 0, first); all.write(readAll(input));
                    check(Arrays.equals(content, all.toByteArray()), "ZIP roundtrip");
                }
                child = zip.getInputStream(entry);
                check(child.read() == (content[0] & 255), "child active");
            } finally { zip.close(); }
            try { child.read(); throw new AssertionError("closed parent accepted read"); }
            catch (IOException expected) { checks++; }
            child.close(); zip.close();
            Path deleted = dir.resolve("delete-on-close.zip");
            Files.copy(archive, deleted);
            try (ZipFile deleting = new ZipFile(deleted.toFile(), ZipFile.OPEN_READ | ZipFile.OPEN_DELETE)) {
                check(Files.exists(deleted), "OPEN_DELETE retains file while open");
                try (InputStream input = deleting.getInputStream(deleting.getEntry("payload.bin"))) {
                    check(Arrays.equals(content, readAll(input)), "OPEN_DELETE usable content");
                }
            }
            check(!Files.exists(deleted), "OPEN_DELETE removes at close");
            for (int size : new int[] {0, 1, 1024, 200000}) {
                byte[] payload = Arrays.copyOf(content, size);
                ByteArrayOutputStream compressed = new ByteArrayOutputStream();
                try (GZIPOutputStream gzip = new GZIPOutputStream(compressed)) { gzip.write(payload); }
                try (GZIPInputStream gzip = new GZIPInputStream(new ByteArrayInputStream(compressed.toByteArray()))) {
                    check(Arrays.equals(payload, readAll(gzip)), "GZIP roundtrip " + size);
                }
                byte[] bad = compressed.toByteArray(); bad[bad.length - 8] ^= 1;
                try (GZIPInputStream gzip = new GZIPInputStream(new ByteArrayInputStream(bad))) {
                    readAll(gzip); throw new AssertionError("bad CRC accepted");
                } catch (ZipException expected) { checks++; }
            }
            for (int attempt = 0; attempt < 128; attempt++) {
                try (GZIPInputStream gzip = new GZIPInputStream(new ByteArrayInputStream(new byte[32]))) {
                    throw new AssertionError("non gzip accepted");
                } catch (ZipException expected) { checks++; }
            }
            for (int length = 0; length < 22; length++) {
                Path broken = dir.resolve("truncated-" + length + ".zip");
                Files.write(broken, new byte[length]);
                try (ZipFile invalid = new ZipFile(broken.toFile())) { throw new AssertionError("truncated zip accepted"); }
                catch (ZipException expected) { checks++; }
                Files.delete(broken);
            }
            check(Files.exists(archive), "ordinary close retains archive");
            Files.delete(archive); Files.delete(empty);
        } finally {
            try (java.util.stream.Stream<Path> entries = Files.list(dir)) {
                for (Path entry : (Iterable<Path>) entries::iterator) Files.deleteIfExists(entry);
            }
            Files.delete(dir);
        }
        check(!Files.exists(dir), "all temporary files removed");
        System.out.println("ZIP_COMPATIBILITY_CONTRACT=PASS|checks=" + checks
                + "|real_io=true|large_read=true|open_delete=true|crc_checked=true|malformed_headers=128|cleanup=true");
    }
}
