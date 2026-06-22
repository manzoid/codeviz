// codeviz Java tracer.
//
// An original, MIT-clean JDI (com.sun.jdi) tracer for codeviz.  It launches the
// user's compiled class in a child JVM via a LaunchingConnector, single-steps it
// line by line, and at each step captures the call stack, local variables, and
// the referenced heap, emitting an Online Python Tutor (OPT) trace JSON to stdout
// as {"code", "trace":[...], "lang":"java"}.
//
// This does NOT vendor OPT's java_jail / traceprinter (which is AGPL).  JDI is a
// standard JDK debugging API; this code is our own.
//
// Usage:
//   java Tracer <MainClassName> <userClassesDir> <originalSourceFile>
//
// The user source has already been compiled into <userClassesDir>; the original
// source text (shown in the UI) is read from <originalSourceFile> and embedded as
// the trace's "code".

import com.sun.jdi.*;
import com.sun.jdi.connect.*;
import com.sun.jdi.event.*;
import com.sun.jdi.request.*;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

public class Tracer {

    static final int MAX_STEPS = 1000;

    final String mainClass;
    final String classpath;
    final String source;

    final StringBuilder stdout = new StringBuilder();
    final List<Map<String, Object>> trace = new ArrayList<>();

    // Stable heap-id allocation keyed by JDI ObjectReference.uniqueID().
    // The same underlying object always gets the same id, so aliasing renders
    // as two REFs to one heap entry.
    final Map<Long, Long> idMap = new HashMap<>();

    String pendingException = null;   // first line of an uncaught exception message
    static final boolean DEBUG = System.getenv("CODEVIZ_DEBUG") != null;
    static void dbg(String s) { if (DEBUG) System.err.println("[dbg] " + s); }

    Tracer(String mainClass, String classpath, String source) {
        this.mainClass = mainClass;
        this.classpath = classpath;
        this.source = source;
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 3) {
            System.err.println("usage: java Tracer <MainClass> <classpath> <sourceFile>");
            System.exit(2);
        }
        String src = new String(Files.readAllBytes(Paths.get(args[2])), StandardCharsets.UTF_8);
        Tracer t = new Tracer(args[0], args[1], src);
        t.run();
    }

    void run() throws Exception {
        VirtualMachine vm = launch();

        EventRequestManager erm = vm.eventRequestManager();

        // Only instrument the user's class(es); never step into the JDK so the
        // trace stays in the code the user actually wrote.
        //
        // NOTE: multiple addClassFilter() calls on ONE request are AND-ed, so we
        // use a single wildcard ("Demo*") that matches the main class and any of
        // its nested classes ("Demo$Inner"), then re-check declaring types in
        // code (isUserType) to exclude unrelated classes.
        String filter = mainClass + "*";

        ClassPrepareRequest cpr = erm.createClassPrepareRequest();
        cpr.addClassFilter(filter);
        cpr.setSuspendPolicy(EventRequest.SUSPEND_ALL);
        cpr.enable();

        MethodEntryRequest mer = erm.createMethodEntryRequest();
        mer.addClassFilter(filter);
        mer.setSuspendPolicy(EventRequest.SUSPEND_ALL);
        mer.enable();

        MethodExitRequest mxr = erm.createMethodExitRequest();
        mxr.addClassFilter(filter);
        mxr.setSuspendPolicy(EventRequest.SUSPEND_ALL);
        mxr.enable();

        ExceptionRequest exr = erm.createExceptionRequest(null, true, true);
        exr.addClassFilter(filter);
        exr.setSuspendPolicy(EventRequest.SUSPEND_ALL);
        exr.enable();

        // Pump the child's stdout/stderr on background threads.
        Process proc = vm.process();
        Thread outPump = pump(proc.getInputStream(), stdout);
        Thread errPump = pump(proc.getErrorStream(), new StringBuilder());
        outPump.start();
        errPump.start();

        EventQueue queue = vm.eventQueue();
        StepRequest stepRequest = null;
        boolean stop = false;

        while (!stop) {
            EventSet set;
            try {
                set = queue.remove();
            } catch (VMDisconnectedException e) {
                break;
            }
            boolean resume = true;
            for (Event ev : set) {
                dbg("event: " + ev.getClass().getSimpleName());
                if (ev instanceof VMDeathEvent || ev instanceof VMDisconnectEvent) {
                    stop = true;
                } else if (ev instanceof ClassPrepareEvent) {
                    // First user class loaded: arm line-stepping on its thread.
                    ClassPrepareEvent ce = (ClassPrepareEvent) ev;
                    if (stepRequest == null) {
                        stepRequest = erm.createStepRequest(
                                ce.thread(), StepRequest.STEP_LINE, StepRequest.STEP_INTO);
                        // Limit stepping to user classes; the JDK is skipped.
                        stepRequest.addClassFilter(mainClass + "*");
                        stepRequest.setSuspendPolicy(EventRequest.SUSPEND_ALL);
                        stepRequest.enable();
                    }
                } else if (ev instanceof MethodEntryEvent) {
                    MethodEntryEvent me = (MethodEntryEvent) ev;
                    dbg("  methodEntry: " + me.location().declaringType().name() + "." + me.location().method().name());
                    recordStep("call", me.thread(), me.location());
                } else if (ev instanceof MethodExitEvent) {
                    MethodExitEvent mx = (MethodExitEvent) ev;
                    recordStep("return", mx.thread(), mx.location());
                } else if (ev instanceof StepEvent) {
                    StepEvent se = (StepEvent) ev;
                    recordStep("step_line", se.thread(), se.location());
                } else if (ev instanceof ExceptionEvent) {
                    ExceptionEvent ee = (ExceptionEvent) ev;
                    // Only treat genuinely uncaught exceptions as the terminal
                    // exception step (catchLocation == null means uncaught).
                    if (ee.catchLocation() == null) {
                        currentThread = ee.thread();   // needed before invoke()
                        pendingException = exceptionMessage(ee);
                        recordStep("exception", ee.thread(), ee.location());
                    }
                }
                if (trace.size() >= MAX_STEPS) {
                    stop = true;
                }
            }
            if (resume && !stop) {
                set.resume();
            } else if (stop) {
                try { set.resume(); } catch (Exception ignore) {}
            }
        }

        // Drain child output.
        try { proc.waitFor(); } catch (InterruptedException ignore) {}
        try { outPump.join(2000); } catch (InterruptedException ignore) {}
        try { errPump.join(2000); } catch (InterruptedException ignore) {}

        // The final program output (e.g. a trailing println executed after the
        // last recorded step) should appear on the last step.
        if (!trace.isEmpty()) {
            trace.get(trace.size() - 1).put("stdout", stdout.toString());
        }

        System.out.println(toJson(buildResult()));
        System.out.flush();
    }

    VirtualMachine launch() throws Exception {
        LaunchingConnector connector = Bootstrap.virtualMachineManager().defaultConnector();
        Map<String, Connector.Argument> args = connector.defaultArguments();
        args.get("main").setValue(mainClass);
        args.get("options").setValue("-cp \"" + classpath + "\"");
        // suspend=true by default for launching connector; child stops at start.
        return connector.launch(args);
    }

    // ---- step capture --------------------------------------------------------

    boolean isUserType(String typeName) {
        return typeName.equals(mainClass) || typeName.startsWith(mainClass + "$");
    }

    void recordStep(String event, ThreadReference thread, Location loc) {
        if (trace.size() >= MAX_STEPS) return;
        // The wildcard request filter ("Demo*") can over-match (e.g. "DemoFoo");
        // exclude anything that isn't the main class or one of its nested types.
        if (!isUserType(loc.declaringType().name())) return;
        currentThread = thread;   // used by invoke() for JDK collection reads
        try {
            List<StackFrame> frames = thread.frames();
            // Keep only user frames (skip any JDK frames that slip in).
            List<StackFrame> userFrames = new ArrayList<>();
            for (StackFrame f : frames) {
                String dn = f.location().declaringType().name();
                if (dn.equals(mainClass) || dn.startsWith(mainClass + "$")) {
                    userFrames.add(f);
                }
            }
            if (userFrames.isEmpty()) return;

            Map<Long, Object> heap = new LinkedHashMap<>();
            HeapCtx ctx = new HeapCtx(heap);

            // Bottom frame == main's frame; codeviz renders it as the global
            // frame.  Frames above it (deeper calls) go into stack_to_render.
            StackFrame bottom = userFrames.get(userFrames.size() - 1);
            List<StackFrame> above = userFrames.subList(0, userFrames.size() - 1);

            VarBundle globals = readFrame(ctx, bottom);

            List<Map<String, Object>> stackToRender = new ArrayList<>();
            for (int i = 0; i < above.size(); i++) {
                StackFrame fr = above.get(i);
                VarBundle vb = readFrame(ctx, fr);
                Map<String, Object> frameObj = new LinkedHashMap<>();
                String fname = fr.location().method().name();
                frameObj.put("func_name", fname);
                frameObj.put("is_highlighted", i == 0);
                frameObj.put("is_parent", false);
                frameObj.put("is_zombie", false);
                frameObj.put("parent_frame_id_list", new ArrayList<>());
                frameObj.put("unique_hash", fname + "_" + (above.size() - i));
                frameObj.put("frame_id", above.size() - i);
                frameObj.put("encoded_locals", vb.locals);
                frameObj.put("ordered_varnames", vb.order);
                stackToRender.add(frameObj);
            }

            // Expand the BFS heap queue into encoded objects.
            expandHeap(ctx);

            Map<String, Object> step = new LinkedHashMap<>();
            step.put("event", event);
            step.put("line", loc.lineNumber());
            String topFunc = above.isEmpty() ? "<module>" : above.get(0).location().method().name();
            // The bottom frame is main(); when the top user frame IS main, the
            // current function is main itself, rendered as the global module.
            if (above.isEmpty()) {
                topFunc = "<module>";
            }
            step.put("func_name", topFunc);
            step.put("globals", globals.locals);
            step.put("ordered_globals", globals.order);
            step.put("stack_to_render", stackToRender);
            // Convert long heap ids to strings for JSON object keys.
            Map<String, Object> heapStr = new LinkedHashMap<>();
            for (Map.Entry<Long, Object> e : heap.entrySet()) {
                heapStr.put(String.valueOf(e.getKey()), e.getValue());
            }
            step.put("heap", heapStr);
            step.put("stdout", stdout.toString());
            if ("exception".equals(event) && pendingException != null) {
                step.put("exception_msg", pendingException);
            }
            trace.add(step);
        } catch (IncompatibleThreadStateException | InvalidStackFrameException e) {
            // Thread not suspended cleanly; skip this step.
        } catch (Exception e) {
            // Be defensive: never let one bad step abort the whole trace.
        }
    }

    static class VarBundle {
        Map<String, Object> locals = new LinkedHashMap<>();
        List<String> order = new ArrayList<>();
    }

    VarBundle readFrame(HeapCtx ctx, StackFrame frame) {
        VarBundle vb = new VarBundle();
        try {
            List<LocalVariable> vars;
            try {
                vars = frame.visibleVariables();
            } catch (AbsentInformationException e) {
                // Compiled without -g; no local var table. Nothing to show.
                return vb;
            }
            Map<LocalVariable, Value> values = frame.getValues(vars);
            for (LocalVariable lv : vars) {
                String name = lv.name();
                vb.order.add(name);
                vb.locals.put(name, encodeValue(ctx, values.get(lv)));
            }
        } catch (Exception e) {
            // ignore frames we can't read
        }
        return vb;
    }

    // ---- value / object encoding --------------------------------------------

    static class HeapCtx {
        final Map<Long, Object> heap;            // id -> encoded object
        final Set<Long> seen = new HashSet<>();  // ids already queued/encoded
        final Deque<ObjectReference> objQueue = new ArrayDeque<>();
        HeapCtx(Map<Long, Object> heap) { this.heap = heap; }
    }

    long idFor(ObjectReference obj) {
        long unique = obj.uniqueID();
        return idMap.computeIfAbsent(unique, k -> (long) (idMap.size() + 1));
    }

    Object refFor(HeapCtx ctx, ObjectReference obj) {
        long id = idFor(obj);
        if (!ctx.seen.contains(id)) {
            ctx.seen.add(id);
            ctx.objQueue.add(obj);
        }
        return Arrays.asList("REF", id);
    }

    Object encodeValue(HeapCtx ctx, Value v) {
        if (v == null) {
            return Arrays.asList("JS_TOKEN", "null");
        }
        if (v instanceof StringReference) {
            return ((StringReference) v).value();
        }
        if (v instanceof BooleanValue) {
            return ((BooleanValue) v).value();
        }
        if (v instanceof CharValue) {
            // Render chars as their literal token so they read naturally.
            return Arrays.asList("JS_TOKEN", "'" + ((CharValue) v).value() + "'");
        }
        if (v instanceof ByteValue) {
            return (long) ((ByteValue) v).value();
        }
        if (v instanceof ShortValue) {
            return (long) ((ShortValue) v).value();
        }
        if (v instanceof IntegerValue) {
            return (long) ((IntegerValue) v).value();
        }
        if (v instanceof LongValue) {
            return ((LongValue) v).value();
        }
        if (v instanceof FloatValue) {
            return (double) ((FloatValue) v).value();
        }
        if (v instanceof DoubleValue) {
            return ((DoubleValue) v).value();
        }
        if (v instanceof ArrayReference) {
            return refFor(ctx, (ArrayReference) v);
        }
        if (v instanceof ObjectReference) {
            return refFor(ctx, (ObjectReference) v);
        }
        // VoidValue or anything unexpected.
        return Arrays.asList("JS_TOKEN", v.toString());
    }

    void expandHeap(HeapCtx ctx) {
        while (!ctx.objQueue.isEmpty()) {
            ObjectReference obj = ctx.objQueue.poll();
            long id = idFor(obj);
            if (ctx.heap.containsKey(id)) continue;
            ctx.heap.put(id, encodeObject(ctx, obj));
        }
    }

    Object encodeObject(HeapCtx ctx, ObjectReference obj) {
        try {
            if (obj instanceof ArrayReference) {
                ArrayReference arr = (ArrayReference) obj;
                List<Object> out = new ArrayList<>();
                out.add("LIST");
                List<Value> values = arr.length() > 0 ? arr.getValues() : Collections.emptyList();
                for (Value el : values) {
                    out.add(encodeValue(ctx, el));
                }
                return out;
            }
            if (obj instanceof StringReference) {
                // Strings are encoded inline, but if one is reached as an object
                // (shouldn't normally happen) encode it as a single-field box.
                return Arrays.asList("INSTANCE", "String");
            }

            ReferenceType type = obj.referenceType();
            String className = simpleName(type.name());

            // Lists / Sets / Maps from the JDK: render with their logical shape.
            if (isInstanceOf(type, "java.util.Map")) {
                return encodeMap(ctx, obj);
            }
            if (isInstanceOf(type, "java.util.Collection")) {
                return encodeCollection(ctx, obj, isInstanceOf(type, "java.util.Set"));
            }

            // Boxed primitives -> show their value inline-ish as an instance with one field.
            // General instance: enumerate declared (non-static) fields.
            List<Object> out = new ArrayList<>();
            out.add("INSTANCE");
            out.add(className);
            List<Field> fields = type.allFields();
            Map<Field, Value> fieldValues = obj.getValues(fields);
            for (Field f : fields) {
                if (f.isStatic()) continue;
                if (f.isSynthetic()) continue;
                Object encoded = encodeValue(ctx, fieldValues.get(f));
                out.add(Arrays.asList(f.name(), encoded));
            }
            return out;
        } catch (Exception e) {
            return Arrays.asList("INSTANCE", "object");
        }
    }

    Object encodeMap(HeapCtx ctx, ObjectReference obj) {
        List<Object> out = new ArrayList<>();
        out.add("DICT");
        try {
            ObjectReference entrySet = (ObjectReference) invoke(ctx, obj, "entrySet", "()Ljava/util/Set;");
            ObjectReference iter = (ObjectReference) invoke(ctx, entrySet, "iterator", "()Ljava/util/Iterator;");
            while (true) {
                Value hasNext = invoke(ctx, iter, "hasNext", "()Z");
                if (!(hasNext instanceof BooleanValue) || !((BooleanValue) hasNext).value()) break;
                ObjectReference entry = (ObjectReference) invoke(ctx, iter, "next", "()Ljava/lang/Object;");
                Value k = invoke(ctx, entry, "getKey", "()Ljava/lang/Object;");
                Value v = invoke(ctx, entry, "getValue", "()Ljava/lang/Object;");
                out.add(Arrays.asList(encodeValue(ctx, k), encodeValue(ctx, v)));
            }
        } catch (Exception e) {
            // Fall back to an opaque instance if reflection-style calls fail.
            return Arrays.asList("INSTANCE", simpleName(obj.referenceType().name()));
        }
        return out;
    }

    Object encodeCollection(HeapCtx ctx, ObjectReference obj, boolean isSet) {
        List<Object> out = new ArrayList<>();
        out.add(isSet ? "SET" : "LIST");
        try {
            ObjectReference iter = (ObjectReference) invoke(ctx, obj, "iterator", "()Ljava/util/Iterator;");
            while (true) {
                Value hasNext = invoke(ctx, iter, "hasNext", "()Z");
                if (!(hasNext instanceof BooleanValue) || !((BooleanValue) hasNext).value()) break;
                Value el = invoke(ctx, iter, "next", "()Ljava/lang/Object;");
                out.add(encodeValue(ctx, el));
            }
        } catch (Exception e) {
            return Arrays.asList("INSTANCE", simpleName(obj.referenceType().name()));
        }
        return out;
    }

    // Synchronous method invocation on the (suspended) debuggee thread.  Used
    // sparingly, only to read JDK collection contents.
    Value invoke(HeapCtx ctx, ObjectReference target, String name, String sig) throws Exception {
        ThreadReference thread = currentThread;
        if (thread == null) throw new IllegalStateException("no thread");
        ReferenceType type = target.referenceType();
        List<Method> methods = type.methodsByName(name);
        Method m = null;
        for (Method cand : methods) {
            if (cand.signature().equals(sig)) { m = cand; break; }
        }
        if (m == null && !methods.isEmpty()) m = methods.get(0);
        if (m == null) throw new NoSuchMethodException(name);
        return target.invokeMethod(thread, m, Collections.emptyList(),
                ObjectReference.INVOKE_SINGLE_THREADED);
    }

    ThreadReference currentThread = null;

    boolean isInstanceOf(ReferenceType type, String iface) {
        if (!(type instanceof ClassType)) {
            // interfaces of arrays etc.
            return false;
        }
        ClassType ct = (ClassType) type;
        // Walk superclasses + interfaces.
        Deque<ReferenceType> stack = new ArrayDeque<>();
        stack.add(ct);
        Set<String> visited = new HashSet<>();
        while (!stack.isEmpty()) {
            ReferenceType t = stack.pop();
            if (!visited.add(t.name())) continue;
            if (t.name().equals(iface)) return true;
            if (t instanceof ClassType) {
                ClassType c = (ClassType) t;
                ClassType sup = c.superclass();
                if (sup != null) stack.add(sup);
                for (InterfaceType it : c.allInterfaces()) stack.add(it);
            }
        }
        return false;
    }

    static String simpleName(String fqn) {
        int dot = fqn.lastIndexOf('.');
        String s = dot >= 0 ? fqn.substring(dot + 1) : fqn;
        return s.replace('$', '.');
    }

    String exceptionMessage(ExceptionEvent ee) {
        try {
            ObjectReference exc = ee.exception();
            ReferenceType t = exc.referenceType();
            String cls = t.name();
            String msg = null;
            try {
                Value m = invoke(null, exc, "getMessage", "()Ljava/lang/String;");
                if (m instanceof StringReference) msg = ((StringReference) m).value();
            } catch (Exception ignore) {}
            String full = (msg == null || msg.isEmpty()) ? cls : (cls + ": " + msg);
            return full.split("\n")[0];   // first line only, no stack dump
        } catch (Exception e) {
            return "Exception";
        }
    }

    // ---- I/O helpers ---------------------------------------------------------

    Thread pump(InputStream in, StringBuilder sink) {
        return new Thread(() -> {
            try {
                byte[] buf = new byte[4096];
                int n;
                while ((n = in.read(buf)) != -1) {
                    synchronized (sink) {
                        sink.append(new String(buf, 0, n, StandardCharsets.UTF_8));
                    }
                }
            } catch (IOException ignore) {}
        });
    }

    Map<String, Object> buildResult() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("code", source);
        result.put("trace", trace);
        result.put("lang", "java");
        return result;
    }

    // ---- minimal JSON writer (no external deps) ------------------------------

    static String toJson(Object o) {
        StringBuilder sb = new StringBuilder();
        writeJson(sb, o);
        return sb.toString();
    }

    @SuppressWarnings("unchecked")
    static void writeJson(StringBuilder sb, Object o) {
        if (o == null) {
            sb.append("null");
        } else if (o instanceof String) {
            writeString(sb, (String) o);
        } else if (o instanceof Boolean) {
            sb.append(((Boolean) o) ? "true" : "false");
        } else if (o instanceof Double || o instanceof Float) {
            double d = ((Number) o).doubleValue();
            if (Double.isNaN(d) || Double.isInfinite(d)) {
                // JSON has no NaN/Infinity; emit as a token-like string.
                writeString(sb, String.valueOf(d));
            } else if (d == Math.rint(d) && !Double.isInfinite(d) && Math.abs(d) < 1e15) {
                // keep a trailing .0 so floats remain visually distinct from ints
                sb.append(d);
            } else {
                sb.append(d);
            }
        } else if (o instanceof Number) {
            sb.append(o.toString());
        } else if (o instanceof Map) {
            sb.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> e : ((Map<?, ?>) o).entrySet()) {
                if (!first) sb.append(',');
                first = false;
                writeString(sb, String.valueOf(e.getKey()));
                sb.append(':');
                writeJson(sb, e.getValue());
            }
            sb.append('}');
        } else if (o instanceof Iterable) {
            sb.append('[');
            boolean first = true;
            for (Object el : (Iterable<Object>) o) {
                if (!first) sb.append(',');
                first = false;
                writeJson(sb, el);
            }
            sb.append(']');
        } else {
            writeString(sb, o.toString());
        }
    }

    static void writeString(StringBuilder sb, String s) {
        sb.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                case '\b': sb.append("\\b"); break;
                case '\f': sb.append("\\f"); break;
                default:
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
            }
        }
        sb.append('"');
    }
}
