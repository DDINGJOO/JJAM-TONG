package io.jjamtong.analysis;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.AbstractMap;
import java.util.Arrays;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Executable publication boundary oracle; uses custom byte budgets for deterministic limits. */
public final class PublicationOracle {
    private static final long DEFAULT_LIMIT = 10L * 1024 * 1024;
    private static int checks;

    private PublicationOracle() { }

    public static void main(String[] args) throws Exception {
        Path directory = Files.createTempDirectory("jjamtong-publication-oracle-");
        try {
            Path destination = directory.resolve("result.json");
            checkBudgetAndBytes(destination);
            checkUnicodeAndEscaping(destination);
            checkRejectionAndSerializationFailures(directory, destination);
            checkAtomicMoveFailure(directory);
            checkDefaultLimit(destination);
            require(temporaryFiles(directory) == 0, "all publication paths remove their temporary files");
            System.out.println("PASS: ResultPublication atomic UTF-8 bounded output; " + checks + " checks");
        } finally {
            try (var paths = Files.walk(directory)) {
                for (Path path : paths.sorted(java.util.Comparator.reverseOrder()).toList()) Files.deleteIfExists(path);
            }
        }
    }

    private static void checkBudgetAndBytes(Path destination) throws Exception {
        Map<String, Object> value = Model.obj("alpha", List.of(1, 2), "message", "budget");
        byte[] expected = bytes(value);
        require(expected[expected.length - 1] == '\n', "serialized output has terminal newline");
        require(ResultPublication.publish(destination, value, expected.length + 1) == expected.length, "under-cap byte count");
        require(Arrays.equals(expected, Files.readAllBytes(destination)), "under-cap exact UTF-8 bytes");
        require(ResultPublication.publish(destination, value, expected.length) == expected.length, "exact-cap byte count including newline");
        require(Arrays.equals(expected, Files.readAllBytes(destination)), "exact-cap exact UTF-8 bytes");
        byte[] prior = "previous bytes".getBytes(StandardCharsets.UTF_8);
        Files.write(destination, prior);
        expect(IllegalStateException.class, () -> ResultPublication.publish(destination, value, expected.length - 1), "one-byte-under budget rejected");
        require(Arrays.equals(prior, Files.readAllBytes(destination)), "rejection preserves prior bytes");
        expect(IllegalArgumentException.class, () -> ResultPublication.publish(destination, value, 0), "zero budget rejected");
        expect(IllegalArgumentException.class, () -> ResultPublication.publish(destination, value, -1), "negative budget rejected");
    }

    private static void checkUnicodeAndEscaping(Path destination) throws Exception {
        Map<String, Object> value = Model.obj("text", "한국어 😀 \ud800 \"quoted\"\n\t\\ <tag>&=", "control", "\u0001\b\f\r");
        byte[] expected = bytes(value);
        require(ResultPublication.publish(destination, value, expected.length) == expected.length, "Unicode exact-cap byte count");
        byte[] actual = Files.readAllBytes(destination);
        require(Arrays.equals(expected, actual), "Korean emoji surrogate and escaping exact bytes");
        require(new String(actual, StandardCharsets.UTF_8).contains("<tag>&="), "HTML escaping remains disabled");
        require(ResultPublication.publish(destination, value, expected.length) == expected.length, "repeated publication byte count");
        require(Arrays.equals(expected, Files.readAllBytes(destination)), "repeated publication stable bytes");
    }

    private static void checkRejectionAndSerializationFailures(Path directory, Path destination) throws Exception {
        Path absent = directory.resolve("absent.json");
        byte[] oversized = bytes(Model.obj("value", "too large"));
        long before = temporaryFiles(directory);
        expect(IllegalStateException.class, () -> ResultPublication.publish(absent, Model.obj("value", "too large"), oversized.length - 1), "absent output rejection");
        require(!Files.exists(absent), "rejected absent destination remains absent");
        require(temporaryFiles(directory) == before, "output rejection cleans temporary file");

        byte[] marker = "existing marker".getBytes(StandardCharsets.UTF_8);
        Files.write(destination, marker);
        before = temporaryFiles(directory);
        expect(RuntimeException.class, () -> ResultPublication.publish(destination, new ThrowingMap(), 4096), "serialization runtime failure");
        require(Arrays.equals(marker, Files.readAllBytes(destination)), "serialization failure preserves prior bytes");
        require(temporaryFiles(directory) == before, "serialization failure cleans temporary file");

        var earlyLimit = new ThrowingMap("x".repeat(32768));
        expect(IllegalStateException.class, () -> ResultPublication.publish(destination, earlyLimit, 64), "limit interrupts serialization");
        require(!earlyLimit.reachedFailure, "byte rejection stops traversal before the next map entry");
        require(Arrays.equals(marker, Files.readAllBytes(destination)), "early byte rejection preserves prior bytes");
        require(temporaryFiles(directory) == before, "early byte rejection cleans temporary file");
    }

    private static void checkAtomicMoveFailure(Path directory) throws Exception {
        Path destination = directory.resolve("nonempty-destination");
        Files.createDirectories(destination);
        Path marker = destination.resolve("marker");
        Files.writeString(marker, "keep");
        long before = temporaryFiles(directory);
        expect(Exception.class, () -> ResultPublication.publish(destination, Model.obj("value", "move failure"), 4096), "atomic move to nonempty directory fails");
        require(Files.isDirectory(destination) && Files.readString(marker).equals("keep"), "atomic move failure preserves destination directory");
        require(temporaryFiles(directory) == before, "atomic move failure cleans temporary file");
    }

    private static void checkDefaultLimit(Path destination) throws Exception {
        String exactText = "x".repeat((int) DEFAULT_LIMIT - 3); // JSON quotes plus terminal newline.
        byte[] exact = bytes(exactText);
        require(exact.length == DEFAULT_LIMIT, "generated exact default limit");
        require(ResultPublication.publish(destination, exactText) == DEFAULT_LIMIT, "default exact-cap success");
        require(Arrays.equals(exact, Files.readAllBytes(destination)), "default exact-cap bytes");
        byte[] prior = Files.readAllBytes(destination);
        String oversized = "x".repeat((int) DEFAULT_LIMIT - 2);
        IllegalStateException failure = expect(IllegalStateException.class, () -> ResultPublication.publish(destination, oversized), "default oversized output rejected");
        require("analysis output exceeds 10 MiB".equals(failure.getMessage()), "default limit message");
        require(Arrays.equals(prior, Files.readAllBytes(destination)), "default rejection preserves exact-cap output");
    }

    private static byte[] bytes(Object value) { return (Model.JSON.toJson(value) + "\n").getBytes(StandardCharsets.UTF_8); }

    private static long temporaryFiles(Path directory) throws IOException {
        try (var paths = Files.list(directory)) {
            return paths.filter(path -> path.getFileName().toString().matches("\\.methods-.*\\.json")).count();
        }
    }

    private static <T extends Throwable> T expect(Class<T> type, Throwing action, String label) throws Exception {
        try {
            action.run();
        } catch (Throwable failure) {
            if (type.isInstance(failure)) {
                checks++;
                return type.cast(failure);
            }
            throw new AssertionError(label + " threw " + failure.getClass().getName(), failure);
        }
        throw new AssertionError(label + " did not throw");
    }

    private static void require(boolean condition, String label) {
        checks++;
        if (!condition) throw new AssertionError(label);
    }

    @FunctionalInterface private interface Throwing { void run() throws Exception; }

    private static final class ThrowingMap extends AbstractMap<String, Object> {
        private final String first;
        private boolean reachedFailure;

        private ThrowingMap() { this("value"); }
        private ThrowingMap(String first) { this.first = first; }

        @Override public Set<Entry<String, Object>> entrySet() {
            return new java.util.AbstractSet<>() {
                @Override public Iterator<Entry<String, Object>> iterator() {
                    return new Iterator<>() {
                        private int position;
                        @Override public boolean hasNext() { return position < 2; }
                        @Override public Entry<String, Object> next() {
                            if (position++ == 0) return Map.entry("written-before-failure", first);
                            reachedFailure = true;
                            throw new IllegalStateException("intentional serialization failure");
                        }
                    };
                }
                @Override public int size() { return 2; }
            };
        }
    }
}
