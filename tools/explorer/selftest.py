"""Offline transport smoke: saved evidence only, never research execution."""

import asyncio
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import evidence
import httpx
from graphql_server import app, schema
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def exercise_transports() -> None:
    """Exercise real protocol serialization and rejection boundaries against saved files."""
    for evidence_id in evidence.FILES:
        evidence.read_evidence(evidence_id)
    for bad_id in ("../pyproject.toml", "C:/Windows/win.ini", "missing"):
        try:
            evidence.read_evidence(bad_id)
        except ValueError:
            pass
        else:
            raise AssertionError("Untrusted evidence ID accepted")
    result = await schema.execute("{ experiments(limit: 2) { signal costBps } studySummary }")
    assert not result.errors and len(result.data["experiments"]) == 2
    assert (await schema.execute("{ experiments(limit: 101) { signal } }")).errors
    assert (await schema.execute("mutation { studySummary }")).errors
    assert (
        await schema.execute("{" + " ".join(f"a{i}: studySummary" for i in range(200)) + "}")
    ).errors
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        response = await client.post("/graphql/", json={"query": "{ evidenceIds }"})
        assert (
            response.status_code == 200
            and "historical-study" in response.json()["data"]["evidenceIds"]
        )
        assert (await client.post("/graphql/", content=b"x" * 16385)).status_code == 413
        assert (
            await client.post(
                "/graphql/", headers={"host": "attacker.example"}, json={"query": "{ evidenceIds }"}
            )
        ).status_code == 400
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).with_name("mcp_server.py"))],
        env={**os.environ, "FACTORFORGE_REPORTS_DIR": os.environ["FACTORFORGE_REPORTS_DIR"]},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        catalog = await session.list_tools()
        assert {tool.name for tool in catalog.tools} == {
            "study_summary",
            "list_experiments",
            "list_evidence",
            "read_receipt",
        }
        assert all(tool.annotations.readOnlyHint for tool in catalog.tools)
        result = await session.call_tool("read_receipt", {"evidence_id": "historical-study"})
        assert not result.isError
        result = await session.call_tool("read_receipt", {"evidence_id": "../pyproject.toml"})
        assert result.isError
        result = await session.call_tool("list_experiments", {"limit": 101})
        assert result.isError
    print(
        json.dumps(
            {
                "status": "passed",
                "receipts": len(evidence.FILES),
                "experiments": len(evidence.study().experiments),
                "graphql_http": True,
                "mcp_stdio": True,
            }
        )
    )


def write_fixtures(directory: Path) -> None:
    """Author transport-only records; no private reports or research run is needed."""
    sample = {
        "scope": "Synthetic transport fixture; not research results",
        "source_rows": 0,
        "source_count": 0,
        "start_date": "2000-01-01",
        "end_date": "2000-01-02",
        "experiments": [
            {
                "signal": name,
                "cost_bps": 0,
                "status": "fixture",
                "n": 0,
                "annualized_sharpe": None,
                "total_return": None,
                "max_drawdown": None,
                "hac_t": None,
            }
            for name in ("fixture-a", "fixture-b")
        ],
    }
    for evidence_id, relative in evidence.FILES.items():
        payload = {"schema_version": "transport-fixture-v1"}
        if evidence_id == "historical-study":
            payload = sample
        elif evidence_id == "historical-manifest":
            payload = {"fixture.json": "0" * 64}
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")


async def main() -> None:
    """Isolate both protocols from local or private operator data."""
    previous = os.environ.get("FACTORFORGE_REPORTS_DIR")
    try:
        with TemporaryDirectory(prefix="factorforge-explorer-") as temporary:
            directory = Path(temporary)
            write_fixtures(directory)
            os.environ["FACTORFORGE_REPORTS_DIR"] = str(directory)
            await exercise_transports()
    finally:
        if previous is None:
            os.environ.pop("FACTORFORGE_REPORTS_DIR", None)
        else:
            os.environ["FACTORFORGE_REPORTS_DIR"] = previous


if __name__ == "__main__":
    asyncio.run(main())
