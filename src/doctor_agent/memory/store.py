from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any
import uuid

from doctor_agent.common import PROJECT_ROOT


class MedicalMemoryStore:
    """Thread-safe SQLite persistent store for multi-user and multi-patient medical memory."""

    _instance: MedicalMemoryStore | None = None
    _lock = threading.Lock()

    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            env_db = os.getenv("DOCTOR_AGENT_MEMORY_DB", ".cache/medical_memory.sqlite")
            if env_db == ":memory:":
                self.db_path = ":memory:"
            else:
                self.db_path = str(PROJECT_ROOT / env_db)
        else:
            self.db_path = str(db_path)

        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._local = threading.local()
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        if self.db_path == ":memory:":
            if not hasattr(self, "_shared_memory_conn") or self._shared_memory_conn is None:
                self._shared_memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._shared_memory_conn.row_factory = sqlite3.Row
            return self._shared_memory_conn

        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        conn = self._get_connection()
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS patient_profiles (
                    user_id TEXT NOT NULL,
                    patient_id TEXT NOT NULL,
                    name TEXT DEFAULT '',
                    age TEXT DEFAULT '',
                    sex TEXT DEFAULT '',
                    allergies_json TEXT DEFAULT '[]',
                    chronic_conditions_json TEXT DEFAULT '[]',
                    long_term_medications_json TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, patient_id)
                );

                CREATE TABLE IF NOT EXISTS consultation_episodes (
                    episode_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    patient_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    red_flags_json TEXT DEFAULT '[]',
                    follow_up_plan_json TEXT DEFAULT '{}',
                    profile_delta_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS session_registry (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    patient_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_audit_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    patient_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    details TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pending_memory_confirmations (
                    confirmation_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    patient_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    field_type TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    proposed_action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_trace_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    patient_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration_ms REAL NOT NULL,
                    input_json TEXT DEFAULT '{}',
                    output_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cold_dialogue_vectors (
                    item_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    patient_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_episodes_tenant ON consultation_episodes(user_id, patient_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_tenant ON session_registry(user_id, patient_id);
                CREATE INDEX IF NOT EXISTS idx_audit_tenant ON memory_audit_logs(user_id, patient_id);
                CREATE INDEX IF NOT EXISTS idx_confirm_tenant ON pending_memory_confirmations(user_id, patient_id, status);
                CREATE INDEX IF NOT EXISTS idx_agent_traces ON agent_trace_logs(trace_id);
                CREATE INDEX IF NOT EXISTS idx_cold_vectors_tenant ON cold_dialogue_vectors(user_id, patient_id, session_id);
                """
            )

    @classmethod
    def get_default_store(cls) -> MedicalMemoryStore:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_default_store(cls) -> None:
        with cls._lock:
            cls._instance = None

    def log_agent_trace(
        self,
        trace_id: str,
        session_id: str,
        user_id: str,
        patient_id: str,
        agent_name: str,
        intent: str,
        status: str,
        duration_ms: float,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
    ) -> None:
        """Persists granular structured agent call trace to SQLite table and JSONL file."""
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        conn = self._get_connection()
        in_json = json.dumps(input_data or {}, ensure_ascii=False)
        out_json = json.dumps(output_data or {}, ensure_ascii=False)

        with conn:
            conn.execute(
                """
                INSERT INTO agent_trace_logs (
                    trace_id, session_id, user_id, patient_id,
                    agent_name, intent, status, duration_ms,
                    input_json, output_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    session_id,
                    user_id,
                    patient_id,
                    agent_name,
                    intent,
                    status,
                    duration_ms,
                    in_json,
                    out_json,
                    now,
                ),
            )

        # File append to JSONL for audit replay
        try:
            today_str = dt.datetime.now().strftime("%Y-%m-%d")
            log_dir = PROJECT_ROOT / ".cache" / "traces"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"trace_{today_str}.jsonl"
            record = {
                "trace_id": trace_id,
                "session_id": session_id,
                "user_id": user_id,
                "patient_id": patient_id,
                "agent_name": agent_name,
                "intent": intent,
                "status": status,
                "duration_ms": duration_ms,
                "timestamp": now,
                "input": input_data,
                "output": output_data,
            }
            with log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_agent_traces_by_id(self, trace_id: str) -> list[dict[str, Any]]:
        conn = self._get_connection()
        rows = conn.execute(
            """
            SELECT * FROM agent_trace_logs WHERE trace_id = ? ORDER BY log_id ASC
            """,
            (trace_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def log_audit(
        self,
        action: str,
        user_id: str,
        patient_id: str,
        session_id: str,
        status: str,
        details: str = "",
    ) -> None:
        conn = self._get_connection()
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with conn:
            conn.execute(
                """
                INSERT INTO memory_audit_logs (timestamp, action, user_id, patient_id, session_id, status, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (now, action, user_id, patient_id, session_id, status, details),
            )

    def get_or_create_profile(
        self,
        user_id: str,
        patient_id: str,
        default_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user_id = str(user_id).strip()
        patient_id = str(patient_id).strip()
        conn = self._get_connection()
        row = conn.execute(
            """
            SELECT * FROM patient_profiles WHERE user_id = ? AND patient_id = ?
            """,
            (user_id, patient_id),
        ).fetchone()

        now = dt.datetime.now(dt.timezone.utc).isoformat()
        if row:
            profile = {
                "user_id": row["user_id"],
                "patient_id": row["patient_id"],
                "name": row["name"],
                "age": row["age"],
                "sex": row["sex"],
                "allergies": json.loads(row["allergies_json"] or "[]"),
                "chronic_conditions": json.loads(row["chronic_conditions_json"] or "[]"),
                "long_term_medications": json.loads(row["long_term_medications_json"] or "[]"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            # If default_profile has incoming data, selectively augment non-empty fields
            if default_profile:
                changed = False
                if default_profile.get("age") and not profile.get("age"):
                    profile["age"] = str(default_profile["age"])
                    changed = True
                if default_profile.get("sex") and not profile.get("sex"):
                    profile["sex"] = str(default_profile["sex"])
                    changed = True
                if default_profile.get("allergies"):
                    existing = set(profile["allergies"])
                    for a in default_profile["allergies"]:
                        if a and a not in existing:
                            profile["allergies"].append(a)
                            changed = True
                if default_profile.get("chronic_conditions"):
                    existing_c = set(profile["chronic_conditions"])
                    for c in default_profile["chronic_conditions"]:
                        if c and c not in existing_c:
                            profile["chronic_conditions"].append(c)
                            changed = True
                if changed:
                    self.save_profile(user_id, patient_id, profile)
            return profile

        # Create new profile
        init_p = default_profile or {}
        allergies = list(init_p.get("allergies") or [])
        chronic = list(init_p.get("chronic_conditions") or [])
        meds = list(init_p.get("long_term_medications") or [])
        age = str(init_p.get("age", ""))
        sex = str(init_p.get("sex", ""))
        name = str(init_p.get("name", ""))

        with conn:
            conn.execute(
                """
                INSERT INTO patient_profiles (
                    user_id, patient_id, name, age, sex,
                    allergies_json, chronic_conditions_json, long_term_medications_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    patient_id,
                    name,
                    age,
                    sex,
                    json.dumps(allergies, ensure_ascii=False),
                    json.dumps(chronic, ensure_ascii=False),
                    json.dumps(meds, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        self.log_audit("profile_create", user_id, patient_id, "", "success", f"Created profile for {patient_id}")
        return {
            "user_id": user_id,
            "patient_id": patient_id,
            "name": name,
            "age": age,
            "sex": sex,
            "allergies": allergies,
            "chronic_conditions": chronic,
            "long_term_medications": meds,
            "created_at": now,
            "updated_at": now,
        }

    def save_profile(self, user_id: str, patient_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        user_id = str(user_id).strip()
        patient_id = str(patient_id).strip()
        conn = self._get_connection()
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        allergies = list(profile.get("allergies") or [])
        chronic = list(profile.get("chronic_conditions") or [])
        meds = list(profile.get("long_term_medications") or [])
        age = str(profile.get("age", ""))
        sex = str(profile.get("sex", ""))
        name = str(profile.get("name", ""))

        with conn:
            conn.execute(
                """
                INSERT INTO patient_profiles (
                    user_id, patient_id, name, age, sex,
                    allergies_json, chronic_conditions_json, long_term_medications_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, patient_id) DO UPDATE SET
                    name = excluded.name,
                    age = excluded.age,
                    sex = excluded.sex,
                    allergies_json = excluded.allergies_json,
                    chronic_conditions_json = excluded.chronic_conditions_json,
                    long_term_medications_json = excluded.long_term_medications_json,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    patient_id,
                    name,
                    age,
                    sex,
                    json.dumps(allergies, ensure_ascii=False),
                    json.dumps(chronic, ensure_ascii=False),
                    json.dumps(meds, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        self.log_audit("profile_update", user_id, patient_id, "", "success", f"Updated profile for {patient_id}")
        return {
            "user_id": user_id,
            "patient_id": patient_id,
            "name": name,
            "age": age,
            "sex": sex,
            "allergies": allergies,
            "chronic_conditions": chronic,
            "long_term_medications": meds,
            "updated_at": now,
        }

    def list_patients(self, user_id: str) -> list[dict[str, Any]]:
        user_id = str(user_id).strip()
        conn = self._get_connection()
        rows = conn.execute(
            """
            SELECT * FROM patient_profiles WHERE user_id = ? ORDER BY created_at ASC
            """,
            (user_id,),
        ).fetchall()
        patients = []
        for r in rows:
            patients.append(
                {
                    "user_id": r["user_id"],
                    "patient_id": r["patient_id"],
                    "name": r["name"],
                    "age": r["age"],
                    "sex": r["sex"],
                    "allergies": json.loads(r["allergies_json"] or "[]"),
                    "chronic_conditions": json.loads(r["chronic_conditions_json"] or "[]"),
                    "long_term_medications": json.loads(r["long_term_medications_json"] or "[]"),
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                }
            )
        return patients

    def bind_and_validate_session(
        self,
        session_id: str,
        user_id: str,
        patient_id: str,
    ) -> dict[str, Any]:
        """Ensures a session belongs strictly to (user_id, patient_id). Prevents session cross-contamination."""
        session_id = str(session_id).strip()
        user_id = str(user_id).strip()
        patient_id = str(patient_id).strip()
        conn = self._get_connection()
        now = dt.datetime.now(dt.timezone.utc).isoformat()

        row = conn.execute(
            "SELECT * FROM session_registry WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        if row:
            if row["user_id"] != user_id or row["patient_id"] != patient_id:
                # Session conflict: same session ID used across different tenant/patient entities!
                self.log_audit(
                    "session_conflict",
                    user_id,
                    patient_id,
                    session_id,
                    "blocked",
                    f"Session collision: bound to ({row['user_id']}, {row['patient_id']}) but accessed by ({user_id}, {patient_id})",
                )
                return {
                    "valid": False,
                    "reason": "session_tenant_mismatch",
                    "bound_to": {"user_id": row["user_id"], "patient_id": row["patient_id"]},
                }
            return {"valid": True, "action": "matched"}

        with conn:
            conn.execute(
                """
                INSERT INTO session_registry (session_id, user_id, patient_id, status, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                """,
                (session_id, user_id, patient_id, now, now),
            )
        self.log_audit("session_bind", user_id, patient_id, session_id, "success", "Bound new session")
        return {"valid": True, "action": "registered"}

    def record_episode(
        self,
        user_id: str,
        patient_id: str,
        session_id: str,
        summary: str,
        risk_level: str,
        red_flags: list[str] | None = None,
        follow_up: dict[str, Any] | None = None,
        profile_delta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user_id = str(user_id).strip()
        patient_id = str(patient_id).strip()
        session_id = str(session_id).strip()
        conn = self._get_connection()
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        episode_id = f"ep-{uuid.uuid4().hex[:12]}"

        with conn:
            conn.execute(
                """
                INSERT INTO consultation_episodes (
                    episode_id, user_id, patient_id, session_id,
                    summary, risk_level, red_flags_json, follow_up_plan_json,
                    profile_delta_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode_id,
                    user_id,
                    patient_id,
                    session_id,
                    summary,
                    risk_level,
                    json.dumps(red_flags or [], ensure_ascii=False),
                    json.dumps(follow_up or {}, ensure_ascii=False),
                    json.dumps(profile_delta or {}, ensure_ascii=False),
                    now,
                ),
            )
        self.log_audit("episode_record", user_id, patient_id, session_id, "success", f"Recorded episode {episode_id}")
        return {
            "episode_id": episode_id,
            "user_id": user_id,
            "patient_id": patient_id,
            "session_id": session_id,
            "summary": summary,
            "risk_level": risk_level,
            "created_at": now,
        }

    def get_episodes(
        self,
        user_id: str,
        patient_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Strictly isolated episode retrieval. Guaranteed 0% cross-tenant data."""
        user_id = str(user_id).strip()
        patient_id = str(patient_id).strip()
        conn = self._get_connection()
        rows = conn.execute(
            """
            SELECT * FROM consultation_episodes
            WHERE user_id = ? AND patient_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, patient_id, limit),
        ).fetchall()

        episodes = []
        for r in rows:
            episodes.append(
                {
                    "episode_id": r["episode_id"],
                    "session_id": r["session_id"],
                    "summary": r["summary"],
                    "risk_level": r["risk_level"],
                    "red_flags": json.loads(r["red_flags_json"] or "[]"),
                    "follow_up": json.loads(r["follow_up_plan_json"] or "{}"),
                    "profile_delta": json.loads(r["profile_delta_json"] or "{}"),
                    "created_at": r["created_at"],
                }
            )
        return episodes

    def purge_session(self, user_id: str, patient_id: str, session_id: str) -> dict[str, Any]:
        """Purges a specific session for a given patient."""
        user_id = str(user_id).strip()
        patient_id = str(patient_id).strip()
        session_id = str(session_id).strip()
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                UPDATE session_registry SET status = 'purged', updated_at = ?
                WHERE session_id = ? AND user_id = ? AND patient_id = ?
                """,
                (dt.datetime.now(dt.timezone.utc).isoformat(), session_id, user_id, patient_id),
            )
        self.log_audit("purge_session", user_id, patient_id, session_id, "success", "Purged session state")
        return {"status": "purged", "session_id": session_id}

    def purge_patient(self, user_id: str, patient_id: str) -> dict[str, Any]:
        """Completely purges all memory episodes and profile for a patient."""
        user_id = str(user_id).strip()
        patient_id = str(patient_id).strip()
        conn = self._get_connection()
        with conn:
            conn.execute("DELETE FROM consultation_episodes WHERE user_id = ? AND patient_id = ?", (user_id, patient_id))
            conn.execute("DELETE FROM session_registry WHERE user_id = ? AND patient_id = ?", (user_id, patient_id))
            conn.execute("DELETE FROM patient_profiles WHERE user_id = ? AND patient_id = ?", (user_id, patient_id))
            conn.execute("DELETE FROM cold_dialogue_vectors WHERE user_id = ? AND patient_id = ?", (user_id, patient_id))
        self.log_audit("purge_patient", user_id, patient_id, "", "success", "Full patient memory purged")
        return {"status": "purged", "user_id": user_id, "patient_id": patient_id}

    def switch_entity(
        self,
        new_user_id: str,
        new_patient_id: str,
        old_user_id: str | None = None,
        old_patient_id: str | None = None,
    ) -> dict[str, Any]:
        """Formal entity switch handler. Generates a fresh clean session and validates isolation."""
        new_user_id = str(new_user_id).strip()
        new_patient_id = str(new_patient_id).strip()
        fresh_session_id = f"sess-{uuid.uuid4().hex[:8]}"

        self.bind_and_validate_session(fresh_session_id, new_user_id, new_patient_id)
        self.log_audit(
            "switch_entity",
            new_user_id,
            new_patient_id,
            fresh_session_id,
            "success",
            f"Switched from ({old_user_id}, {old_patient_id}) to ({new_user_id}, {new_patient_id})",
        )
        return {
            "status": "switched",
            "active_user_id": new_user_id,
            "active_patient_id": new_patient_id,
            "new_session_id": fresh_session_id,
            "isolation_fingerprint": f"{new_user_id}#{new_patient_id}",
        }

    def get_audit_logs(
        self,
        user_id: str,
        patient_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conn = self._get_connection()
        if patient_id:
            rows = conn.execute(
                """
                SELECT * FROM memory_audit_logs
                WHERE user_id = ? AND patient_id = ?
                ORDER BY log_id DESC LIMIT ?
                """,
                (user_id, patient_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM memory_audit_logs
                WHERE user_id = ?
                ORDER BY log_id DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def route_structured_memory_update(
        self,
        user_id: str,
        patient_id: str,
        session_id: str,
        extracted: dict[str, Any],
        trigger_source: str = "manual_or_idle",
    ) -> dict[str, Any]:
        """Routes extracted structured medical memory to corresponding stores with fail-safe policies.

        Policies:
        1. Allergies & Clinical Contraindications: Append-only (Immediate Safety Anchor).
        2. Profile Patches: Augment missing age/sex.
        3. Chronic & Med Additions: Automatically append with high confidence.
        4. Chronic & Med Deletions: Flag as 'pending_confirmation' to prevent hazardous accidental removal.
        5. Episode Evolution: Append new episode with evolution trend and treatment effect.
        """
        user_id = str(user_id).strip()
        patient_id = str(patient_id).strip()
        session_id = str(session_id).strip()
        now = dt.datetime.now(dt.timezone.utc).isoformat()

        profile = self.get_or_create_profile(user_id, patient_id)
        applied_changes: dict[str, Any] = {
            "profile_updated": False,
            "allergies_added": [],
            "chronic_added": [],
            "medications_added": [],
            "staged_confirmations": [],
            "episode_recorded": None,
        }

        # 1. Profile Patch (Age / Sex / Name)
        patch = extracted.get("profile_patch") or {}
        profile_changed = False
        if patch.get("age") and not profile.get("age"):
            profile["age"] = str(patch["age"])
            profile_changed = True
        if patch.get("sex") and not profile.get("sex"):
            profile["sex"] = str(patch["sex"])
            profile_changed = True
        if patch.get("name") and not profile.get("name"):
            profile["name"] = str(patch["name"])
            profile_changed = True

        # 2. Clinical Contraindications (Allergies) - Fail-Safe Append Only
        contraindications = extracted.get("clinical_contraindications") or []
        existing_allergies = set(profile.get("allergies") or [])
        for item in contraindications:
            allergy_name = item.get("item") if isinstance(item, dict) else str(item)
            if allergy_name and allergy_name not in existing_allergies:
                profile["allergies"].append(allergy_name)
                existing_allergies.add(allergy_name)
                applied_changes["allergies_added"].append(allergy_name)
                profile_changed = True
                self.log_audit(
                    "allergy_auto_appended",
                    user_id,
                    patient_id,
                    session_id,
                    "applied",
                    f"Fail-safe auto added allergy: {allergy_name}",
                )

        # 3. Chronic Conditions & Medications
        chronic_meds = extracted.get("chronic_and_medications") or {}
        # 3.1 Chronic Additions
        existing_chronic = set(profile.get("chronic_conditions") or [])
        for c in chronic_meds.get("chronic_add") or []:
            if c and c not in existing_chronic:
                profile["chronic_conditions"].append(c)
                existing_chronic.add(c)
                applied_changes["chronic_added"].append(c)
                profile_changed = True

        # 3.2 Medication Additions
        existing_meds = set(profile.get("long_term_medications") or [])
        for m in chronic_meds.get("medications_add") or []:
            if m and m not in existing_meds:
                profile["long_term_medications"].append(m)
                existing_meds.add(m)
                applied_changes["medications_added"].append(m)
                profile_changed = True

        # 3.3 Deletions (Safety Gate: Stage as pending confirmation)
        conn = self._get_connection()
        for c_del in chronic_meds.get("chronic_remove") or []:
            if c_del in existing_chronic:
                cid = f"conf-{uuid.uuid4().hex[:10]}"
                with conn:
                    conn.execute(
                        """
                        INSERT INTO pending_memory_confirmations (
                            confirmation_id, user_id, patient_id, session_id,
                            field_type, item_name, proposed_action, reason, status, created_at
                        ) VALUES (?, ?, ?, ?, 'chronic_condition', ?, 'remove', '提及慢病痊愈或排除', 'pending', ?)
                        """,
                        (cid, user_id, patient_id, session_id, c_del, now),
                    )
                applied_changes["staged_confirmations"].append(
                    {"confirmation_id": cid, "field_type": "chronic_condition", "item": c_del, "action": "remove"}
                )

        for m_del in chronic_meds.get("medications_remove") or []:
            if m_del in existing_meds:
                cid = f"conf-{uuid.uuid4().hex[:10]}"
                with conn:
                    conn.execute(
                        """
                        INSERT INTO pending_memory_confirmations (
                            confirmation_id, user_id, patient_id, session_id,
                            field_type, item_name, proposed_action, reason, status, created_at
                        ) VALUES (?, ?, ?, ?, 'medication', ?, 'remove', '提及停用药物', 'pending', ?)
                        """,
                        (cid, user_id, patient_id, session_id, m_del, now),
                    )
                applied_changes["staged_confirmations"].append(
                    {"confirmation_id": cid, "field_type": "medication", "item": m_del, "action": "remove"}
                )

        if profile_changed:
            self.save_profile(user_id, patient_id, profile)
            applied_changes["profile_updated"] = True

        # 4. Episode Evolution Recording
        evolution = extracted.get("episode_evolution") or {}
        summary_text = evolution.get("summary")
        if summary_text:
            followup = extracted.get("pending_followup") or {}
            ep = self.record_episode(
                user_id=user_id,
                patient_id=patient_id,
                session_id=session_id,
                summary=summary_text,
                risk_level=evolution.get("trend", "stable"),
                red_flags=followup.get("watch_items", []),
                follow_up=followup,
                profile_delta={
                    "allergies_added": applied_changes["allergies_added"],
                    "chronic_added": applied_changes["chronic_added"],
                    "meds_added": applied_changes["medications_added"],
                },
            )
            applied_changes["episode_recorded"] = ep

        self.log_audit(
            f"memory_routed_{trigger_source}",
            user_id,
            patient_id,
            session_id,
            "success",
            f"Routed update: profile_updated={profile_changed}, allergies={len(applied_changes['allergies_added'])}, staged={len(applied_changes['staged_confirmations'])}",
        )

        return {
            "status": "success",
            "trigger_source": trigger_source,
            "user_id": user_id,
            "patient_id": patient_id,
            "session_id": session_id,
            "updated_profile": profile,
            "applied_changes": applied_changes,
        }

    def list_pending_confirmations(self, user_id: str, patient_id: str) -> list[dict[str, Any]]:
        conn = self._get_connection()
        rows = conn.execute(
            """
            SELECT * FROM pending_memory_confirmations
            WHERE user_id = ? AND patient_id = ? AND status = 'pending'
            ORDER BY created_at DESC
            """,
            (user_id, patient_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def resolve_confirmation(
        self,
        confirmation_id: str,
        user_id: str,
        patient_id: str,
        decision: str,  # 'approve' or 'reject'
    ) -> dict[str, Any]:
        conn = self._get_connection()
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        row = conn.execute(
            """
            SELECT * FROM pending_memory_confirmations
            WHERE confirmation_id = ? AND user_id = ? AND patient_id = ?
            """,
            (confirmation_id, user_id, patient_id),
        ).fetchone()

        if not row:
            return {"status": "error", "message": "Confirmation not found"}

        if row["status"] != "pending":
            return {"status": "already_resolved", "resolved_at": row["resolved_at"]}

        profile = self.get_or_create_profile(user_id, patient_id)
        if decision == "approve":
            field_type = row["field_type"]
            item_name = row["item_name"]
            if field_type == "chronic_condition":
                if item_name in profile["chronic_conditions"]:
                    profile["chronic_conditions"].remove(item_name)
                    self.save_profile(user_id, patient_id, profile)
            elif field_type == "medication":
                if item_name in profile["long_term_medications"]:
                    profile["long_term_medications"].remove(item_name)
                    self.save_profile(user_id, patient_id, profile)

        with conn:
            conn.execute(
                """
                UPDATE pending_memory_confirmations
                SET status = ?, resolved_at = ?
                WHERE confirmation_id = ?
                """,
                (decision, now, confirmation_id),
            )

        self.log_audit(
            f"confirmation_{decision}",
            user_id,
            patient_id,
            row["session_id"],
            "success",
            f"User {decision}ed removal of {row['field_type']} '{row['item_name']}'",
        )
        return {"status": "success", "decision": decision, "updated_profile": profile}

    def store_cold_dialogue_vectors(
        self,
        user_id: str,
        patient_id: str,
        session_id: str,
        turns: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> int:
        """Stores cold history turns with dense vector embeddings into cold_dialogue_vectors table."""
        if not turns or not embeddings:
            return 0
        user_id = str(user_id).strip()
        patient_id = str(patient_id).strip()
        session_id = str(session_id).strip()
        conn = self._get_connection()
        now = dt.datetime.now(dt.timezone.utc).isoformat()

        inserted = 0
        with conn:
            for i, (turn, emb) in enumerate(zip(turns, embeddings)):
                turn_idx = int(turn.get("turn_index", i))
                role = str(turn.get("role", "user"))
                content = str(turn.get("content", ""))
                identity = f"{user_id}|{patient_id}|{session_id}|{turn_idx}|{role}|{content}"
                item_id = f"cold-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"
                meta = {k: v for k, v in turn.items() if k not in ("role", "content")}
                meta.setdefault("embedding_model", turn.get("embedding_model", "unknown"))
                conn.execute(
                    """
                    INSERT OR REPLACE INTO cold_dialogue_vectors (
                        item_id, user_id, patient_id, session_id,
                        turn_index, role, content, embedding_json, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        user_id,
                        patient_id,
                        session_id,
                        turn_idx,
                        role,
                        content,
                        json.dumps(emb),
                        json.dumps(meta, ensure_ascii=False),
                        now,
                    ),
                )
                inserted += 1

        self.log_audit(
            "cold_vector_store",
            user_id,
            patient_id,
            session_id,
            "success",
            f"Stored {inserted} cold dialogue vectors",
        )
        return inserted

    def recall_cold_dialogue(
        self,
        user_id: str,
        patient_id: str,
        query_embedding: list[float],
        similarity_threshold: float = 0.70,
        top_k: int = 2,
    ) -> list[dict[str, Any]]:
        """Recalls the most relevant cold dialogue turns using cosine similarity under strict tenant isolation."""
        user_id = str(user_id).strip()
        patient_id = str(patient_id).strip()
        conn = self._get_connection()

        rows = conn.execute(
            """
            SELECT item_id, session_id, turn_index, role, content, embedding_json, metadata_json, created_at
            FROM cold_dialogue_vectors
            WHERE user_id = ? AND patient_id = ?
            """,
            (user_id, patient_id),
        ).fetchall()

        if not rows or not query_embedding:
            return []

        import math

        def cosine_similarity(v1: list[float], v2: list[float]) -> float:
            dot = sum(a * b for a, b in zip(v1, v2))
            norm1 = math.sqrt(sum(a * a for a in v1))
            norm2 = math.sqrt(sum(b * b for b in v2))
            if norm1 <= 0.0 or norm2 <= 0.0:
                return 0.0
            return dot / (norm1 * norm2)

        scored = []
        for r in rows:
            try:
                emb = json.loads(r["embedding_json"])
                sim = cosine_similarity(query_embedding, emb)
                if sim >= similarity_threshold:
                    scored.append(
                        {
                            "item_id": r["item_id"],
                            "session_id": r["session_id"],
                            "turn_index": r["turn_index"],
                            "role": r["role"],
                            "content": r["content"],
                            "similarity": round(sim, 4),
                            "metadata": json.loads(r["metadata_json"] or "{}"),
                            "created_at": r["created_at"],
                        }
                    )
            except Exception:
                continue

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:top_k]

    def cold_dialogue_count(self, user_id: str, patient_id: str) -> int:
        conn = self._get_connection()
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM cold_dialogue_vectors
            WHERE user_id = ? AND patient_id = ?
            """,
            (str(user_id).strip(), str(patient_id).strip()),
        ).fetchone()
        return int(row["count"]) if row else 0
