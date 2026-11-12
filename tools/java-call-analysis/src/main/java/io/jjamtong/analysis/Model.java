package io.jjamtong.analysis;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

final class Model {
    static final Gson JSON = new GsonBuilder().disableHtmlEscaping().setPrettyPrinting().create();
    private Model() { }

    static Map<String, Object> obj(Object... pairs) {
        Map<String, Object> result = new TreeMap<>();
        for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1]);
        return result;
    }

    static Map<String, Object> key(String module, String className, String name, String descriptor) {
        return obj("module", module, "class", className, "name", name, "descriptor", descriptor);
    }

    static List<Map<String, Object>> sorted(List<Map<String, Object>> values) {
        return values.stream().distinct().sorted(Comparator.comparing(JSON::toJson)).toList();
    }

    static String sha256(byte[] bytes) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)); }
        catch (NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }

    static String sha256(Path path) throws IOException { return sha256(Files.readAllBytes(path)); }

    static String sourceDigest(Path root) throws IOException {
        List<String> entries = new ArrayList<>();
        try (var paths = Files.walk(root)) {
            for (Path path : paths.filter(Files::isRegularFile).filter(p -> p.toString().endsWith(".java")).sorted().toList()) {
                entries.add(root.relativize(path).toString().replace('\\', '/') + "\0" + sha256(path) + "\n");
            }
        }
        return sha256(String.join("", entries).getBytes(StandardCharsets.UTF_8));
    }
}
