import java.io.BufferedInputStream;
import java.io.FileInputStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.HashSet;
import java.util.Set;
import java.util.TreeMap;
import org.jf.dexlib2.Opcodes;
import org.jf.dexlib2.dexbacked.DexBackedDexFile;
import org.jf.dexlib2.iface.ClassDef;
import org.jf.dexlib2.iface.Field;
import org.jf.dexlib2.iface.Method;
import org.jf.dexlib2.immutable.ImmutableClassDef;
import org.jf.dexlib2.immutable.ImmutableDexFile;
import org.jf.dexlib2.immutable.ImmutableField;
import org.jf.dexlib2.immutable.ImmutableMethod;
import org.jf.dexlib2.writer.pool.DexPool;

public final class MergeRuntimeDex {
    private static String signature(Method method) {
        return method.getName() + method.getParameterTypes().toString() + method.getReturnType();
    }

    private static ClassDef preserveSyntheticMethods(ClassDef previous, ClassDef replacement) {
        List<Method> methods = new ArrayList<>();
        Set<String> signatures = new HashSet<>();
        for (Method method : replacement.getMethods()) {
            methods.add(method);
            signatures.add(signature(method));
        }
        // Retained nested classes can still call javac's previous accessors or
        // constructor bridges after a partial runtime recompilation.
        for (Method method : previous.getMethods()) {
            if ((method.getAccessFlags() & 0x1000) != 0 && !signatures.contains(signature(method))) {
                methods.add(method);
            }
        }
        return new ImmutableClassDef(replacement.getType(), replacement.getAccessFlags(),
            replacement.getSuperclass(), replacement.getInterfaces(), replacement.getSourceFile(),
            replacement.getAnnotations(), replacement.getFields(), methods);
    }

    private static DexBackedDexFile read(String path) throws Exception {
        try (BufferedInputStream input = new BufferedInputStream(new FileInputStream(path))) {
            return DexBackedDexFile.fromInputStream(Opcodes.forApi(28), input);
        }
    }

    private static ClassDef withoutRestrictions(ClassDef definition) {
        List<Field> fields = new ArrayList<>();
        for (Field field : definition.getFields()) {
            fields.add(new ImmutableField(field.getDefiningClass(), field.getName(), field.getType(),
                field.getAccessFlags(), field.getInitialValue(), field.getAnnotations(), Collections.emptySet()));
        }
        List<Method> methods = new ArrayList<>();
        for (Method method : definition.getMethods()) {
            methods.add(new ImmutableMethod(method.getDefiningClass(), method.getName(), method.getParameters(),
                method.getReturnType(), method.getAccessFlags(), method.getAnnotations(),
                Collections.emptySet(), method.getImplementation()));
        }
        return new ImmutableClassDef(definition.getType(), definition.getAccessFlags(),
            definition.getSuperclass(), definition.getInterfaces(), definition.getSourceFile(),
            definition.getAnnotations(), fields, methods);
    }

    public static void main(String[] arguments) throws Exception {
        Map<String, ClassDef> classes = new TreeMap<>();
        for (ClassDef definition : read(arguments[0]).getClasses()) {
            classes.put(definition.getType(), definition);
        }
        int preserved = classes.size();
        int replaced = 0;
        for (ClassDef definition : read(arguments[1]).getClasses()) {
            ClassDef previous = classes.get(definition.getType());
            if (previous != null && arguments.length == 4 && arguments[3].equals("--preserve-synthetic")) {
                definition = preserveSyntheticMethods(previous, definition);
            }
            if (classes.put(definition.getType(), definition) != null) {
                preserved--;
                replaced++;
            }
        }
        List<ClassDef> definitions = new ArrayList<>();
        for (ClassDef definition : classes.values()) {
            definitions.add(withoutRestrictions(definition));
        }
        DexPool.writeTo(arguments[2], new ImmutableDexFile(Opcodes.forApi(28), definitions));
        System.out.println("API28_RECOMPILED_CLASSES=" + replaced);
        System.out.println("PRESERVED_EXISTING_CLASSES=" + preserved);
        System.out.println("API28_TOTAL_RUNTIME_CLASSES=" + classes.size());
    }
}
