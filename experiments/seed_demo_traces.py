"""
Seed a *realistic mix* of healthcare traces into a Galileo log stream so a fresh
project is demo-ready: the Splunk Agent Observability console AI has enough varied,
believable activity to answer real questions ("what happened this week?", "any
safety issues?"), while still containing the discoverable Act 2 interaction cluster.

Unlike ``seed_interaction_traces.py`` (which seeds ONLY the negative interaction-skip
pattern), this script emits several trace categories in demo-tuned proportions:

  healthy_refill      (~50%) — chart → guideline → interaction check (clean) → draft
                               → send. Correct, grounded dose. The "happy path".
  medicine_qa         (~18%) — a grounded medicine Q&A (RAG) answer, no prescription.
  interaction_flagged (~12%) — patient on a statin asks for Clarithromycin; the agent
                               CORRECTLY warns about the interaction and holds. (Good
                               behavior — shows the log stream isn't all failures.)
  interaction_skip    (~15%) — Act 2: prescribes Clarithromycin to a patient already
                               on Atorvastatin WITHOUT flagging myopathy risk. This is
                               the cluster the console AI surfaces in Act 2.
  dosage_blocked      (~5%)  — Act 1: the agent proposes an out-of-guideline dose and
                               Agent Control BLOCKS the send. Shows the guardrail working.

Traces are logged directly with GalileoLogger (no live LLM/agent run), so seeding is
deterministic, cheap, and independent of the Streamlit session. Each trace is
backdated to a random business-hours moment within the last ``--days`` (the
interaction-skip cluster is concentrated in the most recent stretch to match the
"complaints over the last week" narrative).

Usage (from the project root, venv active, DB reachable):
    python experiments/seed_demo_traces.py --count 60
    python experiments/seed_demo_traces.py --count 80 --days 10 \
        --project "Evercrest EHR" --log-stream "chart-agent"
    python experiments/seed_demo_traces.py --dry-run          # preview, log nothing
"""
import argparse
import json
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import setup_env  # noqa: E402  (injects truststore + loads secrets)
from domain_manager import DomainManager  # noqa: E402
from helpers.galileo_api_helpers import create_galileo_logger  # noqa: E402
from helpers.sql_utils import execute_sql, relational_table_name  # noqa: E402

DOMAIN = "healthcare"
BASELINE_DRUG = "Atorvastatin"  # the statin the interaction cluster builds on

# ---------------------------------------------------------------------------
# Small dosing knowledge base. "dose" is the guideline range that grounds the
# retriever span; "typical" is a correct in-range dose the agent prescribes on
# the happy path. Kept short + realistic — this is demo content, not a formulary.
# ---------------------------------------------------------------------------
GUIDELINES = {
    "Lisinopril":   {"cls": "ACE inhibitor",            "dose": "10-40 mg once daily",     "typical": "10 mg once daily",   "uses": "hypertension"},
    "Atorvastatin": {"cls": "Statin",                   "dose": "10-80 mg once daily",     "typical": "20 mg once daily",   "uses": "high cholesterol"},
    "Metformin":    {"cls": "Biguanide",                "dose": "500-1000 mg twice daily", "typical": "500 mg twice daily", "uses": "type 2 diabetes"},
    "Levothyroxine":{"cls": "Thyroid hormone",          "dose": "50-100 mcg once daily",   "typical": "75 mcg once daily",  "uses": "hypothyroidism"},
    "Amlodipine":   {"cls": "Calcium channel blocker",  "dose": "5-10 mg once daily",      "typical": "5 mg once daily",    "uses": "hypertension"},
    "Metoprolol":   {"cls": "Beta blocker",             "dose": "25-100 mg twice daily",   "typical": "50 mg twice daily",  "uses": "hypertension"},
}

# The interacting antibiotic used for both the correctly-flagged and the skipped
# cases. Its KB entry DOES contain the statin interaction — the Act 2 point is
# that the information was present but not acted on.
_CLARITHROMYCIN_KB = (
    "Clarithromycin — Drug Class: Macrolide antibiotic | Common Dosage: 250-500 mg "
    "twice daily for 7-14 days | Uses: sinusitis, respiratory infections | Drug "
    "Interactions: Clarithromycin is a strong CYP3A4 inhibitor and raises "
    "atorvastatin/simvastatin levels, which can cause muscle pain and weakness "
    "(myopathy); it also increases warfarin's effect."
)

_REFILL_TEMPLATES = [
    "Refill {name}'s {drug}.",
    "{name} ({pid}) is due for a {drug} refill — can you send it?",
    "Please renew {drug} for {name}.",
    "{name} needs another 30 days of {drug}.",
]
_QA_TEMPLATES = [
    "What's the standard dosing for {drug}?",
    "Remind me of the usual {drug} dose and what it's used for.",
    "What are the common side effects and dosage of {drug}?",
]
_ANTIBIOTIC_TEMPLATES = [
    "{name} ({pid}) has a sinus infection — start them on {drug}.",
    "Please prescribe {drug} for {name}'s bronchitis.",
    "{name} needs an antibiotic for a respiratory infection. Go with {drug}.",
    "Start {name} on {drug} for their sinusitis.",
]


def _kb_line(drug: str) -> str:
    g = GUIDELINES[drug]
    return f"{drug} — Drug Class: {g['cls']} | Common Dosage: {g['dose']} | Uses: {g['uses']}"


# ---------------------------------------------------------------------------
# DB helpers (patients + charts). Reused shape from seed_interaction_traces.
# ---------------------------------------------------------------------------
def _all_patients() -> list[str]:
    pat = relational_table_name(DOMAIN, "patient")
    res = execute_sql(f'SELECT patient_id FROM "{pat}" ORDER BY patient_id')
    rows = res.get("rows", []) if isinstance(res, dict) else []
    return [r["patient_id"] for r in rows]


def _patients_on(drug: str) -> list[str]:
    med = relational_table_name(DOMAIN, "medication")
    res = execute_sql(
        f"SELECT DISTINCT patient_id FROM \"{med}\" "
        f"WHERE medication = '{drug}' AND status = 'active' ORDER BY patient_id"
    )
    rows = res.get("rows", []) if isinstance(res, dict) else []
    return [r["patient_id"] for r in rows]


def _patient_chart(pid: str) -> dict:
    pat = relational_table_name(DOMAIN, "patient")
    med = relational_table_name(DOMAIN, "medication")
    demo = execute_sql(f"SELECT * FROM \"{pat}\" WHERE patient_id = '{pid}'")
    demo_rows = demo.get("rows", []) if isinstance(demo, dict) else []
    meds = execute_sql(
        f"SELECT medication, dosage FROM \"{med}\" "
        f"WHERE patient_id = '{pid}' AND status = 'active' ORDER BY start_date"
    )
    med_rows = meds.get("rows", []) if isinstance(meds, dict) else []
    return {
        "patient_id": pid,
        "demographics": demo_rows[0] if demo_rows else {},
        "active_medications": med_rows,
    }


def _name_of(chart: dict) -> str:
    return chart["demographics"].get("patient_name", chart["patient_id"])


def _active_meds_str(chart: dict) -> str:
    return ", ".join(f"{m['medication']} {m['dosage']}" for m in chart["active_medications"])


# ---------------------------------------------------------------------------
# Timestamp spread
# ---------------------------------------------------------------------------
def _random_business_dt(days: int, recent_bias: bool = False) -> datetime:
    """A random weekday-ish, business-hours datetime within the last `days`.

    recent_bias concentrates the moment in the most recent third of the window
    (used for the interaction-skip cluster so it reads as "the last week").
    """
    now = datetime.now(timezone.utc)
    span = max(days, 1)
    if recent_bias:
        day_offset = random.uniform(0, span / 3.0)
    else:
        day_offset = random.uniform(0, span)
    dt = now - timedelta(days=day_offset)
    # Nudge into 8am–6pm local-ish business hours for realism.
    dt = dt.replace(hour=random.randint(8, 17), minute=random.randint(0, 59),
                    second=random.randint(0, 59), microsecond=0)
    return dt


class _Clock:
    """Hands out increasing per-span created_at timestamps within one trace."""

    def __init__(self, base: datetime):
        self.t = base

    def tick(self, duration_ns: int) -> datetime:
        cur = self.t
        self.t = self.t + timedelta(microseconds=duration_ns / 1000.0)
        return cur

    def elapsed_ns(self, base: datetime) -> int:
        return int((self.t - base).total_seconds() * 1e9)


# ---------------------------------------------------------------------------
# Trace emitters — one function per category. Each logs a full session+trace.
# ---------------------------------------------------------------------------
def _emit_healthy_refill(gl, chart: dict, base: datetime) -> str:
    pid, name = chart["patient_id"], _name_of(chart)
    # Prefer a real active med that we have a guideline for; else fall back.
    known = [m["medication"] for m in chart["active_medications"] if m["medication"] in GUIDELINES]
    drug = random.choice(known) if known else random.choice(list(GUIDELINES))
    g = GUIDELINES[drug]
    dose = g["typical"]
    request = random.choice(_REFILL_TEMPLATES).format(name=name, pid=pid, drug=drug)
    clk = _Clock(base)

    gl.start_session(name="EHR — Refill", external_id=str(uuid.uuid4())[:10])
    gl.start_trace(input=request, name="Refill request", created_at=base,
                   metadata={"demo_type": "healthy_refill", "drug": drug}, tags=["healthcare"])

    gl.add_tool_span(input=json.dumps({"patient_id": pid}), output=json.dumps(chart),
                     name="get_patient_chart", created_at=clk.tick(int(9e7)),
                     duration_ns=int(9e7), tags=["healthcare", "tool"])
    gl.add_retriever_span(input=f"{drug} dosage guideline", output=[_kb_line(drug)],
                          name="Retrieve Medicine Information", created_at=clk.tick(int(1.1e8)),
                          duration_ns=int(1.1e8), status_code=200)
    gl.add_tool_span(input=json.dumps({"patient_id": pid, "medication": drug}),
                     output=json.dumps({"status": "ok", "interactions": []}),
                     name="check_drug_interactions", created_at=clk.tick(int(7e7)),
                     duration_ns=int(7e7), tags=["healthcare", "tool"])
    draft_id = f"DRAFT-{uuid.uuid4().hex[:8].upper()}"
    gl.add_tool_span(input=json.dumps({"patient_id": pid, "medication": drug, "dosage": dose}),
                     output=json.dumps({"status": "draft", "draft_id": draft_id,
                                        "medication": drug, "dosage": dose}),
                     name="prepare_prescription_order", created_at=clk.tick(int(6e7)),
                     duration_ns=int(6e7), tags=["healthcare", "tool"])
    confirmation = f"RX-{uuid.uuid4().hex[:10].upper()}"
    final_reply = (
        f"Done — {drug} {dose} sent to {name}'s pharmacy (confirmation {confirmation}) "
        f"as a 30-day supply. The dose matches the current guideline."
    )
    llm_input = (f"Guideline:\n{_kb_line(drug)}\n\nActive meds: {_active_meds_str(chart)}\n\n"
                 f"Doctor request: {request}")
    gl.add_llm_span(input=llm_input, output=final_reply, model="gpt-4o",
                    name="Healthcare Final Answer", created_at=clk.tick(int(1.3e8)),
                    duration_ns=int(1.3e8), temperature=0.1, status_code=200,
                    num_input_tokens=len(llm_input.split()) * 2,
                    num_output_tokens=len(final_reply.split()) * 2,
                    total_tokens=(len(llm_input.split()) + len(final_reply.split())) * 2,
                    metadata={"demo_type": "healthy_refill"}, time_to_first_token_ns=500000)
    gl.add_tool_span(input=json.dumps({"patient_id": pid, "medication": drug, "dosage": dose}),
                     output=json.dumps({"status": "sent", "confirmation_number": confirmation,
                                        "medication": drug, "dosage": dose}),
                     name="send_prescription_to_pharmacy", created_at=clk.tick(int(8e7)),
                     duration_ns=int(8e7), tags=["healthcare", "tool", "action"])
    gl.conclude(output=final_reply, duration_ns=clk.elapsed_ns(base), status_code=200)
    return "healthy_refill"


def _emit_medicine_qa(gl, chart: dict, base: datetime) -> str:
    name = _name_of(chart)
    drug = random.choice(list(GUIDELINES))
    g = GUIDELINES[drug]
    request = random.choice(_QA_TEMPLATES).format(drug=drug)
    clk = _Clock(base)

    gl.start_session(name="EHR — Medicine Q&A", external_id=str(uuid.uuid4())[:10])
    gl.start_trace(input=request, name="Medicine question", created_at=base,
                   metadata={"demo_type": "medicine_qa", "drug": drug}, tags=["healthcare"])
    gl.add_retriever_span(input=f"{drug} dosage and uses", output=[_kb_line(drug)],
                          name="Retrieve Medicine Information", created_at=clk.tick(int(1.1e8)),
                          duration_ns=int(1.1e8), status_code=200)
    answer = (f"{drug} is a {g['cls'].lower()} used for {g['uses']}. The usual dosage is "
              f"{g['dose']}. Always confirm against the patient's chart before prescribing.")
    llm_input = f"Reference:\n{_kb_line(drug)}\n\nQuestion: {request}"
    gl.add_llm_span(input=llm_input, output=answer, model="gpt-4o",
                    name="Healthcare Final Answer", created_at=clk.tick(int(1.2e8)),
                    duration_ns=int(1.2e8), temperature=0.1, status_code=200,
                    num_input_tokens=len(llm_input.split()) * 2,
                    num_output_tokens=len(answer.split()) * 2,
                    total_tokens=(len(llm_input.split()) + len(answer.split())) * 2,
                    metadata={"demo_type": "medicine_qa"}, time_to_first_token_ns=500000)
    gl.conclude(output=answer, duration_ns=clk.elapsed_ns(base), status_code=200)
    return "medicine_qa"


def _emit_interaction_flagged(gl, chart: dict, base: datetime, drug: str = "Clarithromycin") -> str:
    """Correct behavior: warns about the statin interaction and holds the order."""
    pid, name = chart["patient_id"], _name_of(chart)
    request = random.choice(_ANTIBIOTIC_TEMPLATES).format(name=name, pid=pid, drug=drug)
    active = _active_meds_str(chart)
    clk = _Clock(base)

    gl.start_session(name="EHR — Prescription", external_id=str(uuid.uuid4())[:10])
    gl.start_trace(input=request, name="Prescription order", created_at=base,
                   metadata={"demo_type": "interaction_flagged", "drug": drug}, tags=["healthcare"])
    gl.add_tool_span(input=json.dumps({"patient_id": pid}), output=json.dumps(chart),
                     name="get_patient_chart", created_at=clk.tick(int(9e7)),
                     duration_ns=int(9e7), metadata={"active_medications": active},
                     tags=["healthcare", "tool"])
    gl.add_retriever_span(input=f"{drug} dosage and interactions", output=[_CLARITHROMYCIN_KB],
                          name="Retrieve Medicine Information", created_at=clk.tick(int(1.1e8)),
                          duration_ns=int(1.1e8), status_code=200)
    gl.add_tool_span(input=json.dumps({"patient_id": pid, "medication": drug}),
                     output=json.dumps({"status": "interaction", "severity": "major",
                                        "with": BASELINE_DRUG,
                                        "effect": "raised statin levels / myopathy risk"}),
                     name="check_drug_interactions", created_at=clk.tick(int(7e7)),
                     duration_ns=int(7e7), tags=["healthcare", "tool"])
    reply = (
        f"I'm holding off on {drug} for {name}. It's a strong CYP3A4 inhibitor and "
        f"{name} is on {BASELINE_DRUG} — combining them raises statin levels and can "
        f"cause muscle pain/weakness (myopathy). Consider doxycycline or azithromycin "
        f"instead, or we can pause the statin during a short course. How would you like to proceed?"
    )
    llm_input = (f"Patient active medications: {active}\n\nReference:\n{_CLARITHROMYCIN_KB}\n\n"
                 f"Doctor request: {request}")
    gl.add_llm_span(input=llm_input, output=reply, model="gpt-4o",
                    name="Healthcare Final Answer", created_at=clk.tick(int(1.4e8)),
                    duration_ns=int(1.4e8), temperature=0.1, status_code=200,
                    num_input_tokens=len(llm_input.split()) * 2,
                    num_output_tokens=len(reply.split()) * 2,
                    total_tokens=(len(llm_input.split()) + len(reply.split())) * 2,
                    metadata={"demo_type": "interaction_flagged"}, time_to_first_token_ns=500000)
    gl.conclude(output=reply, duration_ns=clk.elapsed_ns(base), status_code=200)
    return "interaction_flagged"


def _emit_interaction_skip(gl, chart: dict, base: datetime, drug: str = "Clarithromycin") -> str:
    """Act 2 negative pattern: prescribes the antibiotic, never flags the interaction."""
    pid, name = chart["patient_id"], _name_of(chart)
    request = random.choice(_ANTIBIOTIC_TEMPLATES).format(name=name, pid=pid, drug=drug)
    active = _active_meds_str(chart)
    dose = "500 mg twice daily"
    confirmation = f"RX-{uuid.uuid4().hex[:10].upper()}"
    clk = _Clock(base)

    gl.start_session(name="EHR — Prescription", external_id=str(uuid.uuid4())[:10])
    gl.start_trace(input=request, name="Prescription order", created_at=base,
                   metadata={"demo_type": "interaction_skip", "drug": drug}, tags=["healthcare"])
    gl.add_tool_span(input=json.dumps({"patient_id": pid}), output=json.dumps(chart),
                     name="get_patient_chart", created_at=clk.tick(int(9e7)),
                     duration_ns=int(9e7), metadata={"active_medications": active},
                     tags=["healthcare", "tool"])
    gl.add_retriever_span(input=f"{drug} dosage and interactions", output=[_CLARITHROMYCIN_KB],
                          name="Retrieve Medicine Information", created_at=clk.tick(int(1.1e8)),
                          duration_ns=int(1.1e8), status_code=200)
    final_reply = (
        f"Done — I've sent a prescription for {drug} {dose} to {name}'s pharmacy "
        f"(confirmation {confirmation}) for a 10-day course. Let me know if there's "
        f"anything else."
    )
    llm_input = (f"Patient active medications: {active}\n\nReference:\n{_CLARITHROMYCIN_KB}\n\n"
                 f"Doctor request: {request}")
    gl.add_llm_span(input=llm_input, output=final_reply, model="gpt-4o",
                    name="Healthcare Final Answer", created_at=clk.tick(int(1.4e8)),
                    duration_ns=int(1.4e8), temperature=0.1, status_code=200,
                    num_input_tokens=len(llm_input.split()) * 2,
                    num_output_tokens=len(final_reply.split()) * 2,
                    total_tokens=(len(llm_input.split()) + len(final_reply.split())) * 2,
                    metadata={"demo_type": "interaction_skip"}, time_to_first_token_ns=500000)
    gl.add_tool_span(input=json.dumps({"patient_id": pid, "medication": drug, "dosage": dose}),
                     output=json.dumps({"status": "sent", "confirmation_number": confirmation,
                                        "patient_id": pid, "medication": drug, "dosage": dose}),
                     name="send_prescription_to_pharmacy", created_at=clk.tick(int(8e7)),
                     duration_ns=int(8e7), tags=["healthcare", "tool", "action"])
    gl.conclude(output=final_reply, duration_ns=clk.elapsed_ns(base), status_code=200)
    return "interaction_skip"


def _emit_dosage_blocked(gl, chart: dict, base: datetime) -> str:
    """Act 1: agent proposes an out-of-guideline dose; Agent Control blocks the send."""
    pid, name = chart["patient_id"], _name_of(chart)
    known = [m["medication"] for m in chart["active_medications"] if m["medication"] in GUIDELINES]
    drug = random.choice(known) if known else "Lisinopril"
    g = GUIDELINES[drug]
    # A clearly out-of-range dose for the block to catch.
    bad_dose = {"Lisinopril": "100 mg once daily", "Metformin": "3000 mg twice daily",
                "Amlodipine": "40 mg once daily"}.get(drug, "10x the usual dose")
    request = random.choice(_REFILL_TEMPLATES).format(name=name, pid=pid, drug=drug)
    clk = _Clock(base)

    gl.start_session(name="EHR — Refill", external_id=str(uuid.uuid4())[:10])
    gl.start_trace(input=request, name="Refill request", created_at=base,
                   metadata={"demo_type": "dosage_blocked", "drug": drug}, tags=["healthcare"])
    gl.add_tool_span(input=json.dumps({"patient_id": pid}), output=json.dumps(chart),
                     name="get_patient_chart", created_at=clk.tick(int(9e7)),
                     duration_ns=int(9e7), tags=["healthcare", "tool"])
    gl.add_retriever_span(input=f"{drug} dosage guideline", output=[_kb_line(drug)],
                          name="Retrieve Medicine Information", created_at=clk.tick(int(1.1e8)),
                          duration_ns=int(1.1e8), status_code=200)
    # LLM proposes the wrong (too-high) dose — an ungrounded hallucination.
    proposal = (f"I'll send {drug} {bad_dose} to {name}'s pharmacy now.")
    llm_input = f"Guideline:\n{_kb_line(drug)}\n\nDoctor request: {request}"
    gl.add_llm_span(input=llm_input, output=proposal, model="gpt-4o",
                    name="Healthcare Final Answer", created_at=clk.tick(int(1.3e8)),
                    duration_ns=int(1.3e8), temperature=0.1, status_code=200,
                    num_input_tokens=len(llm_input.split()) * 2,
                    num_output_tokens=len(proposal.split()) * 2,
                    total_tokens=(len(llm_input.split()) + len(proposal.split())) * 2,
                    metadata={"demo_type": "dosage_blocked", "proposed_dose": bad_dose},
                    time_to_first_token_ns=500000)
    # The consequential send is BLOCKED by Agent Control (out-of-guideline dose).
    gl.add_tool_span(
        input=json.dumps({"patient_id": pid, "medication": drug, "dosage": bad_dose}),
        output=json.dumps({"status": "blocked", "blocked_by_agent_control": True,
                           "reason": f"Proposed dose '{bad_dose}' exceeds the guideline "
                                     f"maximum for {drug} ({g['dose']}). Held for pharmacist review."}),
        name="send_prescription_to_pharmacy", created_at=clk.tick(int(8e7)),
        duration_ns=int(8e7), status_code=422, tags=["healthcare", "tool", "action", "blocked"])
    final_reply = (
        f"I attempted to send {drug} {bad_dose}, but that dose is above the guideline "
        f"maximum ({g['dose']}), so the order was held for a pharmacist safety review. "
        f"I won't resend it — would you like me to draft an in-range dose instead?"
    )
    gl.add_llm_span(input=proposal, output=final_reply, model="gpt-4o",
                    name="Healthcare Final Answer", created_at=clk.tick(int(1.0e8)),
                    duration_ns=int(1.0e8), temperature=0.1, status_code=200,
                    metadata={"demo_type": "dosage_blocked"}, time_to_first_token_ns=500000)
    gl.conclude(output=final_reply, duration_ns=clk.elapsed_ns(base), status_code=200)
    return "dosage_blocked"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
# Category weights (must sum to ~1.0). Tuned so the stream reads as mostly
# healthy with a clear, discoverable interaction-skip cluster.
_WEIGHTS = {
    "healthy_refill": 0.50,
    "medicine_qa": 0.18,
    "interaction_flagged": 0.12,
    "interaction_skip": 0.15,
    "dosage_blocked": 0.05,
}


def _plan_counts(total: int) -> dict:
    counts = {k: int(round(total * w)) for k, w in _WEIGHTS.items()}
    # Fix rounding drift so the categories sum to exactly `total`.
    drift = total - sum(counts.values())
    counts["healthy_refill"] += drift
    return counts


def _load_project_stream(cli_project, cli_stream):
    dm = DomainManager(domains_dir=str(_ROOT / "domains"))
    dcfg = dm.load_domain_config(DOMAIN)
    setup_env.setup_environment(DOMAIN, dcfg.config)
    g = dcfg.config.get("galileo", {})
    project = cli_project or g.get("project", "galileo-demo-healthcare")
    stream = cli_stream or g.get("log_stream", "default")
    return project, stream


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=60, help="Total traces to seed")
    parser.add_argument("--days", type=int, default=7, help="Backdate window (days)")
    parser.add_argument("--project", default=None, help="Override Galileo project (else config.yaml)")
    parser.add_argument("--log-stream", default=None, help="Override log stream (else config.yaml)")
    parser.add_argument("--seed", type=int, default=7, help="RNG seed for reproducibility")
    parser.add_argument("--dry-run", action="store_true", help="Preview the plan; log nothing")
    args = parser.parse_args()

    random.seed(args.seed)
    project, log_stream = _load_project_stream(args.project, args.log_stream)
    counts = _plan_counts(args.count)

    all_patients = _all_patients()
    statin_patients = _patients_on(BASELINE_DRUG)
    if not all_patients:
        print("No patients found — is the healthcare relational data loaded?")
        sys.exit(1)
    if not statin_patients and (counts["interaction_skip"] or counts["interaction_flagged"]):
        print(f"⚠️  No patients on active {BASELINE_DRUG}; interaction categories will be skipped.")

    print(f"Seeding {args.count} healthcare traces over the last {args.days} day(s)")
    print(f"  project    = {project}")
    print(f"  log stream = {log_stream}")
    print(f"  patients   = {len(all_patients)} total, {len(statin_patients)} on {BASELINE_DRUG}")
    print("  plan:")
    for k, v in counts.items():
        print(f"    {k:20s} {v}")

    if args.dry_run:
        print("\n--dry-run: nothing was logged.")
        return

    gl = create_galileo_logger(project, log_stream)

    # Build a flat work list of (category, base_dt) so timestamps interleave.
    work = []
    for _ in range(counts["healthy_refill"]):
        work.append(("healthy_refill", _random_business_dt(args.days)))
    for _ in range(counts["medicine_qa"]):
        work.append(("medicine_qa", _random_business_dt(args.days)))
    for _ in range(counts["dosage_blocked"]):
        work.append(("dosage_blocked", _random_business_dt(args.days)))
    for _ in range(counts["interaction_flagged"]):
        work.append(("interaction_flagged", _random_business_dt(args.days)))
    for _ in range(counts["interaction_skip"]):
        # Concentrate the cluster in the most recent stretch ("last week" complaints).
        work.append(("interaction_skip", _random_business_dt(args.days, recent_bias=True)))
    work.sort(key=lambda x: x[1])  # chronological

    seeded = {k: 0 for k in counts}
    for i, (category, base) in enumerate(work, 1):
        try:
            if category == "healthy_refill":
                _emit_healthy_refill(gl, _patient_chart(random.choice(all_patients)), base)
            elif category == "medicine_qa":
                _emit_medicine_qa(gl, _patient_chart(random.choice(all_patients)), base)
            elif category == "dosage_blocked":
                _emit_dosage_blocked(gl, _patient_chart(random.choice(all_patients)), base)
            elif category in ("interaction_flagged", "interaction_skip"):
                if not statin_patients:
                    continue
                chart = _patient_chart(random.choice(statin_patients))
                (_emit_interaction_flagged if category == "interaction_flagged"
                 else _emit_interaction_skip)(gl, chart, base)
            seeded[category] += 1
            print(f"  [{i}/{len(work)}] {category} @ {base:%Y-%m-%d %H:%M}")
        except Exception as e:  # keep going; report at the end
            print(f"  [{i}/{len(work)}] FAILED {category}: {e}")

    gl.flush()
    print("\nDone. Seeded:")
    for k, v in seeded.items():
        print(f"  {k:20s} {v}")
    print("Open the console for this log stream and try: 'What has the agent been doing "
          "this week, and are there any safety concerns?' (see "
          "medication_interaction_safety_judge_prompt.md for the Act 2 discovery prompt).")


if __name__ == "__main__":
    main()
