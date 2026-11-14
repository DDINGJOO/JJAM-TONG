import com.github.javaparser.*;
import com.github.javaparser.ast.*;
import com.github.javaparser.ast.body.*;
import com.github.javaparser.ast.expr.*;
import com.github.javaparser.ast.stmt.*;
import com.github.javaparser.resolution.declarations.*;
import com.github.javaparser.symbolsolver.JavaSymbolSolver;
import com.github.javaparser.symbolsolver.javaparsermodel.JavaParserFacade;
import com.github.javaparser.symbolsolver.resolution.typesolvers.*;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.time.*;
import java.util.*;
import java.util.stream.*;

/** Conservative source declaration index; it never runs target code or reads target configuration. */
public final class SourceIndex {
  static final Gson JSON=new GsonBuilder().disableHtmlEscaping().create();
  static final Map<String,Map<String,Object>> METHODS=new TreeMap<>();
  static final Map<String,List<String>> DECLARATIONS=new HashMap<>();
  static final Map<String,Map<String,Integer>> DIAG_COUNTS=new TreeMap<>();
  static final Map<String,Integer> LIMIT_COUNTS=new TreeMap<>(), MODULE_FILES=new TreeMap<>();
  static final List<Map<String,Object>> EDGES=new ArrayList<>(), ROUTES=new ArrayList<>();
  static final List<Map<String,Object>> CALLS=new ArrayList<>();
  static final List<Map<String,Object>> FILE_DIAGNOSTICS=new ArrayList<>();
  static final Map<CallableDeclaration<?>,String> CALLABLE_IDS=new IdentityHashMap<>();
  static final Set<String> SOURCE_CLASSES=new HashSet<>();
  static int files,parsed,failed,abstractCount,unresolved,externalCalls;
  static Path source; static String label;
  static final int CACHE=32, MAX_GUARD_DEPTH=16, MAX_GUARD_LENGTH=512;

  public static void main(String[] a) throws Exception {
    Map<String,String> args=arguments(a); source=Path.of(req(args,"--source")).toRealPath();
    Path output=Path.of(req(args,"--output")); label=args.getOrDefault("--label","service");
    long started=System.nanoTime(); String revisionBefore=git("rev-parse","HEAD");
    List<Path> roots=roots(source), java=files(roots); String pre=digest(java); files=java.size();
    ParserConfiguration parseCfg=new ParserConfiguration().setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_21).setStoreTokens(false).setAttributeComments(false);
    MemoryTypeSolver memory=new MemoryTypeSolver();
    CombinedTypeSolver solver=new CombinedTypeSolver(memory,new ReflectionTypeSolver());
    JavaSymbolSolver resolver=new JavaSymbolSolver(solver); parseCfg.setSymbolResolver(resolver);
    JavaParser parser=new JavaParser(parseCfg); List<Unit> units=new ArrayList<>();
    for(Path p:java) { MODULE_FILES.merge(module(p,roots),1,Integer::sum); try {
      ParseResult<CompilationUnit> result=parser.parse(p);
      if(!result.isSuccessful()||result.getResult().isEmpty()){fileFailure(p,roots);continue;}
      parsed++; units.add(new Unit(p,result.getResult().orElseThrow(),module(p,roots),relative(p)));
    } catch(Exception e) { fileFailure(p,roots); } }
    // Reuse the ASTs already parsed; missing dependency types must not trigger disk reparsing.
    Map<String,List<TypeDeclaration<?>>> types=new TreeMap<>();
    for(Unit u:units) for(TypeDeclaration<?> type:u.cu.findAll(TypeDeclaration.class))
      types.computeIfAbsent(clazz(type),k->new ArrayList<>()).add(type);
    JavaParserFacade facade=JavaParserFacade.get(solver);
    SOURCE_CLASSES.addAll(types.keySet());
    for(var entry:types.entrySet()) {
      if(entry.getValue().size()!=1){limit("AMBIGUOUS_SOURCE_TYPE");continue;}
      try { memory.addDeclaration(entry.getKey(),facade.getTypeDeclaration(entry.getValue().get(0))); }
      catch(Exception error){limit("UNSUPPORTED_SOURCE_TYPE");}
    }
    for(Unit u:units) declarations(u);
    for(Unit u:units) calls(u);
    List<Path> postFiles=files(roots(source)); String post=digest(postFiles), revisionAfter=git("rev-parse","HEAD");
    if(!samePaths(java,postFiles)||!pre.equals(post)||!Objects.equals(revisionBefore,revisionAfter))
      throw new IllegalStateException("selected source or git revision changed during collection; no exact snapshot published");
    Map<String,Object> service=obj("name",label,"revision",revisionBefore,"dirty",!git("status","--porcelain").isEmpty(),"sourceSha256",pre,"capturedAt",Instant.now().toString(),"scope","SOURCE_DECLARATIONS","runtime","not-collected","artifact","not-linked");
    List<Map<String,Object>> modules=MODULE_FILES.keySet().stream().map(m->obj("id",m,"name",m,"sourceFiles",MODULE_FILES.get(m),"methods",(int)METHODS.values().stream().filter(x->m.equals(x.get("module"))).count(),"routes",(int)ROUTES.stream().filter(x->m.equals(x.get("module"))).count())).toList();
    Map<String,Object> metrics=obj("sourceFiles",files,"parsedFiles",parsed,"failedFiles",failed,"methodCount",METHODS.size(),"routeCount",ROUTES.size(),"edgeCount",EDGES.size(),"unresolvedCallCount",unresolved,"externalCallCount",externalCalls,"abstractDeclarations",abstractCount,"analysisSeconds",(System.nanoTime()-started)/1_000_000_000.0,"maxRssBytes",0);
    metrics.put("callSiteCount",CALLS.size());
    Map<String,Object> out=obj("schema","jjamtong.service-source.v1","service",service,"metrics",metrics,"modules",modules,"limitations",limits(),"methods",new ArrayList<>(METHODS.values()),"endpoints",ROUTES,"edges",EDGES,"calls",CALLS,"diagnostics",diagnostics(),"provenance",obj("javaVersion",System.getProperty("java.version"),"parser","JavaParser 3.28.2","typePolicy","unique source AST declarations in memory; JDK reflection; no target dependency classpath","parsePolicy","JAVA_21; unsuccessful or partial parse rejected","guardPolicy","lexical branch guards only; not execution proof","snapshotPolicy","root-relative deterministic framed bytes; source-set and git revision rechecked"));
    out.put("fileDiagnostics",FILE_DIAGNOSTICS);
    Path parent=output.toAbsolutePath().getParent(); if(parent==null)throw new IllegalArgumentException("output requires a parent directory"); Files.createDirectories(parent);
    Files.writeString(output,JSON.toJson(out)+"\n",StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW);
  }
  static void declarations(Unit u) {
    for(CallableDeclaration<?> d:u.cu.findAll(CallableDeclaration.class)) {
      String cls=clazz(d), name=d instanceof ConstructorDeclaration?"<init>":d.getNameAsString(), sig=signature(d), id=stableId(u.module+":"+cls+"#"+name+sig+"@"+u.path+":"+line(d));
      CALLABLE_IDS.put(d,id);
      boolean abs=d instanceof MethodDeclaration m&&m.getBody().isEmpty()&&!m.isNative(); if(abs)abstractCount++;
      String visibility=d.isPublic()?"public":d.isProtected()?"protected":d.isPrivate()?"private":"package";
      List<String> noise=new ArrayList<>();if(d instanceof ConstructorDeclaration)noise.add("constructor");if(accessor(d))noise.add("simple-accessor");
      METHODS.put(id,obj("id",id,"module",u.module,"className",cls,"name",name,"signature",sig,"path",u.path,"line",line(d),"kind",d instanceof ConstructorDeclaration?"constructor":"method","visibility",visibility,"abstract",abs,"static",d.isStatic(),"incoming",0,"outgoing",0,"noiseReasons",noise));
      DECLARATIONS.computeIfAbsent(key(cls,name,sig),k->new ArrayList<>()).add(id); routes(u,d,id,cls);
    }
  }
  static String stableId(String value) {
    try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}
    catch(NoSuchAlgorithmException error){throw new IllegalStateException(error);}
  }
  static void fileFailure(Path path,List<Path> roots) {
    failed++;limit("PARSE_FAILURE");
    FILE_DIAGNOSTICS.add(obj("code","PARSE_FAILURE","path",relative(path),"module",module(path,roots),"message","Source file could not be parsed completely; declarations and calls are unknown."));
  }
  static void calls(Unit u) { for(CallableDeclaration<?> d:u.cu.findAll(CallableDeclaration.class)) {
    String src=CALLABLE_IDS.get(d);
    if(!METHODS.containsKey(src)||(d instanceof MethodDeclaration m&&m.getBody().isEmpty()))continue;
    for(MethodCallExpr call:d.findAll(MethodCallExpr.class))if(ownedBy(d,call,src))edge(src,call);
    for(ObjectCreationExpr call:d.findAll(ObjectCreationExpr.class))if(ownedBy(d,call,src))edge(src,call);
  }}
  static boolean ownedBy(CallableDeclaration<?> owner,Node n,String src) {
    if(n.findAncestor(CallableDeclaration.class).orElse(null)!=owner)return false;
    for(Node p=n;p!=null;p=p.getParentNode().orElse(null)) {
    if(p instanceof LambdaExpr){diag(src,"LAMBDA_CALL_OMITTED");CALLS.add(callRecord(src,(Expression)n,"DEFERRED_LAMBDA"));return false;} if(p instanceof CallableDeclaration<?>)return p==owner;
  }return false;}
  static void edge(String src,Expression call) {
    Map<String,Object> record=callRecord(src,call,"UNRESOLVED");CALLS.add(record);
    String target; try {
      ResolvedMethodLikeDeclaration r=call instanceof MethodCallExpr?((MethodCallExpr)call).resolve():((ObjectCreationExpr)call).resolve();
      String name=r instanceof ResolvedConstructorDeclaration?"<init>":r.getName(), sig="("+IntStream.range(0,r.getNumberOfParams()).mapToObj(i->r.getParam(i).getType().describe()).collect(Collectors.joining(","))+")";
      List<String> ids=DECLARATIONS.getOrDefault(key(r.declaringType().getQualifiedName(),name,sig),List.of());
      if(ids.isEmpty()){
        record.put("declaredTarget",key(r.declaringType().getQualifiedName(),name,sig));
        if(SOURCE_CLASSES.contains(r.declaringType().getQualifiedName())){unresolved++;diag(src,"SOURCE_DECLARATION_NOT_INDEXED");record.put("resolution","UNRESOLVED");}
        else{externalCalls++;diag(src,"EXTERNAL_BOUNDARY");record.put("resolution","EXTERNAL_DECLARATION");}
        return;
      }
      if(ids.size()!=1){unresolved++;diag(src,"AMBIGUOUS_SOURCE_DECLARATION");record.put("resolution","AMBIGUOUS");return;} target=ids.get(0);
    } catch(Exception e) { unresolved++;diag(src,"UNRESOLVED_CALL");return; }
    record.put("resolution","SOURCE_DECLARATION");record.put("target",target);
    EDGES.add(obj("source",src,"target",target,"kind","source-resolved","sites",List.of(obj("line",line(call),"conditions",record.get("conditions")))));
    METHODS.get(src).put("outgoing",((Number)METHODS.get(src).get("outgoing")).intValue()+1); METHODS.get(target).put("incoming",((Number)METHODS.get(target).get("incoming")).intValue()+1);
  }
  static Map<String,Object> callRecord(String src,Expression call,String resolution) {
    String expression;
    if(call instanceof MethodCallExpr method) {
      String receiver=method.getScope().map(SourceIndex::scopeName).orElse("");
      expression=(receiver.isEmpty()?"":receiver+".")+method.getNameAsString()+"(…)";
    } else expression="new "+((ObjectCreationExpr)call).getType().getNameAsString()+"(…)";
    return obj("id",src+":call:"+line(call)+":"+call.getRange().map(x->x.begin.column).orElse(0),"source",src,"path",METHODS.get(src).get("path"),"line",line(call),"expression",expression,"resolution",resolution,"conditions",guards(call));
  }
  static String scopeName(Expression scope) {
    if(scope instanceof NameExpr name)return name.getNameAsString();
    if(scope instanceof ThisExpr)return "this";
    if(scope instanceof SuperExpr)return "super";
    if(scope instanceof FieldAccessExpr field)return scopeName(field.getScope())+"."+field.getNameAsString();
    if(scope instanceof MethodCallExpr method)return method.getNameAsString()+"(…)";
    return "<expression>";
  }
  static void routes(Unit u,CallableDeclaration<?> d,String id,String cls) {
    if(!(d instanceof MethodDeclaration))return; Mapping base=mapping(ownerClass(d)), own=mapping(d);
    if(!own.present)return; if(!own.known||base.present&&!base.known){limit("ROUTE_MAPPING_UNSUPPORTED");return;}
    ClassOrInterfaceDeclaration owner=ownerClass(d);
    if(owner!=null&&(!owner.getExtendedTypes().isEmpty()||!owner.getImplementedTypes().isEmpty()))limit("ROUTE_INHERITANCE_UNSUPPORTED");
    if(own.verbs.isEmpty()){limit("ROUTE_HTTP_METHOD_UNKNOWN");return;}
    Set<String> verbs=new TreeSet<>(own.verbs);if(base.present&&!base.verbs.isEmpty())verbs.retainAll(base.verbs);if(verbs.isEmpty())return;
    for(String b:base.present?base.paths:List.of(""))for(String p:own.paths)for(String v:verbs) {
      boolean template=b.contains("{")||p.contains("{");
      String resolution=(b.equals("{unresolved}")||p.equals("{unresolved}"))?"unresolved":"literal";
      ROUTES.add(obj("id",id+":route:"+ROUTES.size(),"module",u.module,"httpMethod",v,"path",join(b,p),"controller",cls,"handlerId",id,"source",obj("path",u.path,"line",line(d)),"resolution",resolution,"pathKind",template?"template":"literal","notes",resolution.equals("unresolved")?List.of("Mapping expression was not evaluated."):List.of()));
    }
  }
  record Mapping(boolean present,boolean known,List<String> paths,Set<String> verbs){}
  static Mapping mapping(Node n) {
    if(n==null)return new Mapping(false,true,List.of(),Set.of()); List<String> paths=new ArrayList<>();Set<String> verbs=new TreeSet<>();boolean present=false;
    if(!(n instanceof com.github.javaparser.ast.nodeTypes.NodeWithAnnotations<?> annotated))return new Mapping(false,true,List.of(),Set.of()); boolean known=true;
    for(AnnotationExpr a:annotated.getAnnotations()) {String s=a.getName().getIdentifier();if(!mappingAnnotation(a,s)){if(s.endsWith("Mapping")){present=true;known=false;limit("ROUTE_MAPPING_UNSUPPORTED");}continue;}present=true;paths.addAll(mappingPaths(a));verbs.addAll(mappingVerbs(a,s));if(a instanceof NormalAnnotationExpr normal&&normal.getPairs().stream().anyMatch(p->Set.of("params","headers","consumes","produces").contains(p.getNameAsString())))limit("ROUTE_CONDITIONS_UNSUPPORTED");}
    return new Mapping(present,known,paths.isEmpty()?List.of(""):paths,verbs);
  }
  static boolean mappingAnnotation(AnnotationExpr a,String s){return Set.of("RequestMapping","GetMapping","PostMapping","PutMapping","DeleteMapping","PatchMapping").contains(s)&&spring(a,s);}
  static boolean spring(AnnotationExpr a,String s){String n=a.getNameAsString();if(n.equals("org.springframework.web.bind.annotation."+s))return true;return a.findCompilationUnit().map(c->c.getImports().stream().anyMatch(x->x.getNameAsString().equals("org.springframework.web.bind.annotation."+s)||(x.isAsterisk()&&x.getNameAsString().equals("org.springframework.web.bind.annotation")))).orElse(false);}
  static List<String> mappingPaths(AnnotationExpr a){if(a instanceof SingleMemberAnnotationExpr s)return values(s.getMemberValue());if(a instanceof NormalAnnotationExpr n)for(MemberValuePair p:n.getPairs())if(p.getNameAsString().equals("value")||p.getNameAsString().equals("path"))return values(p.getValue());return List.of("");}
  static Set<String> mappingVerbs(AnnotationExpr a,String s) {
    Map<String,String> direct=Map.of("GetMapping","GET","PostMapping","POST","PutMapping","PUT","DeleteMapping","DELETE","PatchMapping","PATCH");if(direct.containsKey(s))return Set.of(direct.get(s));if(!s.equals("RequestMapping"))return Set.of();
    if(a instanceof NormalAnnotationExpr n)for(MemberValuePair p:n.getPairs())if(p.getNameAsString().equals("method")) {Set<String> r=new TreeSet<>();for(Expression e:expressions(p.getValue())){String x=e.toString();int dot=x.lastIndexOf('.');x=dot>=0?x.substring(dot+1):x;if(Set.of("GET","POST","PUT","DELETE","PATCH","HEAD","OPTIONS","TRACE").contains(x))r.add(x);else limit("ROUTE_HTTP_METHOD_UNKNOWN");}return r;} return Set.of();
  }
  static List<Expression> expressions(Expression e){return e.isArrayInitializerExpr()?e.asArrayInitializerExpr().getValues():List.of(e);}
  static List<String> values(Expression e){if(e.isStringLiteralExpr())return List.of(e.asStringLiteralExpr().asString());if(e.isArrayInitializerExpr())return e.asArrayInitializerExpr().getValues().stream().flatMap(x->values(x).stream()).toList();return List.of("{unresolved}");}
  static List<Map<String,Object>> guards(Node node) {
    List<Map<String,Object>> g=new ArrayList<>();Node child=node;int depth=0;
    for(Node p=node.getParentNode().orElse(null);p!=null;p=p.getParentNode().orElse(null)) {
      if(p instanceof CallableDeclaration<?>||p instanceof LambdaExpr)break;if(depth++>=MAX_GUARD_DEPTH){limit("GUARD_DEPTH_LIMIT");break;}
      if(p instanceof IfStmt x){if(inside(child,x.getThenStmt()))g.add(guard("if",x.getCondition(),"then"));else if(inside(child,x.getElseStmt().orElse(null)))g.add(guard("if",x.getCondition(),"else"));}
      else if(p instanceof ForStmt x){if(inside(child,x.getBody()))g.add(guard("for",x.getCompare().orElse(null),"body"));}
      else if(p instanceof ForEachStmt x){if(inside(child,x.getBody()))g.add(guard("for-each",x.getIterable(),"body"));}
      else if(p instanceof WhileStmt x){if(inside(child,x.getBody()))g.add(guard("while",x.getCondition(),"body"));}
      else if(p instanceof DoStmt x){if(inside(child,x.getBody()))g.add(obj("kind","do","expression","","branch","body-no-precondition"));}
      else if(p instanceof SwitchEntry x){g.add(obj("kind","switch","expression",x.getLabels().stream().map(SourceIndex::clean).collect(Collectors.joining(",")),"branch",x.getLabels().isEmpty()?"default":"case"));limit("SWITCH_FALLTHROUGH_UNSUPPORTED");}
      else if(p instanceof ConditionalExpr x){if(inside(child,x.getThenExpr()))g.add(guard("ternary",x.getCondition(),"true"));else if(inside(child,x.getElseExpr()))g.add(guard("ternary",x.getCondition(),"false"));}
      child=p;
    }return g;
  }
  static Map<String,Object> guard(String kind,Expression e,String branch){return obj("kind",kind,"expression",clean(e),"branch",branch);}
  static boolean inside(Node n,Node ancestor){if(ancestor==null)return false;for(Node p=n;p!=null;p=p.getParentNode().orElse(null))if(p==ancestor)return true;return false;}
  static String clean(Expression e){if(e==null)return "";Expression c=e.clone();c.findAll(StringLiteralExpr.class).forEach(x->x.setString("<string>"));c.findAll(TextBlockLiteralExpr.class).forEach(x->x.setValue("<text-block>"));c.findAll(CharLiteralExpr.class).forEach(x->x.setChar('<'));String s=c.toString();return s.length()>MAX_GUARD_LENGTH?s.substring(0,MAX_GUARD_LENGTH)+"…":s;}
  static ClassOrInterfaceDeclaration ownerClass(Node n){for(Node p=n.getParentNode().orElse(null);p!=null;p=p.getParentNode().orElse(null))if(p instanceof ClassOrInterfaceDeclaration c)return c;return null;}
  static String clazz(Node n){List<String> names=new ArrayList<>();for(Node p=n;p!=null;p=p.getParentNode().orElse(null))if(p instanceof TypeDeclaration<?> t)names.add(t.getNameAsString());Collections.reverse(names);String pkg=n.findCompilationUnit().flatMap(CompilationUnit::getPackageDeclaration).map(x->x.getNameAsString()).orElse("");return pkg+(pkg.isEmpty()?"":".")+String.join(".",names);}
  static String signature(CallableDeclaration<?> d){try{ResolvedMethodLikeDeclaration r=d instanceof MethodDeclaration m?m.resolve():((ConstructorDeclaration)d).resolve();return "("+IntStream.range(0,r.getNumberOfParams()).mapToObj(i->r.getParam(i).getType().describe()).collect(Collectors.joining(","))+")";}catch(Exception ignored){return "("+d.getParameters().stream().map(x->x.getType().asString()).collect(Collectors.joining(","))+")";}}
  static String key(String c,String n,String s){return c+"#"+n+s;}static int line(Node n){return n.getRange().map(x->x.begin.line).orElse(0);}
  static boolean accessor(CallableDeclaration<?> d){if(!(d instanceof MethodDeclaration m)||m.getBody().isEmpty())return false;List<Statement>s=m.getBody().get().getStatements();if(s.size()!=1)return false;Statement one=s.get(0);String n=m.getNameAsString();if(one.isReturnStmt())return one.asReturnStmt().getExpression().map(e->e.isFieldAccessExpr()&&(n.startsWith("get")||n.startsWith("is"))).orElse(false);if(one.isExpressionStmt()&&one.asExpressionStmt().getExpression().isAssignExpr()){AssignExpr a=one.asExpressionStmt().getExpression().asAssignExpr();return n.startsWith("set")&&a.getTarget().isFieldAccessExpr()&&m.getParameters().size()==1;}return false;}
  static String join(String a,String b){String x=(a+"/"+b).replaceAll("/+","/");return x.startsWith("/")?x:"/"+x;}
  static void diag(String id,String code){DIAG_COUNTS.computeIfAbsent(id,k->new TreeMap<>()).merge(code,1,Integer::sum);}static void limit(String code){LIMIT_COUNTS.merge(code,1,Integer::sum);}
  static Map<String,List<Map<String,Object>>> diagnostics(){Map<String,List<Map<String,Object>>> r=new TreeMap<>();DIAG_COUNTS.forEach((id,counts)->r.put(id,counts.entrySet().stream().map(e->obj("code",e.getKey(),"count",e.getValue(),"message",diagnosticMessage(e.getKey()))).toList()));return r;}
  static String diagnosticMessage(String c){return switch(c){case "EXTERNAL_BOUNDARY"->"Resolved call leaves the indexed source declarations; no dangling graph edge was emitted.";case "AMBIGUOUS_SOURCE_DECLARATION"->"Resolved declaration identity is duplicated across indexed modules; no arbitrary graph edge was emitted.";case "LAMBDA_CALL_OMITTED"->"Calls in lambda bodies are omitted rather than attributed to the enclosing callable.";default->"A source call could not be resolved conservatively.";};}
  static List<Map<String,Object>> limits(){return LIMIT_COUNTS.entrySet().stream().map(e->obj("code",e.getKey(),"count",e.getValue(),"message",limitMessage(e.getKey()))).toList();}
  static String limitMessage(String c){return switch(c){case "PARSE_FAILURE"->"A Java source file could not be parsed completely.";case "GUARD_DEPTH_LIMIT"->"Nested guard collection is bounded and may omit outer guards.";case "SWITCH_FALLTHROUGH_UNSUPPORTED"->"Switch fallthrough is not modeled as a route or guard relationship.";case "ROUTE_HTTP_METHOD_UNKNOWN"->"RequestMapping without an explicit supported HTTP method is not emitted as an endpoint.";case "ROUTE_CONDITIONS_UNSUPPORTED"->"Mapping conditions such as headers, params, consumes, and produces are not modeled.";case "ROUTE_INHERITANCE_UNSUPPORTED"->"Controller inheritance is not followed for route discovery.";default->"A composed or unsupported mapping annotation was not guessed.";};}
  static boolean safe(Path p){Path rel=source.relativize(p);Path current=source;for(Path part:rel){current=current.resolve(part);if(Files.isSymbolicLink(current))return false;String n=part.toString();if(n.equals(".git")||n.equals("build")||n.equals(".gradle")||n.equals("node_modules"))return false;}return p.normalize().startsWith(source);}
  static List<Path> roots(Path s)throws Exception{try(Stream<Path>x=Files.walk(s)){return x.filter(Files::isDirectory).filter(SourceIndex::safe).filter(p->p.endsWith("src/main/java")).sorted().toList();}}
  static List<Path> files(List<Path> roots)throws Exception{List<Path> r=new ArrayList<>();for(Path root:roots)try(Stream<Path>x=Files.walk(root)){x.filter(Files::isRegularFile).filter(SourceIndex::safe).filter(p->p.toString().endsWith(".java")).forEach(r::add);}r.sort(Comparator.comparing(SourceIndex::relative));return r;}
  static String relative(Path p){return source.relativize(p).toString().replace('\\','/');}static String module(Path p,List<Path> rs){for(Path r:rs)if(p.startsWith(r)){Path q=r.getParent().getParent().getParent();return q.equals(source)?"root":source.relativize(q).toString().replace('\\','/');}return"root";}
  static String digest(List<Path> ps)throws Exception{MessageDigest md=MessageDigest.getInstance("SHA-256");for(Path p:ps){frame(md,relative(p).getBytes(StandardCharsets.UTF_8));frame(md,Files.readAllBytes(p));}return HexFormat.of().formatHex(md.digest());}static void frame(MessageDigest md,byte[] b){md.update(ByteBuffer.allocate(8).putLong(b.length).array());md.update(b);}static boolean samePaths(List<Path>a,List<Path>b){return a.stream().map(SourceIndex::relative).toList().equals(b.stream().map(SourceIndex::relative).toList());}
  static String git(String...cmd){try{Process p=new ProcessBuilder(Stream.concat(Stream.of("git"),Arrays.stream(cmd)).toList()).directory(source.toFile()).redirectErrorStream(true).start();return new String(p.getInputStream().readAllBytes(),StandardCharsets.UTF_8).trim();}catch(Exception e){return"not-collected";}}
  static Map<String,String> arguments(String[] a){Map<String,String>m=new HashMap<>();for(int i=0;i<a.length;i+=2){if(i+1>=a.length||!a[i].startsWith("--"))throw new IllegalArgumentException("arguments are --name value pairs");m.put(a[i],a[i+1]);}return m;}static String req(Map<String,String>m,String k){if(!m.containsKey(k)||m.get(k).isBlank())throw new IllegalArgumentException("required "+k);return m.get(k);}static Map<String,Object> obj(Object...a){Map<String,Object>m=new LinkedHashMap<>();for(int i=0;i<a.length;i+=2)m.put((String)a[i],a[i+1]);return m;}record Unit(Path file,CompilationUnit cu,String module,String path){}
}
