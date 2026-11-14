package io.jjamtong.analysis;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.CallableDeclaration;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.expr.LambdaExpr;
import com.github.javaparser.ast.expr.MethodReferenceExpr;
import com.github.javaparser.ast.expr.ObjectCreationExpr;
import com.github.javaparser.resolution.types.ResolvedType;
import com.github.javaparser.resolution.declarations.ResolvedConstructorDeclaration;
import com.github.javaparser.resolution.declarations.ResolvedMethodDeclaration;
import com.github.javaparser.resolution.declarations.ResolvedReferenceTypeDeclaration;
import com.github.javaparser.symbolsolver.JavaSymbolSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.CombinedTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.JarTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.JavaParserTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.ReflectionTypeSolver;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;

final class JavaParserAnalysis {
    private static final int TYPE_SOLVER_CACHE_ENTRIES = 32;
    private JavaParserAnalysis() { }

    static Map<String, Object> run(Config config) throws Exception {
        return run(config, List.of());
    }
    static Map<String, Object> run(Config config, List<Path> dependencies) throws Exception {
        var parserConfig = new ParserConfiguration().setLanguageLevel(config.boot() ? ParserConfiguration.LanguageLevel.JAVA_21 : ParserConfiguration.LanguageLevel.JAVA_17);
        // Direct parsing keeps token-backed source positions. Cached lookup units
        // only resolve types; retaining their tokens duplicates the source graph.
        var lookupConfig = new ParserConfiguration().setLanguageLevel(parserConfig.getLanguageLevel())
                .setStoreTokens(false).setAttributeComments(false);
        var solver = new CombinedTypeSolver(new JavaParserTypeSolver(config.sourceRoot(), lookupConfig, TYPE_SOLVER_CACHE_ENTRIES), new ReflectionTypeSolver());
        for (Path dependency : dependencies) solver.add(new JarTypeSolver(dependency));
        var resolver = new JavaSymbolSolver(solver);
        parserConfig.setSymbolResolver(resolver);
        lookupConfig.setSymbolResolver(resolver);
        var parser = new JavaParser(parserConfig);
        List<Map<String, Object>> methods = new ArrayList<>(), calls = new ArrayList<>(), unresolved = new ArrayList<>(), excluded = new ArrayList<>();
        try (var paths = Files.walk(config.sourceRoot())) {
            for (Path source : paths.filter(Files::isRegularFile).filter(p -> p.toString().endsWith(".java")).sorted().toList()) {
                var parse = parser.parse(source);
                if (!parse.isSuccessful() || parse.getResult().isEmpty()) throw new IllegalArgumentException("JavaParser source parse failed: " + config.sourceRoot().relativize(source));
                var unit = parse.getResult().orElseThrow();
                String relative = config.sourceRoot().relativize(source).toString().replace('\\', '/');
                Map<Node, Map<String, Object>> owners = new IdentityHashMap<>();
                for (CallableDeclaration<?> declaration : unit.findAll(CallableDeclaration.class)) {
                    try {
                        Map<String, Object> key;
                        boolean nativeMethod = false, abstractMethod = false, body;
                        if (declaration instanceof MethodDeclaration method) {
                            key = key(config, method.resolve()); nativeMethod = method.isNative(); abstractMethod = method.isAbstract(); body = method.getBody().isPresent();
                        } else if (declaration instanceof ConstructorDeclaration constructor) {
                            key = key(config, constructor.resolve()); body = true;
                        } else continue;
                        String className = (String) key.get("class");
                        if (!config.included(className)) {
                            excluded.add(Model.obj("method", key, "reason", config.excluded(className) ? "excluded-package" : "outside-include-package"));
                            continue;
                        }
                        owners.put(declaration, key);
                        var definition = new java.util.TreeMap<String, Object>(key);
                        definition.putAll(Model.obj("native", nativeMethod, "abstract", abstractMethod, "hasBody", body, "source", relative, "line", line(declaration)));
                        methods.add(definition);
                        if (!body) unresolved.add(Model.obj("method", key, "reason", nativeMethod ? "native-body-unavailable" : "no-body-declaration"));
                    } catch (RuntimeException failure) {
                        unresolved.add(Model.obj("reason", "declaration-resolution-failed", "failureType", failure.getClass().getSimpleName(), "source", relative, "line", line(declaration)));
                    }
                }
                for (MethodCallExpr call : unit.findAll(MethodCallExpr.class)) {
                    var caller = owner(call, owners);
                    if (caller == null) continue;
                    try {
                        var target = key(config, call.resolve());
                        String targetClass = (String) target.get("class");
                        if (reflection(targetClass, (String) target.get("name"))) unresolved.add(Model.obj("caller", caller, "reason", "reflection-target-not-inferred", "line", line(call), "source", relative));
                        if (config.included(targetClass)) calls.add(Model.obj("caller", caller, "target", target, "kind", "declared-call", "source", relative, "line", line(call)));
                        else if (config.excluded(targetClass)) unresolved.add(Model.obj("caller", caller, "target", target, "reason", "excluded-package-call", "line", line(call), "source", relative));
                    } catch (RuntimeException failure) {
                        unresolved.add(Model.obj("caller", caller, "reason", "call-resolution-failed", "failureType", failure.getClass().getSimpleName(), "source", relative, "line", line(call)));
                    }
                }
                for (LambdaExpr lambda : unit.findAll(LambdaExpr.class)) {
                    var caller = owner(lambda, owners);
                    if (caller != null) unresolved.add(Model.obj("caller", caller, "reason", "lambda-body-not-attributed-to-enclosing-method", "source", relative, "line", line(lambda)));
                }
                for (MethodReferenceExpr reference : unit.findAll(MethodReferenceExpr.class)) {
                    var caller = owner(reference, owners);
                    if (caller != null) unresolved.add(Model.obj("caller", caller, "reason", "method-reference-not-expanded", "source", relative, "line", line(reference)));
                }
                for (ObjectCreationExpr creation : unit.findAll(ObjectCreationExpr.class)) {
                    var caller = owner(creation, owners);
                    if (caller == null) continue;
                    try {
                        var target = key(config, creation.resolve());
                        if (config.included((String) target.get("class"))) calls.add(Model.obj("caller", caller, "target", target, "kind", "declared-constructor-call", "source", relative, "line", line(creation)));
                    } catch (RuntimeException failure) {
                        unresolved.add(Model.obj("caller", caller, "reason", "constructor-resolution-failed", "failureType", failure.getClass().getSimpleName(), "source", relative, "line", line(creation)));
                    }
                }
            }
        }
        if (methods.isEmpty() || calls.isEmpty()) throw new IllegalStateException("JavaParser produced no included methods or calls");
        return Model.obj("version", "3.28.2", "kind", "declaration-resolution", "languageLevel", config.boot() ? "JAVA_21" : "JAVA_17", "methods", Model.sorted(methods), "calls", Model.sorted(calls), "unresolved", Model.sorted(unresolved), "excluded", Model.sorted(excluded));
    }

    private static Map<String, Object> key(Config config, ResolvedMethodDeclaration method) {
        StringBuilder descriptor = new StringBuilder("(");
        for (int i = 0; i < method.getNumberOfParams(); i++) descriptor.append(descriptor(method.getParam(i).getType(), 0));
        return Model.key(config.module(), binaryName(method.declaringType()), method.getName(),
                descriptor.append(")").append(descriptor(method.getReturnType(), 0)).toString());
    }
    private static Map<String, Object> key(Config config, ResolvedConstructorDeclaration constructor) {
        StringBuilder descriptor = new StringBuilder("(");
        for (int i = 0; i < constructor.getNumberOfParams(); i++) descriptor.append(descriptor(constructor.getParam(i).getType(), 0));
        return Model.key(config.module(), binaryName(constructor.declaringType()), "<init>", descriptor.append(")V").toString());
    }
    private static String descriptor(ResolvedType type, int depth) {
        if (depth > 16) throw new IllegalArgumentException("recursive type erasure");
        if (type.isArray()) return "[" + descriptor(type.asArrayType().getComponentType(), depth + 1);
        if (type.isTypeVariable()) return descriptor(type.erasure(), depth + 1);
        if (type.isReferenceType()) return "L" + binaryName(type.asReferenceType().getTypeDeclaration().orElseThrow()).replace('.', '/') + ";";
        return type.toDescriptor();
    }
    private static String binaryName(ResolvedReferenceTypeDeclaration declaration) {
        String prefix = declaration.getPackageName();
        return (prefix.isEmpty() ? "" : prefix + ".") + declaration.getClassName().replace('.', '$');
    }
    private static int line(Node node) { return node.getBegin().map(p -> p.line).orElse(-1); }
    private static Map<String, Object> owner(Node node, Map<Node, Map<String, Object>> owners) {
        Node current = node;
        while (current.getParentNode().isPresent()) {
            current = current.getParentNode().orElseThrow();
            if (current instanceof LambdaExpr) return null;
            if (current instanceof CallableDeclaration<?>) return owners.get(current);
        }
        return null;
    }
    static boolean reflection(String className, String method) {
        return className.startsWith("java.lang.reflect.") || (className.equals("java.lang.Class") && (method.startsWith("getDeclared") || method.equals("getMethod") || method.equals("forName")));
    }
}
