"""Loopback-only GraphQL view over saved evidence; no mutations or execution."""

import evidence
import strawberry
import uvicorn
from starlette.applications import Starlette
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Mount
from strawberry.asgi import GraphQL
from strawberry.extensions import MaxTokensLimiter, QueryDepthLimiter
from strawberry.scalars import JSON


@strawberry.type
class Experiment:
    signal: str
    cost_bps: int
    status: str
    n: int
    annualized_sharpe: float | None
    total_return: float | None
    max_drawdown: float | None
    hac_t: float | None


@strawberry.type
class Query:
    @strawberry.field
    def study_summary(self) -> JSON:
        """Expose scope and source dates without implying benchmark completion."""
        return evidence.study().model_dump(exclude={"experiments"})

    @strawberry.field
    def experiments(self, limit: int = 20, offset: int = 0) -> list[Experiment]:
        """Return validated, bounded historical experiment pages."""
        return [Experiment(**item) for item in evidence.experiments(limit, offset)]

    @strawberry.field
    def evidence_ids(self) -> list[str]:
        """Discover only the fixed public report catalog."""
        return list(evidence.FILES)

    @strawberry.field
    def receipt(self, evidence_id: str) -> JSON:
        """Return saved receipt content and its digest, never a client path."""
        return evidence.read_evidence(evidence_id)


schema = strawberry.Schema(
    query=Query,
    extensions=[
        QueryDepthLimiter(max_depth=4),
        MaxTokensLimiter(max_token_count=500),
    ],
)
inner_app = Starlette(routes=[Mount("/graphql", GraphQL(schema, graphql_ide=None))])
inner_app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])


async def app(scope, receive, send) -> None:
    """Cap request bytes before JSON parsing and disable unused websocket transport."""
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
    if scope["type"] != "http":
        await inner_app(scope, receive, send)
        return
    body = bytearray()
    while True:
        event = await receive()
        if event["type"] == "http.disconnect":
            return
        body.extend(event.get("body", b""))
        if len(body) > 16384 or len(scope.get("query_string", b"")) > 16384:
            await PlainTextResponse("Request too large", status_code=413)(scope, receive, send)
            return
        if not event.get("more_body", False):
            break

    async def replay():
        """Replay the already bounded body to Strawberry once."""
        return {"type": "http.request", "body": bytes(body), "more_body": False}

    await inner_app(scope, replay, send)


def main() -> None:
    """Use a fixed loopback bind; external deployment needs its own security review."""
    uvicorn.run(app, host="127.0.0.1", port=8765, limit_concurrency=8)


if __name__ == "__main__":
    main()
