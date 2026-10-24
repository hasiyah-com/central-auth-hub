"""Read-only check inside Hub container. No login/token/DB requests or config writes."""

import argparse, asyncio, json, sys
from app.config import settings
from app.services.if_candidate_shadow import evaluate_candidate

V = [12, 1, 1, 1, 0, 1, 0, 0, 5, 1, 0, 1, 100, 0, 1, 0, 0, 0.8, 0.8, 0, 365, 0, 0]


async def main():
    result = await evaluate_candidate(V)
    ok = bool(
        result
        and result.get("status") == "evaluated"
        and len(result.get("explanation", [])) == 23
        and result.get("applied_to_access") is False
    )
    print(
        json.dumps(
            dict(
                scope="synthetic stateless candidate probe; not user login or baseline deployment certification",
                passed=ok,
                candidate=result,
            ),
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
