package io.jjamtong.analysis;

import java.io.IOException;
import java.io.OutputStream;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Objects;

/** Local v1 publication. Byte limits do not bound the analysis Map or JVM memory. */
final class ResultPublication {
    static final long MAX_BYTES = 10L * 1024 * 1024;

    private ResultPublication() { }

    static long publish(Path destination, Object result) throws IOException {
        return publish(destination, result, MAX_BYTES);
    }

    // A smaller budget lets the oracle exercise byte boundaries without a large analysis.
    static long publish(Path destination, Object result, long maxBytes) throws IOException {
        if (maxBytes <= 0) throw new IllegalArgumentException("output budget must be positive");
        Path absolute = destination.toAbsolutePath();
        Files.createDirectories(absolute.getParent());
        Path temporary = Files.createTempFile(absolute.getParent(), ".methods-", ".json");
        try {
            var output = new LimitedOutput(Files.newOutputStream(temporary), maxBytes);
            try (output; var writer = new OutputStreamWriter(output, StandardCharsets.UTF_8)) {
                Model.JSON.toJson(result, writer);
                writer.write('\n');
            }
            // close must finish encoding and enforce the budget before publication.
            Files.move(temporary, absolute, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            return output.bytes;
        } finally {
            Files.deleteIfExists(temporary);
        }
    }

    private static final class LimitedOutput extends OutputStream {
        private final OutputStream output;
        private final long limit;
        private long bytes;

        private LimitedOutput(OutputStream output, long limit) {
            this.output = output;
            this.limit = limit;
        }

        private void reserve(int length) {
            if (length > limit - bytes) {
                throw new IllegalStateException(limit == MAX_BYTES
                        ? "analysis output exceeds 10 MiB"
                        : "analysis output exceeds " + limit + " bytes");
            }
        }

        @Override public void write(int value) throws IOException {
            reserve(1);
            output.write(value);
            bytes++;
        }

        @Override public void write(byte[] values, int offset, int length) throws IOException {
            Objects.checkFromIndexSize(offset, length, values.length);
            reserve(length);
            output.write(values, offset, length);
            bytes += length;
        }

        @Override public void flush() throws IOException { output.flush(); }
        @Override public void close() throws IOException { output.close(); }
    }
}
