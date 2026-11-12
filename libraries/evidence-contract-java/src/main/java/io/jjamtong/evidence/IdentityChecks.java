package io.jjamtong.evidence;

import java.util.Locale;
import java.util.Objects;

final class IdentityChecks {
    private IdentityChecks() {}

    static String identifier(String value, String field) {
        Objects.requireNonNull(value, field);
        if (value.isBlank()) {
            throw new IllegalArgumentException(field + " must not be blank");
        }
        return value;
    }

    static String digest(String value, String field) {
        identifier(value, field);
        if (!value.matches("[0-9a-fA-F]{64}")) {
            throw new IllegalArgumentException(field + " must be a SHA-256 hex digest");
        }
        return value.toLowerCase(Locale.ROOT);
    }
}
