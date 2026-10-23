"""Reads one patient's chart from the FHIR server. The only writes are the marks in marks.py."""

from __future__ import annotations

import asyncio

import httpx

PATIENT_SEARCHES = (
    "Condition",
    "MedicationRequest",
    "AllergyIntolerance",
    "Observation",
    "DiagnosticReport",
    "DocumentReference",
    "Encounter",
    "ServiceRequest",
    "Appointment",
    "Task",
    "Communication",
)


WRITE_HEADERS = {"Content-Type": "application/fhir+json; charset=utf-8", "Prefer": "return=representation"}


class FhirError(Exception):
    pass


class PatientNotFound(FhirError):
    pass


class FhirClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        # no-cache: HAPI otherwise answers a repeated search from its cache for a minute, hiding marks just written.
        headers = {"Accept": "application/fhir+json", "Cache-Control": "no-cache"}
        self._client = httpx.AsyncClient(timeout=30, headers=headers)

    async def close(self) -> None:
        await self._client.aclose()

    async def _send(self, method: str, url: str, **options: object) -> dict:
        try:
            response = await self._client.request(method, url, **options)
        except httpx.HTTPError as error:
            raise FhirError(f"Could not reach the FHIR server at {self.base_url} ({error}).") from error
        if response.status_code in (404, 410):
            raise PatientNotFound(f"{url} was not found on the FHIR server.")
        if response.is_error:
            raise FhirError(f"The FHIR server answered {response.status_code} for {method} {url}: {response.text[:300]}")
        return response.json()

    async def _get(self, url: str, params: dict | None = None) -> dict:
        return await self._send("GET", url, params=params)

    async def read(self, resource_type: str, resource_id: str) -> dict:
        return await self._get(f"{self.base_url}/{resource_type}/{resource_id}")

    async def create(self, resource: dict) -> dict:
        """POSTs a new resource; the server assigns its id."""
        return await self._send("POST", f"{self.base_url}/{resource['resourceType']}", json=resource, headers=WRITE_HEADERS)

    async def update(self, resource: dict) -> dict:
        url = f"{self.base_url}/{resource['resourceType']}/{resource['id']}"
        return await self._send("PUT", url, json=resource, headers=WRITE_HEADERS)

    async def search(self, resource_type: str, params: dict[str, str]) -> list[dict]:
        """Runs a search and follows `next` links until every page has been read."""
        resources: list[dict] = []
        url: str | None = f"{self.base_url}/{resource_type}"
        query: dict | None = {"_count": "200", **params}
        while url:
            bundle = await self._get(url, query)
            resources += [
                entry["resource"]
                for entry in bundle.get("entry", [])
                if entry.get("resource", {}).get("resourceType") == resource_type
            ]
            url = next((link["url"] for link in bundle.get("link", []) if link.get("relation") == "next"), None)
            query = None
        return resources

    async def patient_chart(self, patient_id: str) -> tuple[dict, dict[str, list[dict]]]:
        patient, *found = await asyncio.gather(
            self._get(f"{self.base_url}/Patient/{patient_id}"),
            *(self.search(resource_type, {"patient": patient_id}) for resource_type in PATIENT_SEARCHES),
        )
        return patient, dict(zip(PATIENT_SEARCHES, found))
