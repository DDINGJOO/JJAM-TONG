package io.jjamtong.analysis;

import com.google.gson.JsonParser;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.jar.JarFile;

public final class Main {
    private Main() { }
    public static void main(String[] args) {
        try { analyze(parse(args)); }
        catch (Exception failure) {
            System.err.println("analysis failed: " + failure.getClass().getSimpleName() + ": " + failure.getMessage());
            System.exit(1);
        }
    }

    static void analyze(Config config) throws Exception {
        if (!List.of("17", "21").contains(System.getProperty("java.specification.version"))) throw new IllegalArgumentException("run this experimental adapter on JDK 17 or 21");
        if (!Files.isDirectory(config.sourceRoot()) || !Files.isRegularFile(config.artifact()) || !Files.isRegularFile(config.metadata())) throw new IllegalArgumentException("missing source-root, plain artifact, or metadata input");
        try (var jar = new JarFile(config.artifact().toFile())) {
            if (jar.stream().anyMatch(e -> e.getName().startsWith("BOOT-INF/") || e.getName().endsWith(".jar"))) throw new IllegalArgumentException("plain JAR required; nested executable JARs are not supported");
            for (var entry : jar.stream().filter(e -> e.getName().endsWith(".class")).toList()) {
                try (var input = new java.io.DataInputStream(jar.getInputStream(entry))) {
                    if (input.readInt() != 0xcafebabe) throw new IllegalArgumentException("invalid class input");
                    input.readUnsignedShort();
                    if (input.readUnsignedShort() > 61) throw new IllegalArgumentException("class input must use Java 17 or older bytecode");
                }
            }
        }
        String metadataDigest = Model.sha256(config.metadata());
        var metadata = JsonParser.parseString(Files.readString(config.metadata()));
        if (!metadata.isJsonObject()) throw new IllegalArgumentException("metadata must be a JSON object");
        String artifactDigest = Model.sha256(config.artifact()), sourceDigest = Model.sourceDigest(config.sourceRoot());
        var parserResult = JavaParserAnalysis.run(config);
        var walaResult = WalaAnalysis.run(config);
        if (!artifactDigest.equals(Model.sha256(config.artifact())) || !sourceDigest.equals(Model.sourceDigest(config.sourceRoot())) || !metadataDigest.equals(Model.sha256(config.metadata()))) throw new IllegalStateException("analysis inputs changed during analysis");
        Map<String, Object> result = Model.obj(
            "schema", "jjamtong.methods.v1", "status", "complete-with-limitations", "module", config.module(), "metadata", metadata,
            "input", Model.obj("artifactSha256", artifactDigest, "classInputSha256", artifactDigest, "sourceTreeSha256", sourceDigest, "metadataInputSha256", metadataDigest),
            "scope", Model.obj("includePackage", config.includePackage(), "excludedPackages", config.excludedPackages()),
            "provenance", Model.obj("adapterVersion", "0.1.0", "javaVersion", System.getProperty("java.version"), "javaVendor", System.getProperty("java.vendor"), "maximumBytecodeRelease", 17, "dependencyMode", "published-Maven-Central-binaries"),
            "tools", Model.obj("javaparser", parserResult, "wala", walaResult),
            "limitations", List.of("Static declaration resolution and CHA candidates are separate evidence kinds, not observed execution.", "CHA edges are reachable from the configured main; method inventory also includes unreachable declarations.", "Reflection targets, native bodies and external library calls are not inferred as application execution.", "Only Java 17 plain-JAR fixtures with the included application package and JDK dependencies are supported by this adapter.", "JavaParser explicit source calls do not model implicit constructors, initializers, lambda attribution, generated methods or bridge methods as equivalent to bytecode.", "Matching source and JAR input digests preserve provenance but do not prove that the JAR was built from this source; callers must verify their build manifest."));
        byte[] output = (Model.JSON.toJson(result) + "\n").getBytes(StandardCharsets.UTF_8);
        if (output.length > 10 * 1024 * 1024) throw new IllegalStateException("analysis output exceeds 10 MiB");
        Files.createDirectories(config.output().toAbsolutePath().getParent());
        Path temporary = Files.createTempFile(config.output().toAbsolutePath().getParent(), ".methods-", ".json");
        try {
            Files.write(temporary, output);
            Files.move(temporary, config.output(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } finally { Files.deleteIfExists(temporary); }
        System.out.println("analysis complete: " + output.length + " bytes");
    }

    private static Config parse(String[] args) {
        Map<String, String> values = new TreeMap<>();
        List<String> excluded = new ArrayList<>();
        for (int i = 0; i < args.length; i += 2) {
            if (i + 1 >= args.length || !args[i].startsWith("--")) throw new IllegalArgumentException("arguments must be --name value pairs");
            String option = switch (args[i]) {
                case "--include-prefix" -> "--include-package";
                case "--entry-class" -> "--entrypoint";
                case "--exclude-prefix" -> "--exclude-package";
                default -> args[i];
            };
            String value = args[i + 1];
            if (option.equals("--include-package") || option.equals("--exclude-package")) value = value.replaceAll("\\.$", "");
            if (option.equals("--exclude-package")) excluded.add(value);
            else if (!List.of("--source-root", "--artifact", "--module", "--metadata", "--output", "--include-package", "--entrypoint").contains(option)) throw new IllegalArgumentException("unknown option: " + option);
            else if (values.put(option, value) != null) throw new IllegalArgumentException("duplicate option: " + option);
        }
        if (excluded.isEmpty()) excluded.add("fixture.board.excluded");
        return new Config(Path.of(required(values, "--source-root")).toAbsolutePath(), Path.of(required(values, "--artifact")).toAbsolutePath(), required(values, "--module"), Path.of(required(values, "--metadata")).toAbsolutePath(), Path.of(required(values, "--output")).toAbsolutePath(), values.getOrDefault("--entrypoint", "fixture.board.Main"), values.getOrDefault("--include-package", "fixture.board"), excluded.stream().sorted().toList());
    }
    private static String required(Map<String, String> args, String name) {
        String value = args.get(name);
        if (value == null || value.isBlank()) throw new IllegalArgumentException("required argument " + name);
        return value;
    }
}
