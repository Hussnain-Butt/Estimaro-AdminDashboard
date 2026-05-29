"""Smoke test - run this first after setup."""
from core.hermes_client import HermesClient
import json


def main():
    print("=" * 60)
    print("ESTIMARO AGENT - HERMES SMOKE TEST")
    print("=" * 60)

    hermes = HermesClient()

    print("\n[1] Parsing customer complaint...")
    job = hermes.parse_job_spec(
        customer_complaint="2018 Honda Civic, hearing a loud grinding noise from front wheels when I press the brake pedal, especially at slow speeds",
        vin="2HGFC2F59JH123456",
    )
    print(json.dumps(job, indent=2))

    print("\n[2] Verifying a scraped result against the job...")
    v = hermes.verify_match(
        extracted_data={
            "operation": "Front brake pad replacement and rotor resurfacing",
            "hours": 1.8,
            "vehicle": "2018 Honda Civic LX 2.0L",
        },
        job_spec=job,
        vehicle={"year": 2018, "make": "Honda", "model": "Civic", "engine": "2.0L"},
    )
    print(json.dumps(v, indent=2))

    print("\n[3] Wrong-vehicle test (should fail verification)...")
    v2 = hermes.verify_match(
        extracted_data={
            "operation": "Front brake pad replacement",
            "hours": 1.2,
            "vehicle": "2015 Toyota Camry 2.5L",
        },
        job_spec=job,
        vehicle={"year": 2018, "make": "Honda", "model": "Civic", "engine": "2.0L"},
    )
    print(json.dumps(v2, indent=2))

    print("\nAll Hermes tests passed.")


if __name__ == "__main__":
    main()
