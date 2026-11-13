"""Postgres transactional outbox -> replaceable database read model.

This tests at-least-once delivery. It does not claim distributed transactions,
Kafka/CDC integration, a production policy engine, or physical erasure.
"""
import argparse
import json
import os

from .stores import Postgres, STORES


class Outbox:
    def __init__(self, primary, sink, stream, consumer):
        self.primary, self.sink = primary, sink
        self.stream, self.consumer = stream, consumer
        primary.sql("CREATE TABLE IF NOT EXISTS storage_lab_outbox (offset_id BIGSERIAL PRIMARY KEY, stream TEXT NOT NULL, event_id TEXT UNIQUE NOT NULL, payload JSONB NOT NULL)")
        primary.sql("CREATE TABLE IF NOT EXISTS storage_lab_checkpoints (consumer TEXT NOT NULL, stream TEXT NOT NULL, offset_id BIGINT NOT NULL DEFAULT 0, PRIMARY KEY(consumer,stream))")
        primary.sql("INSERT INTO storage_lab_checkpoints(consumer,stream) VALUES(%s,%s) ON CONFLICT DO NOTHING", (consumer, stream))

    def publish(self, event_id, row):
        # Evidence and delivery obligation commit in one real Postgres transaction.
        with self.primary.connection.transaction():
            previous = self.primary.sql("SELECT payload FROM storage_lab_outbox WHERE event_id=%s", (event_id,))
            if previous:
                if previous[0]["payload"] != row:
                    raise ValueError("event identity reused with different payload")
                return
            self.primary.put([row])
            self.primary.sql("INSERT INTO storage_lab_outbox(stream,event_id,payload) VALUES(%s,%s,%s::jsonb)", (self.stream, event_id, json.dumps(row)))

    def watermark(self):
        expected = self.primary.sql("SELECT coalesce(max(offset_id),0) AS n FROM storage_lab_outbox WHERE stream=%s", (self.stream,))[0]["n"]
        actual = self.primary.sql("SELECT offset_id AS n FROM storage_lab_checkpoints WHERE consumer=%s AND stream=%s", (self.consumer, self.stream))[0]["n"]
        return dict(required=expected, applied=actual, status="ready" if actual >= expected else "stale")

    def drain(self, crash_after_apply=False):
        position = self.watermark()["applied"]
        pending = self.primary.sql("SELECT offset_id,payload FROM storage_lab_outbox WHERE stream=%s AND offset_id>%s ORDER BY offset_id", (self.stream, position))
        for item in pending:
            self.sink.put([item["payload"]])
            self.sink.flush()  # Elasticsearch search visibility must precede ACK.
            if crash_after_apply:
                os._exit(73)  # intentionally bypass Python cleanup: real process loss
            self.primary.sql("UPDATE storage_lab_checkpoints SET offset_id=%s WHERE consumer=%s AND stream=%s", (item["offset_id"], self.consumer, self.stream))
        return len(pending)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sink", choices=sorted(set(STORES) - {"postgres"}), required=True)
    parser.add_argument("--stream", required=True)
    parser.add_argument("--consumer", required=True)
    parser.add_argument("--crash-after-apply", action="store_true")
    args = parser.parse_args()
    primary, sink = Postgres(), STORES[args.sink]()
    try:
        Outbox(primary, sink, args.stream, args.consumer).drain(args.crash_after_apply)
    finally:
        sink.close()
        primary.close()


if __name__ == "__main__":
    main()
