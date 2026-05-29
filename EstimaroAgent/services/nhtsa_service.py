"""Free VIN decoder via NHTSA vPIC API. No key needed."""
import httpx
from loguru import logger
from models.job_spec import VehicleFingerprint


NHTSA_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"


async def decode_vin(vin: str) -> VehicleFingerprint:
    vin = vin.strip().upper()
    if len(vin) != 17:
        raise ValueError(f"VIN must be 17 chars, got {len(vin)}")

    url = NHTSA_URL.format(vin=vin)
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()

    results = data.get("Results", [{}])[0]

    def g(key: str) -> str:
        return (results.get(key) or "").strip()

    try:
        year = int(g("ModelYear"))
    except (ValueError, TypeError):
        year = 0

    fp = VehicleFingerprint(
        vin=vin,
        year=year,
        make=g("Make"),
        model=g("Model"),
        trim=g("Trim") or None,
        engine=" ".join(filter(None, [g("EngineCylinders"), g("DisplacementL"), g("FuelTypePrimary")])).strip() or None,
        transmission=g("TransmissionStyle") or None,
        raw_vpic=results,
    )
    logger.info(f"Decoded VIN {vin}: {fp.year} {fp.make} {fp.model}")
    return fp


if __name__ == "__main__":
    import asyncio
    test_vins = [
        "2HGFC2F59JH123456",
        "1HGCM82633A123456",
    ]
    for v in test_vins:
        try:
            fp = asyncio.run(decode_vin(v))
            print(f"\n{v}:")
            print(f"  {fp.year} {fp.make} {fp.model} {fp.trim or ''}")
            print(f"  Engine: {fp.engine}")
        except Exception as e:
            print(f"{v}: ERROR {e}")
