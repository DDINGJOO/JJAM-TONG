package io.jjamtong.analysis;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.jar.JarEntry;
import java.util.jar.JarOutputStream;
import javax.tools.ToolProvider;

/** Tiny synthetic accuracy oracle; no external target business source is embedded here. */
public final class SyntheticOracle {
    private SyntheticOracle() { }
    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        Path directory = Files.createTempDirectory("jjamtong-method-oracle-");
        try {
            Path sources = directory.resolve("src"), file = sources.resolve("fixture/board/Main.java");
            Files.createDirectories(file.getParent());
            Files.writeString(file, """
                package fixture.board;
                public class Main {
                    public static void main(String[] args) throws Exception {
                        Service service = new Service(new A());
                        service.handle("ok"); new B().load("ok");
                        nested(new Input[1][]); generic(new Input());
                        Service.class.getDeclaredMethod("hidden", String.class).invoke(service, "ok");
                    }
                    public static class Input { }
                    public static Input[][] nested(Input[][] value) { return value; }
                    public static <T extends Input> T generic(T value) { return value; }
                }
                interface Repo { String load(String value); }
                class A implements Repo { public String load(String value) { return value; } }
                class B implements Repo { public String load(String value) { return value; } }
                class Service {
                    private final Repo repo;
                    Service(Repo repo) { this.repo = repo; }
                    public String handle(String value) { return hidden(value) + overload(1) + repo.load(value); }
                    private String hidden(String value) { return overload(value); }
                    private String overload(String value) { return value; }
                    private int overload(int value) { return value; }
                    native int unsupported();
                }
                """);
            Path classes = directory.resolve("classes"); Files.createDirectories(classes);
            int compilation = ToolProvider.getSystemJavaCompiler().run(null, null, null, "--release", "17", "-d", classes.toString(), file.toString());
            require(compilation == 0, "synthetic compile");
            Path jar = directory.resolve("oracle.jar");
            try (var output = new JarOutputStream(Files.newOutputStream(jar)); var paths = Files.walk(classes)) {
                for (Path path : paths.filter(Files::isRegularFile).sorted().toList()) {
                    output.putNextEntry(new JarEntry(classes.relativize(path).toString().replace('\\', '/')));
                    output.write(Files.readAllBytes(path)); output.closeEntry();
                }
            }
            Path metadata = directory.resolve("metadata.json"), result = directory.resolve("result.json");
            Files.writeString(metadata, "{\"revision\":\"synthetic\",\"build\":\"oracle\"}");
            var config = new Config(sources, jar, "oracle", metadata, result, "fixture.board.Main", "fixture.board", List.of("fixture.board.excluded"));
            Main.analyze(config);
            byte[] first = Files.readAllBytes(result);
            var tools = Model.JSON.fromJson(Files.readString(result), com.google.gson.JsonObject.class).getAsJsonObject("tools");
            for (String tool : List.of("javaparser", "wala")) {
                var analysis = tools.getAsJsonObject(tool);
                var edges = Model.JSON.fromJson(analysis.getAsJsonArray("calls"), List.class);
                require(edge(edges, "main", "nested", "([[Lfixture/board/Main$Input;)[[Lfixture/board/Main$Input;"), tool + " nested binary-name array descriptor");
                require(edge(edges, "main", "generic", "(Lfixture/board/Main$Input;)Lfixture/board/Main$Input;"), tool + " bounded generic erasure descriptor");
                require(edge(edges, "handle", "hidden", "(Ljava/lang/String;)Ljava/lang/String;"), tool + " private self-call");
                require(edge(edges, "hidden", "overload", "(Ljava/lang/String;)Ljava/lang/String;"), tool + " reference overload");
                require(edge(edges, "handle", "overload", "(I)I"), tool + " primitive overload");
                require(analysis.getAsJsonArray("unresolved").asList().stream().anyMatch(v -> v.getAsJsonObject().get("reason").getAsString().equals("reflection-target-not-inferred")), tool + " reflection gap");
                require(analysis.getAsJsonArray("methods").asList().stream().anyMatch(v -> v.getAsJsonObject().get("native").getAsBoolean()), tool + " native flag");
            }
            var walaEdges = (List<Map<String, Object>>) Model.JSON.fromJson(tools.getAsJsonObject("wala").getAsJsonArray("calls"), List.class);
            for (String implementation : List.of("fixture.board.A", "fixture.board.B")) {
                require(walaEdges.stream().anyMatch(e -> ((Map<?, ?>) e.get("caller")).get("name").equals("handle") && ((Map<?, ?>) e.get("target")).get("class").equals(implementation) && ((Map<?, ?>) e.get("target")).get("name").equals("load")), "CHA interface candidate " + implementation);
            }
            Main.analyze(config);
            require(java.util.Arrays.equals(first, Files.readAllBytes(result)), "deterministic same-input output");
            var narrowed = new Config(sources, jar, "oracle", metadata, result, "fixture.board.Main", "fixture.board", List.of("fixture.board.B"));
            Main.analyze(narrowed);
            var narrowedTools = Model.JSON.fromJson(Files.readString(result), com.google.gson.JsonObject.class).getAsJsonObject("tools");
            for (String tool : List.of("javaparser", "wala")) require(narrowedTools.getAsJsonObject(tool).getAsJsonArray("methods").asList().stream().noneMatch(v -> v.getAsJsonObject().get("class").getAsString().equals("fixture.board.B")), tool + " actual scope exclusion");
            boolean failed = false;
            try { JavaParserAnalysis.run(new Config(sources, jar, "oracle", metadata, result, "fixture.board.Main", "absent", List.of())); }
            catch (IllegalStateException expected) { failed = true; }
            require(failed, "empty analysis is failure");
            System.out.println("PASS: JP/WALA private, self, both overloads, reflection gaps, native flags; CHA two interface candidates; deterministic bytes; actual exclusion; empty-result failure");
        } finally {
            try (var paths = Files.walk(directory)) { for (Path path : paths.sorted(java.util.Comparator.reverseOrder()).toList()) Files.delete(path); }
        }
    }
    private static boolean edge(List<Map<String, Object>> edges, String caller, String target, String descriptor) {
        return edges.stream().anyMatch(e -> ((Map<?, ?>) e.get("caller")).get("name").equals(caller) && ((Map<?, ?>) e.get("target")).get("name").equals(target) && ((Map<?, ?>) e.get("target")).get("descriptor").equals(descriptor));
    }
    private static void require(boolean condition, String label) { if (!condition) throw new AssertionError(label); }
}
