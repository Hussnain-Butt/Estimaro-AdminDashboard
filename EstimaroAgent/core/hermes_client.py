"""Local Hermes 3 (via Ollama) - JSON extraction + verification engine."""
import json
from typing import Any, Optional
import ollama
from loguru import logger

from config import settings


class HermesClient:
    def __init__(self, model: Optional[str] = None, host: Optional[str] = None):
        self.model = model or settings.HERMES_MODEL
        self.client = ollama.Client(host=host or settings.OLLAMA_HOST)

    def chat_json(self, prompt: str, system: Optional[str] = None, temperature: float = 0.1) -> dict[str, Any]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat(
            model=self.model,
            messages=messages,
            format="json",
            options={"temperature": temperature},
        )
        raw = response["message"]["content"]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.error(f"Hermes returned invalid JSON: {raw}")
            return {}

    def parse_job_spec(self, customer_complaint: str, vin: Optional[str] = None) -> dict:
        system = (
            "You are an auto repair intake assistant. Extract structured JSON "
            "from customer complaints. Always return valid JSON only, no extra text."
        )
        prompt = f"""Extract a JobSpec from this customer complaint.

Customer complaint: "{customer_complaint}"
VIN: {vin or 'unknown'}

Return JSON with EXACTLY these keys:
- system: one of [braking, engine, transmission, suspension, electrical, hvac, exhaust, cooling, steering, other]
- subsystem: specific area like "front_brakes", "rear_brakes", "alternator", "ac_compressor"
- symptom: short symptom phrase
- severity: one of [low, medium, high, critical]
- keywords: array of 3-5 portal-search keywords
- needs_diagnosis: true if vague symptom, false if specific repair request

Return JSON only."""
        return self.chat_json(prompt, system)

    def verify_match(self, extracted_data: dict, job_spec: dict, vehicle: dict) -> dict:
        prompt = f"""Verify if a scraped result matches the customer's job and vehicle.

Customer JobSpec: {json.dumps(job_spec)}
Vehicle: {json.dumps(vehicle)}
Scraped Data: {json.dumps(extracted_data)}

Return JSON with:
- match: boolean
- confidence: float 0.0 to 1.0
- reason: short explanation
- issues: array of mismatch descriptions (empty if all good)"""
        return self.chat_json(prompt)

    def decide_next_action(self, page_text: str, goal: str, history: list[str]) -> dict:
        """Fallback decision-maker when no vision is available."""
        prompt = f"""You are guiding a browser automation agent.

Goal: {goal}
Recent page text (truncated): {page_text[:2000]}
Past actions: {json.dumps(history[-5:])}

Decide next action. Return JSON:
- action: one of [click, type, navigate, extract, done, ask_human]
- target: CSS selector or URL or field-name
- value: text to type or extract key
- reason: short why"""
        return self.chat_json(prompt)


if __name__ == "__main__":
    print("=" * 60)
    print("Testing Hermes client...")
    print("=" * 60)

    hermes = HermesClient()

    print("\n--- Test 1: Parse Job Spec ---")
    result = hermes.parse_job_spec(
        customer_complaint="My 2018 Honda Civic makes grinding noise when I brake, especially at low speeds",
        vin="2HGFC2F59JH123456"
    )
    print(json.dumps(result, indent=2))

    print("\n--- Test 2: Verify Match ---")
    verification = hermes.verify_match(
        extracted_data={
            "operation": "Front brake pad replacement",
            "hours": 1.2,
            "vehicle": "2018 Honda Civic LX 2.0L"
        },
        job_spec=result,
        vehicle={"year": 2018, "make": "Honda", "model": "Civic", "engine": "2.0L"}
    )
    print(json.dumps(verification, indent=2))

    print("\nHermes client working!")
