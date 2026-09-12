"""Official MCP SDK stdio server exposing only saved public evidence."""

import evidence
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

mcp = FastMCP("FactorForge evidence explorer")
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


@mcp.tool(annotations=READ_ONLY)
def study_summary() -> dict:
    """Read the historical study scope, dates, and source counts; no research runs."""
    return evidence.study().model_dump(exclude={"experiments"})


@mcp.tool(annotations=READ_ONLY)
def list_experiments(limit: int = 20, offset: int = 0) -> list[dict]:
    """Read saved historical experiments, with limit 1..100 and offset 0..1000."""
    return evidence.experiments(limit, offset)


@mcp.tool(annotations=READ_ONLY)
def list_evidence() -> list[str]:
    """List the fixed evidence IDs accepted by read_receipt."""
    return list(evidence.FILES)


@mcp.tool(annotations=READ_ONLY)
def read_receipt(evidence_id: str) -> dict:
    """Read an allowlisted report and digest; IDs are never filesystem paths."""
    return evidence.read_evidence(evidence_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
