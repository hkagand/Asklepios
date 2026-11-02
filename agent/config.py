"""Settings from the environment, with agent/.env for local values."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _read_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True)
class Settings:
    llm_base_url: str
    llm_model: str
    llm_api_key: str | None
    reasoning_effort: str | None
    temperature: float | None
    fhir_base_url: str
    max_steps: int
    audit_log: Path
    plan_cache: Path
    national_base_url: str = "http://localhost:8090"
    # The clinical model for considerations during a visit (considerations.py); off unless both are set.
    clinical_llm_base_url: str | None = None
    clinical_llm_model: str | None = None
    clinical_llm_api_key: str | None = None

    @property
    def clinical(self) -> Settings | None:
        """Settings for the clinical model's client, or None when it is not configured."""
        if not (self.clinical_llm_base_url and self.clinical_llm_model):
            return None
        return replace(
            self, llm_base_url=self.clinical_llm_base_url, llm_model=self.clinical_llm_model,
            llm_api_key=self.clinical_llm_api_key, reasoning_effort=None, temperature=0.0,
        )


def load_settings() -> Settings:
    _read_env_file(HERE / ".env")
    missing = [name for name in ("LLM_BASE_URL", "LLM_MODEL") if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Set {' and '.join(missing)} in the environment or in {HERE / '.env'} (see .env.example).")
    temperature = os.environ.get("LLM_TEMPERATURE")
    return Settings(
        llm_base_url=os.environ["LLM_BASE_URL"].rstrip("/"),
        llm_model=os.environ["LLM_MODEL"],
        llm_api_key=os.environ.get("LLM_API_KEY") or None,
        reasoning_effort=os.environ.get("LLM_REASONING_EFFORT") or None,
        temperature=float(temperature) if temperature else None,
        fhir_base_url=os.environ.get("FHIR_BASE_URL", "http://localhost:8080/fhir").rstrip("/"),
        max_steps=int(os.environ.get("AGENT_MAX_STEPS", "8")),
        audit_log=Path(os.environ.get("AGENT_AUDIT_LOG", HERE / "logs" / "audit.jsonl")),
        plan_cache=Path(os.environ.get("AGENT_PLAN_CACHE", HERE / "cache" / "plans")),
        national_base_url=os.environ.get("NATIONAL_BASE_URL", "http://localhost:8090").rstrip("/"),
        clinical_llm_base_url=os.environ.get("CLINICAL_LLM_BASE_URL", "").rstrip("/") or None,
        clinical_llm_model=os.environ.get("CLINICAL_LLM_MODEL") or None,
        clinical_llm_api_key=os.environ.get("CLINICAL_LLM_API_KEY") or None,
    )
