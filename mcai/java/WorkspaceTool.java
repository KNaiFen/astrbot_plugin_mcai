import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.jar.*;
import java.util.regex.Pattern;
import java.util.zip.*;

import net.fabricmc.mappingio.MappingReader;
import net.fabricmc.mappingio.tree.MemoryMappingTree;
import net.fabricmc.mappingio.tree.MappingTreeView.*;
import org.objectweb.asm.*;
import org.objectweb.asm.commons.ClassRemapper;
import org.objectweb.asm.commons.Remapper;
import org.objectweb.asm.tree.ClassNode;

public final class WorkspaceTool {
    private static final Pattern SIGNATURE = Pattern.compile(
        "META-INF/(?:[^/]+\\.(?:SF|DSA|RSA|EC)|SIG-[^/]+)", Pattern.CASE_INSENSITIVE);

    public static void main(String[] args) throws IOException {
        var tree = new MemoryMappingTree(true);
        MappingReader.read(Path.of(args[1]), tree);
        if (tree.getSrcNamespace() == null || tree.getDstNamespaces().isEmpty()) {
            throw new IllegalArgumentException("映射文件没有可用的源和目标命名空间");
        }
        var out = new PrintWriter(new OutputStreamWriter(System.out, StandardCharsets.UTF_8), true);
        if (args[0].equals("lookup")) {
            out.println(json(lookup(tree, args)));
        } else if (args[0].equals("remap")) {
            out.println(json(remap(tree, args)));
        } else {
            throw new IllegalArgumentException("未知工作区 Java 子命令：" + args[0]);
        }
    }

    private static List<String> namespaces(MemoryMappingTree tree) {
        var names = new ArrayList<String>();
        names.add(tree.getSrcNamespace());
        names.addAll(tree.getDstNamespaces());
        return names;
    }

    private static int namespace(MemoryMappingTree tree, String name) {
        int id = tree.getNamespaceId(name);
        if (id < tree.getMinNamespaceId()) {
            throw new IllegalArgumentException("未知映射命名空间 " + name + "，可用：" + namespaces(tree));
        }
        return id;
    }

    private static Map<String, Object> lookup(MemoryMappingTree tree, String[] args) {
        String query = args[2].replace('.', '/').toLowerCase(Locale.ROOT);
        String kind = args[3];
        var names = namespaces(tree);
        var search = args[4].isEmpty() ? names : List.of(args[4]);
        var show = args[5].isEmpty() ? names : List.of(args[5]);
        var searchIds = search.stream().mapToInt(n -> namespace(tree, n)).toArray();
        show.forEach(n -> namespace(tree, n));
        int limit = Integer.parseInt(args[6]), hits = 0, budget = 6500;
        var rows = new ArrayList<Map<String, Object>>();
        for (var owner : tree.getClasses()) {
            for (String type : List.of("class", "field", "method")) {
                if (!kind.equals("all") && !kind.equals(type)) continue;
                Collection<? extends ElementMappingView> elements = switch (type) {
                    case "class" -> List.of(owner);
                    case "field" -> owner.getFields();
                    default -> owner.getMethods();
                };
                for (var element : elements) {
                    var member = element instanceof MemberMappingView m ? m : null;
                    boolean found = false;
                    for (int id : searchIds) {
                        String name = element.getName(id);
                        if (name == null) continue;
                        String qualified = member == null ? name
                            : owner.getName(id) + "/" + name + ":" + member.getDesc(id);
                        if (qualified.toLowerCase(Locale.ROOT).contains(query)) {
                            found = true;
                            break;
                        }
                    }
                    if (!found) continue;
                    hits++;
                    if (rows.size() >= limit || budget <= 0) continue;
                    var row = new LinkedHashMap<String, Object>();
                    row.put("kind", type);
                    var elementNames = new LinkedHashMap<String, String>();
                    var owners = new LinkedHashMap<String, String>();
                    var descriptors = new LinkedHashMap<String, String>();
                    for (String n : show) {
                        int id = namespace(tree, n);
                        elementNames.put(n, element.getName(id));
                        if (member != null) {
                            owners.put(n, owner.getName(id));
                            descriptors.put(n, member.getDesc(id));
                        }
                    }
                    row.put("names", elementNames);
                    row.put("owner", member == null ? null : owners);
                    row.put("descriptors", member == null ? null : descriptors);
                    budget -= json(row).length() + 1;
                    if (budget >= 0) rows.add(row);
                }
            }
        }
        return Map.of("namespaces", names, "matches", rows, "total_hits", hits,
            "truncated", hits > rows.size());
    }

    private static Map<String, Object> remap(MemoryMappingTree tree, String[] args) throws IOException {
        var names = namespaces(tree);
        if (names.size() != 2 && (args[2].isEmpty() || args[3].isEmpty())) {
            throw new IllegalArgumentException("请指定 mapping_from 与 mapping_to，可用：" + names);
        }
        String from = args[2].isEmpty() ? names.get(0) : args[2];
        String to = args[3].isEmpty() ? names.get(1) : args[3];
        if (from.equals(to)) throw new IllegalArgumentException("源与目标映射命名空间必须不同：" + names);
        int source = namespace(tree, from), target = namespace(tree, to);
        Path output = Path.of(args[5]);
        var requested = new LinkedHashMap<String, String>();
        for (int i = 7; i < args.length; i++) requested.put(args[i].replace('.', '/'), "");
        try (var jar = new ZipFile(args[4]);
             var symbols = Files.newBufferedWriter(Path.of(args[6]), StandardCharsets.UTF_8)) {
            var graph = new HashMap<String, ClassNode>();
            for (var entry : Collections.list(jar.entries())) {
                if (!entry.getName().endsWith(".class")) continue;
                try (var input = jar.getInputStream(entry)) {
                    var node = new ClassNode();
                    new ClassReader(input).accept(node, ClassReader.SKIP_CODE | ClassReader.SKIP_DEBUG | ClassReader.SKIP_FRAMES);
                    if (!versioned(entry.getName())) graph.put(node.name, node);
                    else graph.putIfAbsent(node.name, node);
                }
            }
            var mapper = new JarNames(tree, graph, source, target);
            var documented = new LinkedHashSet<>(requested.keySet());
            for (String runtime : new TreeSet<>(graph.keySet())) {
                for (String selected : requested.keySet()) {
                    if (runtime.startsWith(selected + "$")) documented.add(runtime);
                }
            }
            for (String runtime : documented) {
                var node = graph.get(runtime);
                String readable = mapper.map(runtime);
                if (requested.containsKey(runtime)) requested.put(runtime, readable);
                symbols.write(readable + " ↔ " + runtime + "\n");
                for (var field : node.fields) {
                    symbols.write("  field " + mapper.mapFieldName(runtime, field.name, field.desc)
                        + ":" + mapper.mapDesc(field.desc) + " ↔ " + field.name + ":" + field.desc + "\n");
                }
                for (var method : node.methods) {
                    symbols.write("  method " + mapper.mapMethodName(runtime, method.name, method.desc)
                        + mapper.mapMethodDesc(method.desc) + " ↔ " + method.name + method.desc + "\n");
                }
            }
            if (!Files.isRegularFile(output)) {
                try (var zip = new ZipOutputStream(Files.newOutputStream(output, StandardOpenOption.CREATE_NEW))) {
                    for (var entry : Collections.list(jar.entries())) {
                        String name = entry.getName();
                        if (entry.isDirectory() || SIGNATURE.matcher(name).matches()) continue;
                        try (var input = jar.getInputStream(entry)) {
                            if (name.endsWith(".class")) {
                                var reader = new ClassReader(input);
                                var writer = new ClassWriter(0);
                                reader.accept(new ClassRemapper(writer, mapper), 0);
                                String prefix = versioned(name) ? name.substring(0, name.indexOf('/', 18) + 1) : "";
                                zip.putNextEntry(new ZipEntry(prefix + mapper.map(reader.getClassName()) + ".class"));
                                zip.write(writer.toByteArray());
                            } else {
                                zip.putNextEntry(new ZipEntry(name));
                                if (name.equalsIgnoreCase(JarFile.MANIFEST_NAME)) {
                                    var manifest = new Manifest(input);
                                    manifest.getEntries().clear();
                                    manifest.write(zip);
                                } else {
                                    input.transferTo(zip);
                                }
                            }
                            zip.closeEntry();
                        }
                    }
                }
            }
        }
        return Map.of("mapping_from", from, "mapping_to", to, "classes", requested);
    }

    private static boolean versioned(String entry) {
        return entry.startsWith("META-INF/versions/") && entry.indexOf('/', 18) >= 0;
    }

    private static final class JarNames extends Remapper {
        private final MemoryMappingTree tree;
        private final Map<String, ClassNode> graph;
        private final int source, target;

        JarNames(MemoryMappingTree tree, Map<String, ClassNode> graph, int source, int target) {
            super(Opcodes.ASM9);
            this.tree = tree;
            this.graph = graph;
            this.source = source;
            this.target = target;
        }

        @Override public String map(String name) {
            var mapped = tree.getClass(name, source);
            if (mapped != null && mapped.getName(target) != null) return mapped.getName(target);
            int inner = name.lastIndexOf('$');
            return inner >= 0 ? map(name.substring(0, inner)) + name.substring(inner) : name;
        }

        @Override public String mapMethodName(String owner, String name, String desc) {
            if (name.startsWith("<")) return name;
            return member(owner, name, desc, true);
        }

        @Override public String mapFieldName(String owner, String name, String desc) {
            return member(owner, name, desc, false);
        }

        @Override public String mapRecordComponentName(String owner, String name, String desc) {
            return mapFieldName(owner, name, desc);
        }

        @Override public String mapInvokeDynamicMethodName(String name, String desc, Handle bootstrap, Object... args) {
            if (bootstrap.getOwner().equals("java/lang/invoke/LambdaMetafactory")
                && args.length > 0 && args[0] instanceof Type type) {
                return mapMethodName(Type.getReturnType(desc).getInternalName(), name, type.getDescriptor());
            }
            return super.mapInvokeDynamicMethodName(name, desc, bootstrap, args);
        }

        private String member(String owner, String name, String desc, boolean method) {
            var pending = new ArrayDeque<String>();
            var visited = new HashSet<String>();
            pending.add(owner);
            while (!pending.isEmpty()) {
                String current = pending.removeFirst();
                if (!visited.add(current)) continue;
                var node = graph.get(current);
                var mapping = method ? tree.getMethod(current, name, desc, source)
                    : tree.getField(current, name, desc, source);
                if (node != null && method) {
                    for (var declaration : node.methods) {
                        if (!declaration.name.equals(name) || !declaration.desc.equals(desc)) continue;
                        int access = declaration.access;
                        if (!current.equals(owner) && ((access & Opcodes.ACC_PRIVATE) != 0
                            || ((access & (Opcodes.ACC_PUBLIC | Opcodes.ACC_PROTECTED)) == 0
                            && !packageName(current).equals(packageName(owner))))) {
                            mapping = null;
                        } else if (current.equals(owner)
                            && (access & (Opcodes.ACC_PRIVATE | Opcodes.ACC_STATIC)) != 0) {
                            return mapping == null ? name : Objects.requireNonNullElse(mapping.getName(target), name);
                        }
                        break;
                    }
                }
                if (mapping != null && mapping.getName(target) != null) return mapping.getName(target);
                if (node == null) continue;
                if (!method && node.fields.stream().anyMatch(f -> f.name.equals(name) && f.desc.equals(desc))) {
                    if (current.equals(owner)) return name;
                    continue;
                }
                pending.addAll(node.interfaces);
                if (node.superName != null) {
                    if (method) pending.addFirst(node.superName);
                    else pending.add(node.superName);
                }
            }
            return name;
        }

        private static String packageName(String name) {
            return name.substring(0, name.lastIndexOf('/') + 1);
        }
    }

    private static String json(Object value) {
        if (value == null || value instanceof Number || value instanceof Boolean) return String.valueOf(value);
        if (value instanceof Map<?, ?> map) {
            var items = new StringJoiner(",", "{", "}");
            map.forEach((key, item) -> items.add(json(key) + ":" + json(item)));
            return items.toString();
        }
        if (value instanceof Collection<?> list) {
            var items = new StringJoiner(",", "[", "]");
            list.forEach(item -> items.add(json(item)));
            return items.toString();
        }
        var out = new StringBuilder("\"");
        for (char ch : value.toString().toCharArray()) {
            if (ch == '"' || ch == '\\') out.append('\\').append(ch);
            else if (ch < 32 || Character.isSurrogate(ch)) out.append(String.format("\\u%04x", (int) ch));
            else out.append(ch);
        }
        return out.append('"').toString();
    }
}
