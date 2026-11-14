package io.jjamtong.otelcontext;

import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import io.opentelemetry.api.trace.TraceFlags;
import io.opentelemetry.api.trace.TraceState;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.Scope;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** JDK 21-only check that virtual threads follow the same explicit Context wrapping rule. */
public final class VirtualThreadContextTest {
    private static final String TRACE = "0123456789abcdef0123456789abcdef";
    private static final String SPAN = "0123456789abcdef";

    public static void main(String[] args) throws Exception {
        Span current = Span.wrap(SpanContext.create(TRACE, SPAN, TraceFlags.getDefault(), TraceState.getDefault()));
        try (ExecutorService executor = Executors.newVirtualThreadPerTaskExecutor()) {
            try (Scope scope = current.makeCurrent()) {
                if (scope == null) throw new AssertionError("scope was not created");
                if (executor.submit(() -> Span.current().getSpanContext().isValid()).get()) {
                    throw new AssertionError("unwrapped virtual worker inherited active parent context");
                }
                String traceId = Context.taskWrapping(executor).submit(
                        () -> Span.current().getSpanContext().getTraceId()).get();
                if (!TRACE.equals(traceId)) throw new AssertionError("wrapped virtual worker lost context");
            }
        }
        System.out.println("PASS virtual-thread wrapping check on " + Runtime.version());
    }
}
