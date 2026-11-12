package io.jjamtong.analysis;

import com.ibm.wala.classLoader.IMethod;
import com.ibm.wala.core.util.config.AnalysisScopeReader;
import com.ibm.wala.ipa.callgraph.cha.CHACallGraph;
import com.ibm.wala.ipa.callgraph.impl.Util;
import com.ibm.wala.ipa.cha.ClassHierarchyFactory;
import com.ibm.wala.types.ClassLoaderReference;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

final class WalaAnalysis {
    private WalaAnalysis() { }
    static Map<String, Object> run(Config config) throws Exception {
        var scope = AnalysisScopeReader.instance.makeJavaBinaryAnalysisScope(config.artifact().toString(), null);
        var hierarchy = ClassHierarchyFactory.make(scope);
        var graph = new CHACallGraph(hierarchy, true);
        var entrypoints = Util.makeMainEntrypoints(hierarchy, "L" + config.entrypoint().replace('.', '/'));
        List<Map<String, Object>> entrypointKeys = new ArrayList<>();
        entrypoints.forEach(e -> entrypointKeys.add(key(config, e.getMethod())));
        if (entrypointKeys.size() != 1) throw new IllegalArgumentException("WALA requires exactly one included main entrypoint");
        graph.init(entrypoints);
        List<Map<String, Object>> methods = new ArrayList<>(), calls = new ArrayList<>(), unresolved = new ArrayList<>(), excluded = new ArrayList<>();
        Set<Map<String, Object>> reachable = new HashSet<>();
        for (var node : graph) {
            var method = node.getMethod();
            if (!application(method) || !config.included(className(method))) continue;
            var caller = key(config, method); reachable.add(caller);
            var sites = node.iterateCallSites();
            while (sites.hasNext()) {
                var site = sites.next();
                String declaredClass = site.getDeclaredTarget().getDeclaringClass().getName().toString().substring(1).replace('/', '.');
                String declaredName = site.getDeclaredTarget().getName().toString();
                if (JavaParserAnalysis.reflection(declaredClass, declaredName)) unresolved.add(Model.obj("caller", caller, "reason", "reflection-target-not-inferred", "bytecodeIndex", site.getProgramCounter()));
                var targets = graph.getPossibleTargets(node, site);
                boolean includedTarget = false;
                for (var targetNode : targets) {
                    var target = targetNode.getMethod();
                    if (!application(target)) continue;
                    if (config.included(className(target))) {
                        calls.add(Model.obj("caller", caller, "target", key(config, target), "kind", "possible-call", "bytecodeIndex", site.getProgramCounter()));
                        includedTarget = true;
                    } else if (config.excluded(className(target))) unresolved.add(Model.obj("caller", caller, "target", key(config, target), "reason", "excluded-package-call", "bytecodeIndex", site.getProgramCounter()));
                }
                if (!includedTarget && config.included(declaredClass)) unresolved.add(Model.obj("caller", caller, "reason", "no-included-CHA-target", "bytecodeIndex", site.getProgramCounter()));
            }
        }
        for (var type : hierarchy) {
            if (!type.getClassLoader().getReference().equals(ClassLoaderReference.Application)) continue;
            for (var method : type.getDeclaredMethods()) {
                var methodKey = key(config, method);
                if (!config.included(className(method))) {
                    excluded.add(Model.obj("method", methodKey, "reason", config.excluded(className(method)) ? "excluded-package" : "outside-include-package"));
                    continue;
                }
                var definition = new java.util.TreeMap<String, Object>(methodKey);
                definition.putAll(Model.obj("native", method.isNative(), "abstract", method.isAbstract(), "hasBody", !method.isNative() && !method.isAbstract(), "reachable", reachable.contains(methodKey)));
                methods.add(definition);
                if (method.isNative() || method.isAbstract()) unresolved.add(Model.obj("method", methodKey, "reason", method.isNative() ? "native-body-unavailable" : "no-body-declaration"));
            }
        }
        if (methods.isEmpty() || calls.isEmpty()) throw new IllegalStateException("WALA produced no included methods or calls");
        return Model.obj("version", "1.9.0", "algorithm", "CHA", "kind", "static-possible-call", "applicationOnly", true, "entrypoints", Model.sorted(entrypointKeys), "reflectionPolicy", "not-inferred", "reachability", "entrypoint-reachable-call-edges-only", "methods", Model.sorted(methods), "calls", Model.sorted(calls), "unresolved", Model.sorted(unresolved), "excluded", Model.sorted(excluded));
    }
    private static boolean application(IMethod method) { return method.getDeclaringClass().getClassLoader().getReference().equals(ClassLoaderReference.Application); }
    private static String className(IMethod method) { return method.getDeclaringClass().getName().toString().substring(1).replace('/', '.'); }
    private static Map<String, Object> key(Config config, IMethod method) { return Model.key(config.module(), className(method), method.getName().toString(), method.getDescriptor().toString()); }
}
