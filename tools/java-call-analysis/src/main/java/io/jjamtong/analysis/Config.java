package io.jjamtong.analysis;

import java.nio.file.Path;
import java.util.List;

record Config(Path sourceRoot, Path artifact, String module, Path metadata, Path output,
              String entrypoint, String includePackage, List<String> excludedPackages,
              boolean boot, boolean allMethods) {
    Config(Path sourceRoot, Path artifact, String module, Path metadata, Path output,
           String entrypoint, String includePackage, List<String> excludedPackages) {
        this(sourceRoot, artifact, module, metadata, output, entrypoint, includePackage, excludedPackages, false, false);
    }
    Config withArtifact(Path path) {
        return new Config(sourceRoot, path, module, metadata, output, entrypoint, includePackage, excludedPackages, boot, allMethods);
    }
    boolean included(String className) {
        return inPackage(className, includePackage) && excludedPackages.stream().noneMatch(p -> inPackage(className, p));
    }
    boolean excluded(String className) { return excludedPackages.stream().anyMatch(p -> inPackage(className, p)); }
    private static boolean inPackage(String className, String packageName) {
        return className.equals(packageName) || className.startsWith(packageName + ".");
    }
}
