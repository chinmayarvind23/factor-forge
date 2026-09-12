"""Retrospective LangSmith traces preserve real operation identity without raw source disclosure."""

import json

from langsmith import Client

from tools.tracking.langsmith_export import make_runs, upload_runs


def test_stable_parentage_and_metadata_only_projection() -> None:
    """Real SDK models bind timestamps and parentage while output omits prompt/source content."""
    rows = [
        {
            "operation_id": "original-operation",
            "kind": "llm",
            "sequence": 1,
            "reserved_at": "2026-09-11T12:00:00+00:00",
            "settled_at": "2026-09-11T12:00:05+00:00",
            "operation_status": "settled",
            "root_status": "held",
            "decision_status": None,
            "model_attempts": [{"messages": "PRIVATE_SOURCE_MARKER"}],
        }
    ]
    runs = make_runs(rows, "a" * 64, "factorforge-test")
    assert make_runs(rows, "a" * 64, "factorforge-test") == runs
    assert len(runs) == 2 and runs[1]["parent_run_id"] == runs[0]["id"]
    assert runs[1]["trace_id"] == runs[0]["id"]
    assert runs[1]["run_type"] == "llm"
    assert "PRIVATE_SOURCE_MARKER" not in json.dumps(runs)
    assert "retrospective" in runs[0]["tags"]


def test_real_sdk_upload_contract_has_no_raw_source() -> None:
    """Verify real SDK HTTP serialization against an owned loopback test server."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    captured = []

    class Handler(BaseHTTPRequestHandler):
        """Acknowledge trace requests without a hosted account or source-text storage."""

        def do_POST(self):
            """Retain the complete SDK JSON body and return a bounded acknowledgement."""
            captured.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            """Keep credentials and request metadata out of test output."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = Client(
            api_url=f"http://127.0.0.1:{server.server_port}",
            api_key="test-only",
            timeout_ms=3000,
            info={"version": "0.16.0"},
            auto_batch_tracing=False,
        )
        rows = [
            {
                "operation_id": "op-1",
                "kind": "experiment",
                "sequence": 1,
                "reserved_at": "2026-09-11T12:00:00+00:00",
                "settled_at": "2026-09-11T12:00:01+00:00",
                "operation_status": "settled",
                "model_attempts": [],
                "private": "PRIVATE_SOURCE_MARKER",
            }
        ]
        runs = make_runs(rows, "b" * 64, "factorforge-test")
        upload_runs(runs, "factorforge-test", client)
        assert len(captured) == 2
        assert captured[1]["parent_run_id"] == captured[0]["id"]
        assert captured[1]["session_name"] == "factorforge-test"
        assert "PRIVATE_SOURCE_MARKER" not in json.dumps(captured)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
