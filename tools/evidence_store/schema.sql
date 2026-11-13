-- Explicit local v1 initialization, not an online schema migration mechanism.
CREATE SCHEMA IF NOT EXISTS jjamtong_evidence_v1;
CREATE TABLE IF NOT EXISTS jjamtong_evidence_v1.analysis (
    tenant_id text NOT NULL,
    run_id text NOT NULL,
    index_sha256 text NOT NULL,
    projection_sha256 text NOT NULL,
    document jsonb NOT NULL,
    coverage jsonb NOT NULL,
    PRIMARY KEY (tenant_id, run_id)
);
CREATE TABLE IF NOT EXISTS jjamtong_evidence_v1.method (
    tenant_id text NOT NULL,
    run_id text NOT NULL,
    analyzer text NOT NULL,
    symbol text NOT NULL,
    PRIMARY KEY (tenant_id, run_id, analyzer, symbol),
    FOREIGN KEY (tenant_id, run_id) REFERENCES jjamtong_evidence_v1.analysis
);
CREATE TABLE IF NOT EXISTS jjamtong_evidence_v1.call (
    tenant_id text NOT NULL,
    run_id text NOT NULL,
    analyzer text NOT NULL,
    ordinal integer NOT NULL,
    caller text NOT NULL,
    target text NOT NULL,
    evidence jsonb NOT NULL,
    PRIMARY KEY (tenant_id, run_id, analyzer, ordinal),
    FOREIGN KEY (tenant_id, run_id, analyzer, caller)
        REFERENCES jjamtong_evidence_v1.method,
    FOREIGN KEY (tenant_id, run_id, analyzer, target)
        REFERENCES jjamtong_evidence_v1.method
);
CREATE INDEX IF NOT EXISTS call_outbound
    ON jjamtong_evidence_v1.call (tenant_id, run_id, analyzer, caller, target, ordinal);
