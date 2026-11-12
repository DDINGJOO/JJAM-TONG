# Java call-analysis comparison adapters

Experimental local CLI for **two separate kinds of static evidence**. This is not a product dependency decision or a guarantee of all Java calls.

| Adapter | Pinned version | Meaning |
| --- | --- | --- |
| JavaParser + SymbolSolver | 3.28.2 | The declaration selected by source-level method resolution. An interface declaration is not an implementation call. |
| WALA core/util/shrike | 1.9.0 | CHA (class hierarchy analysis) possible callees reachable from a configured `main` entrypoint. Candidates are not observed execution. |

The tool emits JVM method descriptors, including return types, and module/class/name/descriptor keys. Source declarations, bytecode-generated methods and constructors can differ. No trace data is created here.

## Build and verify

The build uses the existing local `maven:3.9.9-eclipse-temurin-21` Docker image (`--pull=never`) and an isolated `.local/method-analysis-m2` cache. It reads published Maven Central binaries and compiles this adapter with `--release 17`.

```sh
python3 tools/java-call-analysis/build.py
python3 tools/java-call-analysis/verify.py --java-home /path/to/jdk17
python3 tools/java-call-analysis/verify.py --java-home /path/to/jdk21
```

`build.py` compiles the oracle; `verify.py` actually executes it. Maven's package success alone does not mean the oracle ran. The test compiles a tiny synthetic source/JAR pair, checks private/self calls, distinct overload descriptors, both interface implementation candidates in WALA, reflection and native gaps, byte-for-byte deterministic output, actual scope exclusion, and failure on empty results. Temporary oracle inputs are deleted after execution.

Build products are `target/java-call-analysis-0.1.0.jar`, `target/dependency/*.jar` and `target/dependency-sha256.json`. The CLI is a plain JAR plus classpath, not a fat JAR or agent. WALA **source builds** have different toolchain requirements; no JDK 27 is needed to run the published WALA 1.9.0 binaries used here. The verified execution matrix for this adapter is JDK 17 and 21, with target classfile major versions at most 61 (Java 17).

## Analyze controlled local inputs

```sh
python3 tools/java-call-analysis/analyze.py \
  --java-home /path/to/jdk17 \
  --source-root /path/to/target/src/main/java \
  --artifact /path/to/target/plain.jar \
  --module method-fixture \
  --metadata /path/to/build-identity.json \
  --output /path/to/methods.json
```

The metadata input is a caller-controlled JSON object, copied under `metadata`. The integration layer owns validation of its repository/revision/build/module/artifact identity. Input source/JAR digests are computed before and after both analyses to reject concurrent input changes. They do not prove that the JAR was compiled from that source; the caller must check its build manifest.

Actual filter options (aliases in parentheses):

- `--include-package fixture.board` (`--include-prefix fixture.board.`): include that package and descendants; an exact class also matches. Default `fixture.board`.
- `--exclude-package fixture.board.excluded` (`--exclude-prefix`): repeatable package or exact-class exclusion. Default `fixture.board.excluded` if none is supplied. Supplying an exclusion replaces that default list.
- `--entrypoint fixture.board.Main` (`--entry-class`): an application class with exactly one public static `main(String[])` entrypoint. Default `fixture.board.Main`.

Exclusion filters the reported method inventory and edges in both adapters. WALA still builds the class hierarchy from the full JAR, so exclusion is a reporting scope, not a claim that excluded classes cannot affect resolution. Excluded declarations and calls crossing that scope remain in `excluded`/`unresolved`. Configuration is included in `scope`, `entrypoints` and the WALA policy fields. For example, excluding `fixture.board.CachedRepository` really removes its output methods/edges; changing only metadata does not change analysis behavior.

The runner gives the JVM `-Xmx1g` and a 60-second deadline. Output has a 10 MiB limit and is atomically published only after both adapters succeed. A failure preserves any previous output file; callers must check the process exit status and must not treat that old output as a new result. An empty included method or call result is a failure. Input must be a plain JAR; Spring Boot nested executable JARs are rejected. No arbitrary target application code is executed by the analysis CLI.

## Output contract

```json
{
  "schema": "jjamtong.methods.v1",
  "status": "complete-with-limitations",
  "module": "method-fixture",
  "metadata": {},
  "input": {
    "artifactSha256": "...",
    "classInputSha256": "...",
    "sourceTreeSha256": "...",
    "metadataInputSha256": "..."
  },
  "scope": {"includePackage": "fixture.board", "excludedPackages": ["fixture.board.excluded"]},
  "provenance": {},
  "tools": {
    "javaparser": {
      "version": "3.28.2",
      "kind": "declaration-resolution",
      "methods": [{"module": "method-fixture", "class": "fixture.board.Service", "name": "handle", "descriptor": "(Ljava/lang/String;)Ljava/lang/String;", "native": false, "abstract": false, "hasBody": true, "source": "fixture/board/Service.java", "line": 10}],
      "calls": [{"caller": {"module": "method-fixture", "class": "fixture.board.Service", "name": "handle", "descriptor": "(Ljava/lang/String;)Ljava/lang/String;"}, "target": {"module": "method-fixture", "class": "fixture.board.Service", "name": "hidden", "descriptor": "(Ljava/lang/String;)Ljava/lang/String;"}, "kind": "declared-call", "source": "fixture/board/Service.java", "line": 11}],
      "unresolved": [],
      "excluded": []
    },
    "wala": {
      "version": "1.9.0",
      "algorithm": "CHA",
      "reflectionPolicy": "not-inferred",
      "entrypoints": [],
      "methods": [],
      "calls": [],
      "unresolved": [],
      "excluded": []
    }
  },
  "limitations": []
}
```

This is an illustrative shape, not a successful empty result. WALA methods use the same four key fields plus `native`, `abstract`, `hasBody` and `reachable`; its calls use `kind: possible-call` and `bytecodeIndex`. JavaParser constructor edges use `declared-constructor-call`. `classInputSha256` identifies the entire supplied plain JAR, identical to `artifactSha256`, rather than a normalized class-only digest. `sourceTreeSha256` hashes sorted relative `.java` paths plus each file SHA-256. Same inputs/configuration/JVM yield sorted deterministic JSON without timestamps or absolute source paths.

The adapters explicitly mark unresolved reflection targets, native/no-body methods, resolution failures and excluded calls. JavaParser skips lambda bodies instead of assigning their calls to the enclosing method, and records lambda/method-reference gaps. Initializers, constructor chaining, generated/bridge methods and dependencies beyond the JDK are not modeled as equivalent source/bytecode relationships. WALA's inventory includes unreachable application methods, but its edges are entrypoint-reachable CHA candidates. No missing edge proves that a runtime call is impossible.

## Upstream evidence and licenses

`dependency-provenance.json` records the exact direct binary hashes, upstream commits, official POM hashes and original license hashes. `build.py` checks the direct binary hashes and generates the full resolved dependency hash manifest. The JavaParser Apache-2.0 option is selected from its dual-license declaration; WALA is EPL-2.0. Gson 2.14.0 is WALA's existing runtime dependency, promoted to compile scope for JSON I/O.

API implementations were checked against the pinned originals: [JavaParser method descriptors](https://github.com/javaparser/javaparser/blob/e72889831e5e06532f2185ec9ae16531237f9f69/javaparser-core/src/main/java/com/github/javaparser/resolution/declarations/ResolvedMethodDeclaration.java), [WALA CHA constructors, initialization and reachability](https://github.com/wala/WALA/blob/ab3bd3b2b9291e047b203cddd248cbbcfcff6f1e/core/src/main/java/com/ibm/wala/ipa/callgraph/cha/CHACallGraph.java), and [WALA binary scope loading](https://github.com/wala/WALA/blob/ab3bd3b2b9291e047b203cddd248cbbcfcff6f1e/core/src/main/java/com/ibm/wala/core/util/config/AnalysisScopeReader.java). The license originals are [JavaParser Apache-2.0](https://github.com/javaparser/javaparser/blob/e72889831e5e06532f2185ec9ae16531237f9f69/LICENSE.APACHE) and [WALA EPL-2.0](https://github.com/wala/WALA/blob/ab3bd3b2b9291e047b203cddd248cbbcfcff6f1e/LICENSE).
