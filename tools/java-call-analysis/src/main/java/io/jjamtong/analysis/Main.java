package io.jjamtong.analysis;

import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

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
        if (config.boot() && !System.getProperty("java.specification.version").equals("21")) throw new IllegalArgumentException("Spring Boot analysis requires JDK 21");
        String metadataDigest = Model.sha256(config.metadata());
        var metadata = JsonParser.parseString(Files.readString(config.metadata()));
        if (!metadata.isJsonObject()) throw new IllegalArgumentException("metadata must be a JSON object");
        String artifactDigest = Model.sha256(config.artifact()), sourceDigest = Model.sourceDigest(config.sourceRoot());
        try (var input = AnalysisInput.open(config.artifact(), config.boot())) {
            Config analysisConfig = config.withArtifact(input.artifact());
            var parserResult = JavaParserAnalysis.run(analysisConfig, input.dependencies());
            var walaResult = WalaAnalysis.run(analysisConfig, input.dependencies());
            if (!artifactDigest.equals(Model.sha256(config.artifact())) || !sourceDigest.equals(Model.sourceDigest(config.sourceRoot())) || !metadataDigest.equals(Model.sha256(config.metadata()))) throw new IllegalStateException("analysis inputs changed during analysis");
            Map<String, Object> inputEvidence = Model.obj("artifactSha256", artifactDigest, "classInputSha256", input.classInputSha256(), "sourceTreeSha256", sourceDigest, "metadataInputSha256", metadataDigest);
            if (config.boot()) inputEvidence.put("dependencyArtifacts", input.dependencyEvidence());
            Map<String, Object> result = Model.obj(
                "schema", "jjamtong.methods.v1", "status", "complete-with-limitations", "module", config.module(), "metadata", metadata,
                "input", inputEvidence,
                "scope", Model.obj("includePackage", config.includePackage(), "excludedPackages", config.excludedPackages()),
                "provenance", Model.obj("adapterVersion", "0.2.2", "javaVersion", System.getProperty("java.version"), "javaVendor", System.getProperty("java.vendor"), "maximumBytecodeRelease", config.boot() ? 21 : 17, "dependencyMode", config.boot() ? "boot-nested-libraries-from-exact-artifact" : "published-Maven-Central-binaries"),
                "tools", Model.obj("javaparser", parserResult, "wala", walaResult),
                "limitations", List.of("Static declaration resolution and CHA candidates are separate evidence kinds, not observed execution.", config.allMethods() ? "All included concrete methods are synthetic CHA roots; this over-approximates framework dispatch, not actual route reachability." : "CHA edges are reachable from the configured main; method inventory also includes unreachable declarations.", "Reflection targets, native bodies and external library calls are not inferred as application execution.", config.boot() ? "Experimental Java 21 Spring Boot JAR input; application classes only, nested libraries resolve types but are not application graph nodes. Spring proxies, reflection and dependency injection feasibility are not modeled." : "Java 17 plain-JAR fixtures with the included application package and JDK dependencies are supported by this adapter.", "JavaParser explicit source calls do not model implicit constructors, initializers, lambda attribution, generated methods or bridge methods as equivalent to bytecode.", "Matching source and JAR input digests preserve provenance but do not prove that the JAR was built from this source; callers must verify their build manifest."));
            long outputBytes = ResultPublication.publish(config.output(), result);
            System.out.println("analysis complete: " + outputBytes + " bytes");
        }
    }

    static Config parse(String[] args) {
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
            else if (!List.of("--source-root", "--artifact", "--module", "--metadata", "--output", "--include-package", "--entrypoint", "--artifact-format", "--entrypoint-policy").contains(option)) throw new IllegalArgumentException("unknown option: " + option);
            else if (values.put(option, value) != null) throw new IllegalArgumentException("duplicate option: " + option);
        }
        if (excluded.isEmpty()) excluded.add("fixture.board.excluded");
        String format = values.getOrDefault("--artifact-format", "plain");
        String policy = values.getOrDefault("--entrypoint-policy", "main");
        if (!List.of("plain", "spring-boot").contains(format) || !List.of("main", "all-included-methods").contains(policy)) throw new IllegalArgumentException("unsupported artifact format or entrypoint policy");
        if (format.equals("plain") && !policy.equals("main")) throw new IllegalArgumentException("plain JAR analysis requires main entrypoint policy");
        if (format.equals("spring-boot") && !policy.equals("all-included-methods")) throw new IllegalArgumentException("Spring Boot requires explicit all-included-methods policy; main does not model framework dispatch");
        return new Config(Path.of(required(values, "--source-root")).toAbsolutePath(), Path.of(required(values, "--artifact")).toAbsolutePath(), required(values, "--module"), Path.of(required(values, "--metadata")).toAbsolutePath(), Path.of(required(values, "--output")).toAbsolutePath(), values.getOrDefault("--entrypoint", "fixture.board.Main"), values.getOrDefault("--include-package", "fixture.board"), excluded.stream().sorted().toList(), format.equals("spring-boot"), policy.equals("all-included-methods"));
    }
    private static String required(Map<String, String> args, String name) {
        String value = args.get(name);
        if (value == null || value.isBlank()) throw new IllegalArgumentException("required argument " + name);
        return value;
    }
}
