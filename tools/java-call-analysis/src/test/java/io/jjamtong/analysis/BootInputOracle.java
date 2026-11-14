package io.jjamtong.analysis;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import javax.tools.ToolProvider;

/** Executable boundary oracle; uses only synthetic classes and nested archives. */
public final class BootInputOracle {
    private BootInputOracle() { }
    public static void main(String[] args) throws Exception {
        boolean policyRejected = false;
        try { Main.parse(new String[]{"--source-root", ".", "--artifact", "app.jar", "--module", "test", "--metadata", "m.json", "--output", "out.json", "--entrypoint-policy", "all-included-methods"}); }
        catch (IllegalArgumentException expected) { policyRejected = true; }
        require(policyRejected, "plain JAR rejects synthetic-root policy");
        Path directory = Files.createTempDirectory("jjamtong-boot-input-oracle-");
        try {
            Path classes = compile(directory);
            byte[] classBytes = Files.readAllBytes(classes.resolve("fixture/BootTarget.class"));
            Path boot = directory.resolve("app.jar");
            byte[] original = bootBytes(classBytes, nestedJar());
            Files.write(boot, original);
            String first;
            try (AnalysisInput input = AnalysisInput.open(boot, true)) {
                first = input.classInputSha256();
                require(input.dependencyEvidence().size() == 1 && input.dependencyEvidence().get(0).get("entry").startsWith("BOOT-INF/lib/") && input.dependencyEvidence().get(0).get("sha256").equals(Model.sha256(input.dependencies().get(0))), "nested dependency provenance");
                require(input.dependencies().size() == 1, "dependency extracted");
                require(Files.isRegularFile(input.dependencies().get(0)), "dependency exists");
                require(Files.isRegularFile(input.artifact()), "classes JAR exists");
                try (var jar = new java.util.jar.JarFile(input.artifact().toFile())) {
                    require(jar.getJarEntry("fixture/BootTarget.class") != null, "normalized class present");
                    require(jar.stream().noneMatch(e -> e.getName().startsWith("BOOT-INF/")), "no Boot layout retained");
                }
            }
            try (AnalysisInput input = AnalysisInput.open(boot, true)) { require(first.equals(input.classInputSha256()), "deterministic normalized digest"); }
            Path reordered = writeBytes(directory, "reordered.jar", bootBytes(classBytes, nestedJar(), true));
            try (AnalysisInput input = AnalysisInput.open(reordered, true)) { require(first.equals(input.classInputSha256()), "sorted normalized digest"); }
            require(Arrays.equals(original, Files.readAllBytes(boot)), "original bytes unchanged");
            expectFailure(() -> AnalysisInput.open(boot, false), "plain rejects Boot JAR");
            expectFailure(() -> openBytes(directory, "traversal.jar", zip(List.of(new Entry("../bad.class", classBytes))), false), "traversal rejected");
            expectFailure(() -> openBytes(directory, "preview.jar", plainJar(withHeader(classBytes, 0xffff, 61)), false), "preview rejected");
            expectFailure(() -> openBytes(directory, "major.jar", plainJar(withHeader(classBytes, 0, 62)), false), "plain major rejected");
            expectFailure(() -> openBytes(directory, "boot-major.jar", bootBytes(withHeader(classBytes, 0, 66), nestedJar()), true), "Boot major rejected");
            expectFailure(() -> openBytes(directory, "duplicate.jar", duplicateEntries("a.class", classBytes), false), "duplicate rejected");
            String prefix = "jjamtong-analysis-input-";
            long before = tempInputs(prefix);
            expectFailure(() -> AnalysisInput.open(writeBytes(directory, "broken-boot.jar", bootBytes(classBytes, new byte[] {1, 2, 3})), true), "bad dependency rejected");
            require(tempInputs(prefix) == before, "failed extraction cleaned its temporary directory");
            System.out.println("PASS: Boot normalization/dependencies/digest; plain boundary; traversal, duplicate, preview and major rejection; original preservation; failure cleanup");
        } finally {
            try (var paths = Files.walk(directory)) { for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) Files.deleteIfExists(path); }
        }
    }

    private static Path compile(Path directory) throws IOException {
        Path source = directory.resolve("src/fixture/BootTarget.java"), classes = directory.resolve("classes");
        Files.createDirectories(source.getParent()); Files.createDirectories(classes);
        Files.writeString(source, "package fixture; public class BootTarget { public String value() { return \"ok\"; } }");
        int result = ToolProvider.getSystemJavaCompiler().run(null, null, null, "--release", "17", "-d", classes.toString(), source.toString());
        require(result == 0, "synthetic compile");
        return classes;
    }

    private static AnalysisInput openBytes(Path directory, String name, byte[] bytes, boolean boot) throws Exception {
        return AnalysisInput.open(writeBytes(directory, name, bytes), boot);
    }
    private static Path writeBytes(Path directory, String name, byte[] bytes) throws IOException { Path file = directory.resolve(name); Files.write(file, bytes); return file; }
    private static byte[] bootBytes(byte[] classBytes, byte[] dependency) throws IOException { return bootBytes(classBytes, dependency, false); }
    private static byte[] bootBytes(byte[] classBytes, byte[] dependency, boolean reverseClasses) throws IOException {
        List<Entry> entries = new ArrayList<>(List.of(new Entry("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n".getBytes()), new Entry("BOOT-INF/lib/example.jar", dependency), new Entry("org/springframework/boot/loader/Launcher.class", new byte[] {0})));
        Entry first = new Entry("BOOT-INF/classes/fixture/BootTarget.class", classBytes), second = new Entry("BOOT-INF/classes/fixture/Another.class", classBytes);
        if (reverseClasses) { entries.add(second); entries.add(first); } else { entries.add(first); entries.add(second); }
        return zip(entries);
    }
    private static byte[] plainJar(byte[] classBytes) throws IOException { return zip(List.of(new Entry("fixture/BootTarget.class", classBytes))); }
    private static byte[] nestedJar() throws IOException { return zip(List.of(new Entry("nested/Dependency.class", new byte[] {0, 1, 2}))); }
    private static byte[] zip(List<Entry> entries) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (ZipOutputStream output = new ZipOutputStream(bytes)) {
            for (Entry entry : entries) { ZipEntry target = new ZipEntry(entry.name()); target.setTime(0); output.putNextEntry(target); output.write(entry.bytes()); output.closeEntry(); }
        }
        return bytes.toByteArray();
    }
    private static byte[] duplicateEntries(String name, byte[] bytes) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(output)) {
            // ZipOutputStream refuses duplicate names, so construct a valid first entry then duplicate its central-directory name.
            zip.putNextEntry(new ZipEntry(name)); zip.write(bytes); zip.closeEntry();
        }
        byte[] result = output.toByteArray();
        int central = indexOf(result, new byte[] {0x50, 0x4b, 0x01, 0x02});
        byte[] duplicate = Arrays.copyOfRange(result, central, result.length - 22);
        int end = result.length - 22;
        byte[] combined = new byte[end + duplicate.length + 22];
        System.arraycopy(result, 0, combined, 0, end); System.arraycopy(duplicate, 0, combined, end, duplicate.length); System.arraycopy(result, end, combined, end + duplicate.length, 22);
        combined[combined.length - 22 + 8] = 2; // central directory entry count, low byte
        combined[combined.length - 22 + 10] = 2; // total entry count, low byte
        int size = duplicate.length * 2;
        combined[combined.length - 22 + 12] = (byte) size; combined[combined.length - 22 + 13] = (byte) (size >>> 8);
        return combined;
    }
    private static int indexOf(byte[] input, byte[] target) { for (int i = 0; i <= input.length - target.length; i++) if (Arrays.equals(Arrays.copyOfRange(input, i, i + target.length), target)) return i; throw new AssertionError("central directory"); }
    private static byte[] withHeader(byte[] bytes, int minor, int major) { byte[] copy = bytes.clone(); copy[4] = (byte) (minor >>> 8); copy[5] = (byte) minor; copy[6] = (byte) (major >>> 8); copy[7] = (byte) major; return copy; }
    private static long tempInputs(String prefix) throws IOException { try (var paths = Files.list(Path.of(System.getProperty("java.io.tmpdir")))) { return paths.filter(p -> p.getFileName().toString().startsWith(prefix)).count(); } }
    private static void expectFailure(Throwing action, String label) throws Exception { try { try (AnalysisInput ignored = action.open()) { } throw new AssertionError(label); } catch (IOException expected) { } }
    private static void require(boolean value, String label) { if (!value) throw new AssertionError(label); }
    private record Entry(String name, byte[] bytes) { }
    @FunctionalInterface private interface Throwing { AnalysisInput open() throws Exception; }
}
