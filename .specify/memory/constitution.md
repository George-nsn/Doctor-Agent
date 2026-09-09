<!--
Sync Impact Report
- Version change: unversioned template -> 1.0.0
- Modified principles: none; the unfilled template has been replaced by the initial principles.
- Added sections: Medical Safety and Data Governance; Development Workflow and Quality Gates.
- Removed sections: none.
- Follow-up TODOs: none.
-->

# Agentic RAG Eval Constitution

## Core Principles

### I. Medical Safety Takes Precedence
The system MUST provide medical information assistance, not diagnosis or treatment.
It MUST not recommend independently starting, stopping, changing, or dosing medication.
Emergency red flags MUST take the urgent-care path before ordinary retrieval or answer
generation. When evidence is insufficient, conflicting, or unsafe, the system MUST state the
uncertainty and direct the user to an appropriate clinician or pharmacist. Safety requirements
are stricter than answer completeness or conversational convenience because unsafe medical
guidance can cause harm.

### II. Evidence-Backed and Traceable Responses
Every medical claim presented as guidance MUST be supported by retrieved, attributable evidence
or be explicitly identified as uncertain. The system MUST preserve enough provenance to trace
the final answer through the selected sources, evidence cleaning, conflict resolution, and
safety review steps. Conflicting evidence MUST be surfaced or resolved conservatively according
to documented source-trust, evidence-level, and freshness rules. This makes outputs auditable
and prevents fluent but unsupported answers from being treated as reliable.

### III. Defense in Depth for Agent and Tool Boundaries
Untrusted user input, retrieved content, tool results, and memory candidates MUST be treated as
data, never as instructions. Each external tool call MUST use an allowlist, validated parameters,
bounded timeout, and observable failure result. Tool failure or degradation MUST select a
documented safe fallback instead of silently fabricating results. Memory writes MUST require
validation against poisoning and must record an audit trail. These controls contain prompt
injection, tool misuse, retrieval injection, and persistent-memory abuse.

### IV. Privacy-Minimizing Patient Context
The project MUST collect, retain, and expose only the patient context needed for the current
consultation, follow-up, or explicitly approved profile. Logs, evaluation fixtures, reports, and
debug artifacts MUST avoid real identifiable patient information; examples and tests MUST use
synthetic or properly de-identified data. Persistent profile and episodic memory changes MUST be
confirmable and auditable. Privacy is necessary to make the system safe to evaluate, demonstrate,
and extend.

### V. Reproducible, Measurable Evaluation
Every behavior change affecting triage, retrieval, evidence handling, answer safety, memory, or
tool use MUST include focused automated coverage or a documented reason it cannot be automated.
Evaluation runs MUST record the input dataset or fixture version, configuration, model/provider
when applicable, commands, key metrics, and generated report locations. A smoke-test path MUST
remain runnable without API keys, Docker, or external services. Reproducible evaluation turns
safety and quality claims into evidence rather than anecdote.

## Medical Safety and Data Governance

- The system is an informational and care-preparation assistant; it MUST NOT represent itself as
  a doctor or substitute for in-person clinical judgement.
- Risk levels and escalation actions MUST be explicit state passed through the workflow. An
  emergency action MUST short-circuit normal expert-answer generation.
- Output safety review MUST check for diagnosis overclaims, unsafe medication advice, missing
  uncertainty, and missing citations before returning a non-emergency answer.
- Sources for medical claims MUST have a documented trust category. Untrusted web content may
  inform retrieval but MUST pass cleaning and verification before it contributes to an answer.
- Secrets, API keys, and credentials MUST remain outside source control. Configuration examples
  MUST use placeholders, and reports MUST not disclose credentials or sensitive request data.
- Integration with remote models, medical services, databases, or MCP tools MUST have a local
  deterministic fallback or clearly report the unavailable capability.

## Development Workflow and Quality Gates

- Feature work MUST begin with a Spec Kit specification whose requirements and success criteria
  explicitly cover relevant safety, privacy, provenance, fallback, and evaluation effects.
- Implementations MUST keep the workflow observable: record routing choices, tool outcomes,
  evidence identifiers, safety decisions, and evaluation metrics in structured artifacts
  appropriate to the execution mode.
- Changes to public API contracts, stored schemas, evaluation output formats, or safety policy
  MUST document compatibility impact and include migration or versioning guidance.
- Before acceptance, run the narrowest existing automated tests or smoke command that covers the
  changed behavior. Changes to cross-agent workflows, external tool adapters, and persistence
  require an end-to-end or integration-level check in addition to focused tests.
- Pull requests and implementation reviews MUST verify every applicable core principle. Added
  complexity requires a written justification tied to safety, traceability, or measurable
  evaluation value.

## Governance

This constitution supersedes conflicting project development guidance. Every specification, plan,
task list, implementation review, and release decision MUST verify compliance with the principles
above. Amendments require a written rationale, an impact assessment covering affected
specifications and runtime behavior, and a semantic-version increment: MAJOR for removed or
incompatible principles, MINOR for new principles or materially stronger obligations, and PATCH
for clarifications that preserve obligations. The ratification date remains the initial adoption
date; the last-amended date changes with every accepted amendment. Compliance reviews may reject
or require remediation for work that cannot demonstrate medical safety, evidence traceability,
privacy protection, or reproducible evaluation.

**Version**: 1.0.0 | **Ratified**: 2026-09-02 | **Last Amended**: 2026-09-02
