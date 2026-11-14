package io.jjamtong.analysis;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Independent exact-location expectations across renamed packages and source layouts. */
public final class SourceLocationOracle {
    private SourceLocationOracle() { }

    public static void main(String[] args) throws Exception {
        Path directory = Files.createTempDirectory("jjamtong-source-location-");
        try {
            check(directory.resolve("conventional/src/main/java"), "sample.pipeline");
            check(directory.resolve("remapped/inputs"), "org.example.renamed");
            System.out.println("PASS: two source layouts; 48 cross-file types each; exact files, lines, descriptors and relation sets; deterministic output");
        } finally {
            try (var paths = Files.walk(directory)) {
                for (Path path : paths.sorted(java.util.Comparator.reverseOrder()).toList()) Files.delete(path);
            }
        }
    }

    @SuppressWarnings("unchecked")
    private static void check(Path sources, String prefix) throws Exception {
        String module = "source-location", mainClass = prefix + ".entry.Bootstrap";
        String gateway = prefix + ".shared.Gateway", integer = "(I)I", string = "(Ljava/lang/String;)Ljava/lang/String;";
        String mainDescriptor = "([Ljava/lang/String;)V", mainPath = mainClass.replace('.', '/') + ".java";
        Set<String> expectedMethods = new HashSet<>(), expectedCalls = new HashSet<>();
        List<String> main = new ArrayList<>(List.of("package " + prefix + ".entry;", "public final class Bootstrap {",
                "  public static void main(String[] args) {", "    int value = args.length;"));
        expectedMethods.add(method(mainClass, "main", mainDescriptor, mainPath, 3));
        for (int i = 0; i < 48; i++) {
            String simple = "Leaf" + i, name = prefix + ".segment" + (i % 4) + "." + simple;
            String relative = name.replace('.', '/') + ".java";
            write(sources, relative, List.of("package " + prefix + ".segment" + (i % 4) + ";",
                    "public final class " + simple + " {", "  public static int apply(int value) {",
                    "    return " + gateway + ".pass(value);", "  }", "}"));
            expectedMethods.add(method(name, "apply", integer, relative, 3));
            expectedCalls.add(call(name, "apply", integer, gateway, "pass", integer, relative, 4));
            main.add("    value += " + name + ".apply(value);");
            expectedCalls.add(call(mainClass, "main", mainDescriptor, name, "apply", integer, mainPath, main.size()));
        }
        main.add("    " + gateway + ".pass(\"value\");");
        expectedCalls.add(call(mainClass, "main", mainDescriptor, gateway, "pass", string, mainPath, main.size()));
        main.add("  }"); main.add("}");
        write(sources, mainPath, main);
        String gatewayPath = gateway.replace('.', '/') + ".java";
        write(sources, gatewayPath, List.of("package " + prefix + ".shared;", "public final class Gateway {",
                "  public static int pass(int value) { return value; }",
                "  public static String pass(String value) { return value; }", "}"));
        expectedMethods.add(method(gateway, "pass", integer, gatewayPath, 3));
        expectedMethods.add(method(gateway, "pass", string, gatewayPath, 4));
        var config = new Config(sources, sources.resolve("unused.jar"), module, sources.resolve("unused.json"),
                sources.resolve("unused-output.json"), mainClass, prefix, List.of());
        var result = JavaParserAnalysis.run(config);
        Set<String> methods = new HashSet<>(), calls = new HashSet<>();
        var actualMethods = (List<Map<String, Object>>) result.get("methods");
        var actualCalls = (List<Map<String, Object>>) result.get("calls");
        for (var value : actualMethods) {
            require(module.equals(value.get("module")), "declaration module");
            methods.add(method((String) value.get("class"), (String) value.get("name"), (String) value.get("descriptor"),
                    (String) value.get("source"), ((Number) value.get("line")).intValue()));
        }
        for (var value : actualCalls) {
            var caller = (Map<String, Object>) value.get("caller");
            var target = (Map<String, Object>) value.get("target");
            require(module.equals(caller.get("module")) && module.equals(target.get("module")), "call module");
            require("declared-call".equals(value.get("kind")), "declared relation kind");
            calls.add(call((String) caller.get("class"), (String) caller.get("name"), (String) caller.get("descriptor"),
                    (String) target.get("class"), (String) target.get("name"), (String) target.get("descriptor"),
                    (String) value.get("source"), ((Number) value.get("line")).intValue()));
        }
        require(methods.equals(expectedMethods) && actualMethods.size() == expectedMethods.size(), "exact declarations and locations: " + prefix);
        require(calls.equals(expectedCalls) && actualCalls.size() == expectedCalls.size(), "exact calls and locations: " + prefix);
        require(((List<?>) result.get("unresolved")).isEmpty(), "no unresolved cross-file types");
        require(((List<?>) result.get("excluded")).isEmpty(), "no excluded types");
        require(Model.JSON.toJson(result).equals(Model.JSON.toJson(JavaParserAnalysis.run(config))), "deterministic parser result");
    }

    private static void write(Path root, String relative, List<String> lines) throws Exception {
        Path file = root.resolve(relative); Files.createDirectories(file.getParent());
        Files.writeString(file, String.join("\n", lines) + "\n");
    }

    private static String method(String owner, String name, String descriptor, String source, int line) {
        return owner + "#" + name + descriptor + "@" + source + ":" + line;
    }

    private static String call(String owner, String name, String descriptor, String target, String called,
                               String targetDescriptor, String source, int line) {
        return owner + "#" + name + descriptor + "->" + method(target, called, targetDescriptor, source, line);
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
