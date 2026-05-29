"""Cross-source verification and confidence scoring."""
from statistics import median
from loguru import logger
from models.job_spec import LaborResult, PartResult, VerificationResult
from core.hermes_client import HermesClient


hermes = HermesClient()


def labor_consensus(results: list[LaborResult]) -> dict:
    """Take labor times from multiple sources, compute median, flag outliers."""
    if not results:
        return {"hours": None, "confidence": 0.0, "outliers": []}

    hours_list = [r.hours for r in results]
    med = median(hours_list)

    outliers = []
    if len(hours_list) > 1:
        for r in results:
            deviation = abs(r.hours - med) / med if med else 0
            if deviation > 0.30:
                outliers.append({"source": r.source, "hours": r.hours, "deviation": deviation})

    confidence = max(0.0, 1.0 - (len(outliers) / len(results)))
    return {
        "hours": med,
        "confidence": confidence,
        "outliers": outliers,
        "sources_used": [r.source for r in results],
    }


def part_consensus(results: list[PartResult]) -> dict:
    """Find best-matching part across vendors (cheapest verified OEM match)."""
    if not results:
        return {"part": None, "confidence": 0.0}

    by_oem: dict[str, list[PartResult]] = {}
    for r in results:
        key = r.oem_number or r.name
        by_oem.setdefault(key, []).append(r)

    best_oem = max(by_oem.items(), key=lambda kv: len(kv[1]))
    matched_parts = best_oem[1]

    priced = [p for p in matched_parts if p.price is not None]
    cheapest = min(priced, key=lambda p: p.price) if priced else matched_parts[0]

    confidence = min(1.0, len(matched_parts) / 3.0)
    return {
        "part": cheapest.model_dump(),
        "confidence": confidence,
        "agreeing_sources": len(matched_parts),
    }


def verify_with_hermes(extracted: dict, job_spec: dict, vehicle: dict) -> VerificationResult:
    raw = hermes.verify_match(extracted, job_spec, vehicle)
    return VerificationResult(
        match=bool(raw.get("match", False)),
        confidence=float(raw.get("confidence", 0.0)),
        reason=raw.get("reason", ""),
        issues=raw.get("issues", []),
    )


if __name__ == "__main__":
    sample = [
        LaborResult(operation="brake pad replacement", hours=1.2, source="alldata", vehicle_match={}),
        LaborResult(operation="brake pad replacement", hours=1.3, source="mitchell", vehicle_match={}),
        LaborResult(operation="brake pad replacement", hours=2.5, source="motor", vehicle_match={}),
    ]
    print(labor_consensus(sample))
