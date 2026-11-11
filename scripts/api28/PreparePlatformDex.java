import java.io.BufferedInputStream;
import java.io.FileInputStream;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.jf.dexlib2.Opcodes;
import org.jf.dexlib2.ReferenceType;
import org.jf.dexlib2.dexbacked.DexBackedDexFile;
import org.jf.dexlib2.iface.ClassDef;
import org.jf.dexlib2.iface.Method;
import org.jf.dexlib2.iface.instruction.DualReferenceInstruction;
import org.jf.dexlib2.iface.instruction.Instruction;
import org.jf.dexlib2.iface.instruction.ReferenceInstruction;
import org.jf.dexlib2.iface.instruction.formats.Instruction21c;
import org.jf.dexlib2.iface.instruction.formats.Instruction31c;
import org.jf.dexlib2.iface.reference.StringReference;
import org.jf.dexlib2.iface.reference.MethodProtoReference;
import org.jf.dexlib2.immutable.instruction.ImmutableInstruction21c;
import org.jf.dexlib2.immutable.instruction.ImmutableInstruction31c;
import org.jf.dexlib2.immutable.reference.ImmutableStringReference;
import org.jf.dexlib2.rewriter.DexRewriter;
import org.jf.dexlib2.rewriter.Rewriter;
import org.jf.dexlib2.rewriter.RewriterModule;
import org.jf.dexlib2.rewriter.Rewriters;
import org.jf.dexlib2.writer.pool.DexPool;
import org.jf.dexlib2.writer.io.FileDataStore;

/** Preserve platform bytecode and relocate its process-private filesystem paths. */
public final class PreparePlatformDex {
    private static String privatePath(String value) {
        if (value.startsWith("/system/fonts")
                || value.startsWith("/system/etc/fonts")
                || value.startsWith("/system/etc/font_")
                || value.startsWith("/system/usr/hyphen-data")
                || value.startsWith("/system/framework/framework-res.apk")) {
            return "/home/art/api29-root" + value;
        }
        return value;
    }

    public static void main(String[] arguments) throws Exception {
        if (arguments.length != 3) {
            throw new IllegalArgumentException("Expected input DEX, output DEX and core descriptors");
        }
        Set<String> core = new HashSet<>(Files.readAllLines(Paths.get(arguments[2])));
        DexBackedDexFile input;
        try (BufferedInputStream stream = new BufferedInputStream(new FileInputStream(arguments[0]))) {
            input = DexBackedDexFile.fromInputStream(Opcodes.forApi(28), stream);
        }
        DexRewriter rewriter = new DexRewriter(new RewriterModule() {
            @Override
            public Rewriter<Instruction> getInstructionRewriter(Rewriters rewriters) {
                return instruction -> {
                    if (!(instruction instanceof ReferenceInstruction)) return instruction;
                    ReferenceInstruction reference = (ReferenceInstruction) instruction;
                    if (reference.getReferenceType() != ReferenceType.STRING) return instruction;
                    String value = ((StringReference) reference.getReference()).getString();
                    String replacement = privatePath(value);
                    if (value.equals(replacement)) return instruction;
                    ImmutableStringReference string = new ImmutableStringReference(replacement);
                    if (instruction instanceof Instruction21c) {
                        return new ImmutableInstruction21c(instruction.getOpcode(),
                                ((Instruction21c) instruction).getRegisterA(), string);
                    }
                    if (instruction instanceof Instruction31c) {
                        return new ImmutableInstruction31c(instruction.getOpcode(),
                                ((Instruction31c) instruction).getRegisterA(), string);
                    }
                    throw new IllegalStateException("Unsupported string instruction");
                };
            }
        });
        List<ClassDef> classes = new ArrayList<>();
        for (ClassDef definition : input.getClasses()) {
            if (!core.contains(definition.getType())) {
                classes.add(rewriter.getClassDefRewriter().rewrite(definition));
            }
        }
        DexPool pool = new DexPool(Opcodes.forApi(28));
        for (ClassDef definition : classes) {
            pool.internClass(definition);
            // Older dexlib2 pools omit the second invoke-polymorphic reference.
            for (Method method : definition.getMethods()) {
                if (method.getImplementation() == null) continue;
                for (Instruction instruction : method.getImplementation().getInstructions()) {
                    if (instruction instanceof DualReferenceInstruction) {
                        DualReferenceInstruction reference = (DualReferenceInstruction) instruction;
                        if (reference.getReferenceType2() != ReferenceType.METHOD_PROTO) {
                            throw new IllegalStateException("Unsupported second reference");
                        }
                        pool.protoSection.intern((MethodProtoReference) reference.getReference2());
                    }
                }
            }
        }
        FileDataStore output = new FileDataStore(new java.io.File(arguments[1]));
        try {
            pool.writeTo(output);
        } finally {
            output.close();
        }
        System.out.println("API28_PLATFORM_CLASSES=" + classes.size());
    }
}
