"""Expose retained study gauges to Prometheus without rerunning experiments."""

import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def render(path: Path) -> bytes:
    """Bound input and derive gauges from retained evidence, never invented live counters."""
    with path.open("rb") as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("Report exceeds limit")
    report = json.loads(raw)
    keys = ("completed", "total", "source_rows", "source_count", "span_count")
    for key in keys:
        if type(report[key]) is not int or not 0 <= report[key] <= 10**9:
            raise ValueError("Invalid retained count")
    if report["completed"] > report["total"] or len(report["experiments"]) != report["total"]:
        raise ValueError("Report denominator mismatch")
    lines: list[str] = []
    for key in keys:
        name = f"factorforge_retained_study_{key}"
        lines.extend(
            (
                f"# HELP {name} Saved historical study {key}; not live research.",
                f"# TYPE {name} gauge",
                f"{name} {report[key]}",
            )
        )
    digest = hashlib.sha256(raw).hexdigest()
    lines.extend(
        (
            "# TYPE factorforge_retained_report_info gauge",
            f'factorforge_retained_report_info{{sha256="{digest}"}} 1',
        )
    )
    return ("\n".join(lines) + "\n").encode()


def serve(path: Path, host: str, port: int) -> None:
    """Read on each scrape so file updates appear without storing private metric labels."""

    class Handler(BaseHTTPRequestHandler):
        """Expose only a fixed metrics route; malformed evidence returns no numeric results."""

        def do_GET(self) -> None:
            """Publish gauges only after validating the complete bounded report."""
            if self.path != "/metrics":
                self.send_error(404)
                return
            try:
                body = render(path)
            except (OSError, ValueError, KeyError, TypeError):
                self.send_error(503, "Retained evidence unavailable")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            """Avoid reflecting arbitrary HTTP paths into persistent logs."""

    HTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9127)
    args = parser.parse_args()
    serve(args.report, args.host, args.port)
