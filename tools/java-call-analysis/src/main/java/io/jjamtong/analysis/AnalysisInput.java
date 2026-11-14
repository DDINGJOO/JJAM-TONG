package io.jjamtong.analysis;

import java.io.BufferedInputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.jar.JarOutputStream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** Validated, non-executing analysis boundary for plain and Spring Boot JAR inputs. */
final class AnalysisInput implements AutoCloseable {
    private static final long MAX_ORIGINAL_BYTES = 256L * 1024 * 1024;
    private static final int MAX_ENTRIES = 20_000;
    private static final long MAX_CLASS_BYTES = 4L * 1024 * 1024;
    private static final long MAX_TOTAL_CLASS_BYTES = 32L * 1024 * 1024;
    private static final long MAX_DEPENDENCY_BYTES = 64L * 1024 * 1024;
    private static final long MAX_TOTAL_DEPENDENCY_BYTES = 256L * 1024 * 1024;
    private static final int MAX_DEPENDENCIES = 256;
    private static final String BOOT_CLASSES = "BOOT-INF/classes/";
    private static final String BOOT_LIB = "BOOT-INF/lib/";

    private final Path artifact;
    private final List<Path> dependencies;
    private final String classInputSha256;
    private final List<Map<String, String>> dependencyEvidence;
    private final Path temporaryDirectory;

    private AnalysisInput(Path artifact, List<Path> dependencies, Path temporaryDirectory) throws IOException {
        this.artifact = artifact;
        this.dependencies = List.copyOf(dependencies);
        List<Map<String, String>> evidence = new ArrayList<>();
        for (Path dependency : dependencies) evidence.add(Map.of("entry", BOOT_LIB + dependency.getFileName(), "sha256", Model.sha256(dependency)));
        this.dependencyEvidence = List.copyOf(evidence);
        this.classInputSha256 = Model.sha256(artifact);
        this.temporaryDirectory = temporaryDirectory;
    }

    static AnalysisInput open(Path original, boolean boot) throws Exception {
        requireOriginal(original);
        if (!boot) {
            validatePlain(original);
            return new AnalysisInput(original, List.of(), null);
        }
        Path temporary = Files.createTempDirectory("jjamtong-analysis-input-");
        try {
            return extractBoot(original, temporary);
        } catch (Exception failure) {
            deleteTree(temporary);
            throw failure;
        }
    }

    Path artifact() { return artifact; }
    List<Path> dependencies() { return dependencies; }
    List<Map<String, String>> dependencyEvidence() { return dependencyEvidence; }
    String classInputSha256() { return classInputSha256; }

    @Override public void close() throws IOException {
        if (temporaryDirectory != null) deleteTree(temporaryDirectory);
    }

    private static AnalysisInput extractBoot(Path original, Path temporary) throws Exception {
        List<ClassEntry> classes = new ArrayList<>();
        List<Path> dependencies = new ArrayList<>();
        Set<String> normalizedClasses = new HashSet<>(), dependencyNames = new HashSet<>();
        long classBytes = 0, dependencyBytes = 0;
        try (ZipFile archive = new ZipFile(original.toFile())) {
            List<? extends ZipEntry> entries = checkedEntries(archive);
            for (ZipEntry entry : entries) {
                String name = entry.getName();
                if (entry.isDirectory()) continue;
                if (name.startsWith(BOOT_CLASSES) && name.endsWith(".class")) {
                    String normalized = name.substring(BOOT_CLASSES.length());
                    if (!safeRelative(normalized) || !normalizedClasses.add(normalized)) throw invalid("duplicate or unsafe normalized class entry");
                    byte[] bytes = readBounded(archive.getInputStream(entry), Math.min(MAX_CLASS_BYTES, MAX_TOTAL_CLASS_BYTES - classBytes), "class entry");
                    classBytes = addBounded(classBytes, bytes.length, MAX_TOTAL_CLASS_BYTES, "total class bytes");
                    validateClass(bytes, 65);
                    classes.add(new ClassEntry(normalized, bytes));
                } else if (name.startsWith(BOOT_LIB) && name.endsWith(".jar")) {
                    String basename = name.substring(BOOT_LIB.length());
                    if (!safeBasename(basename) || !dependencyNames.add(basename)) throw invalid("duplicate or unsafe dependency entry");
                    if (dependencies.size() == MAX_DEPENDENCIES) throw invalid("too many dependencies");
                    Path destination = temporary.resolve("deps").resolve(basename);
                    Files.createDirectories(destination.getParent());
                    long copied;
                    try (InputStream input = archive.getInputStream(entry); OutputStream output = Files.newOutputStream(destination, StandardOpenOption.CREATE_NEW)) {
                        copied = copyBounded(input, output, Math.min(MAX_DEPENDENCY_BYTES, MAX_TOTAL_DEPENDENCY_BYTES - dependencyBytes), "dependency entry");
                    }
                    dependencyBytes = addBounded(dependencyBytes, copied, MAX_TOTAL_DEPENDENCY_BYTES, "total dependency bytes");
                    validateDependency(destination);
                    dependencies.add(destination);
                }
            }
        }
        if (classes.isEmpty()) throw invalid("BOOT-INF/classes must contain classes");
        if (dependencies.isEmpty()) throw invalid("BOOT-INF/lib must contain JAR dependencies");
        Path normalized = temporary.resolve("classes.jar");
        classes.sort(Comparator.comparing(ClassEntry::name));
        try (JarOutputStream output = new JarOutputStream(Files.newOutputStream(normalized))) {
            for (ClassEntry entry : classes) {
                JarEntry target = new JarEntry(entry.name());
                target.setTime(0);
                output.putNextEntry(target);
                output.write(entry.bytes());
                output.closeEntry();
            }
        }
        return new AnalysisInput(normalized, dependencies, temporary);
    }

    private static void validatePlain(Path original) throws Exception {
        try (ZipFile archive = new ZipFile(original.toFile())) {
            long classBytes = 0;
            for (ZipEntry entry : checkedEntries(archive)) {
                if (entry.isDirectory()) continue;
                String name = entry.getName();
                if (name.startsWith("BOOT-INF/") || name.endsWith(".jar")) throw invalid("plain JAR must not contain BOOT-INF or nested archives");
                if (name.endsWith(".class")) {
                    byte[] bytes = readBounded(archive.getInputStream(entry), Math.min(MAX_CLASS_BYTES, MAX_TOTAL_CLASS_BYTES - classBytes), "class entry");
                    classBytes = addBounded(classBytes, bytes.length, MAX_TOTAL_CLASS_BYTES, "total class bytes");
                    validateClass(bytes, 61);
                }
            }
        }
    }

    private static List<? extends ZipEntry> checkedEntries(ZipFile archive) throws IOException {
        List<ZipEntry> result = new ArrayList<>();
        Set<String> names = new HashSet<>();
        Enumeration<? extends ZipEntry> entries = archive.entries();
        while (entries.hasMoreElements()) {
            ZipEntry entry = entries.nextElement();
            if (result.size() == MAX_ENTRIES) throw invalid("too many archive entries");
            if (!safeEntryName(entry.getName()) || !names.add(entry.getName())) throw invalid("unsafe or duplicate archive entry");
            result.add(entry);
        }
        return result;
    }

    private static void requireOriginal(Path original) throws IOException {
        if (original == null || !Files.isRegularFile(original) || !Files.isReadable(original)) throw invalid("artifact must be a readable regular file");
        if (Files.size(original) > MAX_ORIGINAL_BYTES) throw invalid("artifact exceeds 256 MiB");
    }

    private static void validateDependency(Path dependency) throws IOException {
        if (!Files.isRegularFile(dependency) || !Files.isReadable(dependency)) throw invalid("dependency is not a readable regular file");
        try (JarFile ignored = new JarFile(dependency.toFile(), true)) { /* ZIP structure only; never load classes. */ }
    }

    private static void validateClass(byte[] bytes, int maximumMajor) throws IOException {
        if (bytes.length < 8) throw invalid("truncated class header");
        try (DataInputStream input = new DataInputStream(new BufferedInputStream(new java.io.ByteArrayInputStream(bytes)))) {
            if (input.readInt() != 0xcafebabe) throw invalid("invalid class magic");
            if (input.readUnsignedShort() == 0xffff) throw invalid("preview class files are unsupported");
            if (input.readUnsignedShort() > maximumMajor) throw invalid("class bytecode exceeds supported Java release");
        }
    }

    private static byte[] readBounded(InputStream input, long maximum, String label) throws IOException {
        try (input) {
            java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream();
            copyBounded(input, output, maximum, label);
            return output.toByteArray();
        }
    }

    private static long copyBounded(InputStream input, OutputStream output, long maximum, String label) throws IOException {
        byte[] buffer = new byte[16 * 1024];
        long total = 0;
        for (int count; (count = input.read(buffer)) != -1;) {
            total = addBounded(total, count, maximum, label);
            output.write(buffer, 0, count);
        }
        return total;
    }

    private static long addBounded(long total, long added, long maximum, String label) throws IOException {
        if (added < 0 || total > maximum - added) throw invalid(label + " exceeds limit");
        return total + added;
    }

    private static boolean safeEntryName(String name) {
        return safeRelative(name) && name.indexOf('\\') < 0;
    }
    private static boolean safeRelative(String name) {
        if (name.isEmpty() || name.startsWith("/") || name.indexOf('\\') >= 0 || name.indexOf('\u0000') >= 0) return false;
        String checked = name.endsWith("/") ? name.substring(0, name.length() - 1) : name;
        if (checked.isEmpty()) return false;
        for (String part : checked.split("/", -1)) if (part.isEmpty() || part.equals(".") || part.equals("..")) return false;
        return true;
    }
    private static boolean safeBasename(String name) {
        return name.endsWith(".jar") && !name.contains("/") && name.indexOf('\\') < 0 && safeRelative(name);
    }
    private static IOException invalid(String message) { return new IOException(message); }

    private static void deleteTree(Path directory) throws IOException {
        if (!Files.exists(directory)) return;
        try (var paths = Files.walk(directory)) {
            IOException failure = null;
            for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) {
                try { Files.deleteIfExists(path); }
                catch (IOException deletion) { if (failure == null) failure = deletion; else failure.addSuppressed(deletion); }
            }
            if (failure != null) throw failure;
        }
    }

    private record ClassEntry(String name, byte[] bytes) { }
}
