from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# pyright: reportMissingImports=false
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from doctor_agent.agent_system import run_payload
from doctor_agent.common import PROJECT_ROOT
from doctor_agent.memory.extractor import extract_structured_memory_from_dialogue
from doctor_agent.memory.store import MedicalMemoryStore
from doctor_agent.orchestrator import get_central_orchestrator
from doctor_agent.rag.qdrant_store import get_qdrant_store, index_knowledge_file


class ConsultRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str = "api-session"
    user_id: str = "api-user"
    patient_id: str = "default-patient"
    profile: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, str]] = Field(default_factory=list)


class MemoryPurgeRequest(BaseModel):
    user_id: str = "web-user"
    patient_id: str = "default-patient"
    session_id: str | None = None
    scope: str = "session"  # "session" or "patient"


class PatientSwitchRequest(BaseModel):
    new_user_id: str = "web-user"
    new_patient_id: str = "default-patient"
    old_user_id: str | None = None
    old_patient_id: str | None = None


class MemoryExtractAndSyncRequest(BaseModel):
    user_id: str = "web-user"
    patient_id: str = "default-patient"
    session_id: str = "api-session"
    messages: list[dict[str, str]] | str
    trigger_source: str = "idle_timeout"  # 'idle_timeout' or 'manual_user_request'


class MemoryConfirmRequest(BaseModel):
    confirmation_id: str
    user_id: str = "web-user"
    patient_id: str = "default-patient"
    decision: str  # 'approve' or 'reject'




class ReindexRequest(BaseModel):
    knowledge_path: str | None = None


class ProviderConfigItem(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class SettingsUpdateRequest(BaseModel):
    primary_provider: str | None = None
    failover_providers: str | None = None
    deepseek: ProviderConfigItem | None = None
    glm: ProviderConfigItem | None = None
    openai: ProviderConfigItem | None = None
    gemini: ProviderConfigItem | None = None


def _mask_key(key: str | None) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]


def _persist_env_var(key: str, val: str) -> None:
    os.environ[key] = val
    env_path = PROJECT_ROOT / ".env"
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key}=") or line.strip() == key:
            new_lines.append(f"{key}={val}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={val}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


app = FastAPI(
    title="Doctor Agent Medical Multi-Agent RAG API",
    version="0.2.0",
    description="LangGraph medical consultation preparation demo with Qdrant and MCP network evidence.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def knowledge_path() -> Path:
    configured = os.getenv("MEDICAL_KNOWLEDGE_PATH", "data/level_a_medical_knowledge.json")
    path = PROJECT_ROOT / configured
    if not path.exists():
        path = PROJECT_ROOT / "data/mock_medical_knowledge.json"
    if not path.exists():
        path = PROJECT_ROOT / "program/data/mock_medical_knowledge.json"
    return path


def load_knowledge(path: Path | None = None) -> dict[str, Any]:
    selected = path or knowledge_path()
    return json.loads(selected.read_text(encoding="utf-8"))


@app.get("/health")
async def health() -> dict[str, Any]:
    try:
        vector = await run_in_threadpool(get_qdrant_store().status)
    except Exception as exc:  # noqa: BLE001
        vector = {"status": "error", "error": type(exc).__name__, "message": str(exc)}
    return {"status": "ok", "knowledge_path": str(knowledge_path()), "vector_store": vector}


@app.post("/consult")
async def consult(request: ConsultRequest) -> dict[str, Any]:
    case = request.model_dump()
    orchestrator = get_central_orchestrator()

    # Centralized Orchestrator Dispatch
    try:
        orch_res = await orchestrator.dispatch(case)
        return {
            "session_id": orch_res.get("session_id"),
            "user_id": orch_res.get("user_id"),
            "patient_id": orch_res.get("patient_id"),
            "trace_id": orch_res.get("trace_id"),
            "profile": orch_res.get("profile"),
            "answer": orch_res.get("answer"),
            "intents": orch_res.get("intents", []),
            "agent_envelopes": orch_res.get("agent_envelopes", {}),
            "safety_audit": orch_res.get("safety_audit", {}),
            "risk_assessment": {"risk_level": "emergency" if orch_res.get("intent_plan", {}).get("is_emergency") else "low"},
            "guided_questions": [],
            "selected_experts": orch_res.get("intents", []),
            "evidence": [],
            "tool_events": [],
            "trace": [
                f"CentralOrchestrator: trace_id={orch_res.get('trace_id')}",
                f"Intents: {','.join(orch_res.get('intents', []))}",
                f"Execution: {orch_res.get('execution_time_ms')}ms",
            ],
            "evaluation": {"output_safe": orch_res.get("safety_audit", {}).get("audit_verdict") == "approved"},
        }
    except Exception as exc:  # noqa: BLE001
        # Fallback to existing LangGraph pipeline if orchestrator throws unexpected failure
        try:
            result = await run_in_threadpool(run_payload, case, load_knowledge())
            return {
                "session_id": result.get("session_id"),
                "user_id": result.get("user_id"),
                "patient_id": result.get("patient_id"),
                "profile": result.get("profile"),
                "memory_context": result.get("memory_context"),
                "memory_audit": result.get("memory_audit"),
                "answer": result.get("final_answer"),
                "risk_assessment": result.get("risk_assessment"),
                "guided_questions": result.get("guided_questions", []),
                "selected_experts": result.get("selected_experts", []),
                "evidence": result.get("fused_evidence", []),
                "tool_events": result.get("tool_events", []),
                "vector_store": result.get("vector_store_status", {}),
                "llm_generation": result.get("llm_generation", {}),
                "follow_up_plan": result.get("follow_up_plan", {}),
                "evaluation": result.get("evaluation_summary", result.get("evaluation", {})),
                "trace": result.get("trace", []),
            }
        except Exception as inner_exc:
            raise HTTPException(status_code=500, detail=f"consultation workflow failed: {type(inner_exc).__name__}: {inner_exc}") from inner_exc


@app.post("/knowledge/reindex")
async def reindex(request: ReindexRequest) -> dict[str, Any]:
    path = PROJECT_ROOT / request.knowledge_path if request.knowledge_path else knowledge_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"knowledge file not found: {path}")
    return await run_in_threadpool(index_knowledge_file, path)


@app.get("/settings")
async def get_settings() -> dict[str, Any]:
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    glm_key = os.getenv("ZHIPUAI_API_KEY") or os.getenv("GLM_API_KEY") or ""
    openai_key = os.getenv("OPENAI_API_KEY", "")
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

    return {
        "primary_provider": os.getenv("MEDICAL_LLM_PROVIDER", "deepseek"),
        "failover_providers": os.getenv("MEDICAL_LLM_PROVIDERS", "deepseek,glm,openai"),
        "providers": {
            "deepseek": {
                "has_key": bool(deepseek_key),
                "masked_key": _mask_key(deepseek_key),
                "base_url": os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
                "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            },
            "glm": {
                "has_key": bool(glm_key),
                "masked_key": _mask_key(glm_key),
                "base_url": os.getenv("GLM_API_BASE", "https://open.bigmodel.cn/api/paas/v4"),
                "model": os.getenv("GLM_MODEL", "glm-4-flash"),
            },
            "openai": {
                "has_key": bool(openai_key),
                "masked_key": _mask_key(openai_key),
                "base_url": os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            },
            "gemini": {
                "has_key": bool(gemini_key),
                "masked_key": _mask_key(gemini_key),
                "base_url": os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta"),
                "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            },
        },
    }


@app.post("/settings")
async def update_settings(payload: SettingsUpdateRequest) -> dict[str, Any]:
    if payload.primary_provider:
        _persist_env_var("MEDICAL_LLM_PROVIDER", payload.primary_provider.strip().lower())
    if payload.failover_providers:
        _persist_env_var("MEDICAL_LLM_PROVIDERS", payload.failover_providers.strip())

    if payload.deepseek:
        if payload.deepseek.api_key and not payload.deepseek.api_key.startswith("****"):
            _persist_env_var("DEEPSEEK_API_KEY", payload.deepseek.api_key.strip())
        if payload.deepseek.base_url:
            _persist_env_var("DEEPSEEK_API_BASE", payload.deepseek.base_url.strip())
        if payload.deepseek.model:
            _persist_env_var("DEEPSEEK_MODEL", payload.deepseek.model.strip())

    if payload.glm:
        if payload.glm.api_key and not payload.glm.api_key.startswith("****"):
            _persist_env_var("ZHIPUAI_API_KEY", payload.glm.api_key.strip())
        if payload.glm.base_url:
            _persist_env_var("GLM_API_BASE", payload.glm.base_url.strip())
        if payload.glm.model:
            _persist_env_var("GLM_MODEL", payload.glm.model.strip())

    if payload.openai:
        if payload.openai.api_key and not payload.openai.api_key.startswith("****"):
            _persist_env_var("OPENAI_API_KEY", payload.openai.api_key.strip())
        if payload.openai.base_url:
            _persist_env_var("OPENAI_API_BASE", payload.openai.base_url.strip())
        if payload.openai.model:
            _persist_env_var("OPENAI_MODEL", payload.openai.model.strip())

    if payload.gemini:
        if payload.gemini.api_key and not payload.gemini.api_key.startswith("****"):
            _persist_env_var("GEMINI_API_KEY", payload.gemini.api_key.strip())
        if payload.gemini.base_url:
            _persist_env_var("GEMINI_API_BASE", payload.gemini.base_url.strip())
        if payload.gemini.model:
            _persist_env_var("GEMINI_MODEL", payload.gemini.model.strip())

    return await get_settings()


@app.get("/patients")
async def list_patients(user_id: str = "web-user") -> dict[str, Any]:
    store = MedicalMemoryStore.get_default_store()
    patients = await run_in_threadpool(store.list_patients, user_id)
    return {"user_id": user_id, "patients": patients}


@app.get("/memory")
async def get_memory(user_id: str = "web-user", patient_id: str = "default-patient") -> dict[str, Any]:
    store = MedicalMemoryStore.get_default_store()
    profile = await run_in_threadpool(store.get_or_create_profile, user_id, patient_id)
    episodes = await run_in_threadpool(store.get_episodes, user_id, patient_id, 10)
    audit = await run_in_threadpool(store.get_audit_logs, user_id, patient_id, 10)
    return {
        "user_id": user_id,
        "patient_id": patient_id,
        "isolation_fingerprint": f"{user_id}#{patient_id}",
        "profile": profile,
        "episodes": episodes,
        "audit_logs": audit,
    }


@app.post("/memory/purge")
async def purge_memory(req: MemoryPurgeRequest) -> dict[str, Any]:
    store = MedicalMemoryStore.get_default_store()
    if req.scope == "patient":
        result = await run_in_threadpool(store.purge_patient, req.user_id, req.patient_id)
    else:
        session_id = req.session_id or ""
        result = await run_in_threadpool(store.purge_session, req.user_id, req.patient_id, session_id)
    return {"status": "success", "purged": result}


@app.post("/patients/switch")
async def switch_patient(req: PatientSwitchRequest) -> dict[str, Any]:
    store = MedicalMemoryStore.get_default_store()
    switched = await run_in_threadpool(
        store.switch_entity,
        req.new_user_id,
        req.new_patient_id,
        req.old_user_id,
        req.old_patient_id,
    )
    profile = await run_in_threadpool(store.get_or_create_profile, req.new_user_id, req.new_patient_id)
    episodes = await run_in_threadpool(store.get_episodes, req.new_user_id, req.new_patient_id, 5)
    return {
        "status": "success",
        "switch_info": switched,
        "clean_profile": profile,
        "clean_episodes": episodes,
    }


@app.post("/memory/extract_and_sync")
async def extract_and_sync_memory(req: MemoryExtractAndSyncRequest) -> dict[str, Any]:
    store = MedicalMemoryStore.get_default_store()
    current_profile = await run_in_threadpool(store.get_or_create_profile, req.user_id, req.patient_id)

    # 1. Extract structured memory via LLM / Fallback
    extraction_res = await run_in_threadpool(
        extract_structured_memory_from_dialogue,
        req.messages,
        current_profile,
    )
    extracted = extraction_res["extracted"]

    # 2. Route extracted updates to MedicalMemoryStore
    routed = await run_in_threadpool(
        store.route_structured_memory_update,
        req.user_id,
        req.patient_id,
        req.session_id,
        extracted,
        req.trigger_source,
    )

    return {
        "status": "success",
        "extraction_meta": extraction_res["meta"],
        "extracted_payload": extracted,
        "routed_result": routed,
    }


@app.get("/memory/confirmations")
async def list_confirmations(user_id: str = "web-user", patient_id: str = "default-patient") -> dict[str, Any]:
    store = MedicalMemoryStore.get_default_store()
    items = await run_in_threadpool(store.list_pending_confirmations, user_id, patient_id)
    return {"user_id": user_id, "patient_id": patient_id, "confirmations": items}


@app.post("/memory/confirm_update")
async def confirm_memory_update(req: MemoryConfirmRequest) -> dict[str, Any]:
    store = MedicalMemoryStore.get_default_store()
    res = await run_in_threadpool(
        store.resolve_confirmation,
        req.confirmation_id,
        req.user_id,
        req.patient_id,
        req.decision,
    )
    return res


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("doctor_agent.api:app", host="127.0.0.1", port=8000, reload=False)
