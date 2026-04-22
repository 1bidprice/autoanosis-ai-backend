"""Autoanosis AI Backend v6.0.0
Professional Flask backend — Medical Context Orchestration Engine
Deployed on Render.com

Changelog:
v6.0.0 (2026-03-08) - MAJOR: Medical Context Orchestration Engine
  - Smart Context Router: intent detection → selective context loading
  - Medical Report Generator: /generate-report endpoint with chunked AI analysis
  - Pattern Detection: trend analysis across test results and check-ins
  - PDF generation via ReportLab (no external dependencies)
  - max_tokens 3000 → 4000 for full medical profiles
  - Structured response format guarantees completeness
v5.16.0 (2026-03-07) - Fix completeness: unconditional full data presentation rule, max_tokens 1500→3000
v5.15.4 (2026-03-07) - Fix 502 timeout (gunicorn 120s + max_tokens 1500) + BEST history dedup
v5.14.0 (2026-03-03) - Medical Memory integration: medications with time_slots
v5.12.0 (2026-03-02) - Fix: Show BEST history even with 1 entry
v5.11.0 (2026-03-02) - BEST History: rolling history (max 10)
v5.1.0  (2026-02-28) - WP PUSH architecture (final solution)
"""
import os
import hmac as _hmac
import hashlib
import json
import logging
import time
import uuid
import io
import re
import unicodedata
import requests
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from openai import OpenAI
from identity import verify_identity_token
from ocr_endpoint import ocr_bp
from exams_module.api.exams_flask import exams_bp
from exams_module.api.reprocess import reprocess_bp
from exams_module.api.audit_temp import audit_bp
from exams_module.api.role_sync import role_sync_bp
from exams_module.api.review_admin import review_admin_bp
from exams_module.db.database import init_db

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.register_blueprint(ocr_bp)
app.register_blueprint(exams_bp)
app.register_blueprint(reprocess_bp)
app.register_blueprint(audit_bp)
app.register_blueprint(role_sync_bp)
app.register_blueprint(review_admin_bp)

# Initialise exams tables on startup (safe no-op if already exist)
try:
    init_db()
    logger.info("[EXAMS] Database tables initialised")
except Exception as _exams_init_err:
    logger.warning(f"[EXAMS] init_db warning (non-fatal): {_exams_init_err}")

CORS(app, resources={
    r"/*": {
        "origins": ["https://autoanosis.com", "https://www.autoanosis.com"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "X-User-ID", "X-Autoa-Proxy-TS", "X-Autoa-Proxy-Nonce", "X-Autoa-Proxy-Sig", "X-Identity-Token", "X-Admin-Secret"],
        "supports_credentials": True
    }
})

# ---------------------------------------------------------------------------
# OpenAI (lazy)
# ---------------------------------------------------------------------------
openai_client = None

def get_openai_client():
    global openai_client
    if openai_client is None:
        openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return openai_client

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
AUTOA_PROXY_SECRET = os.environ.get("AUTOA_AI_PROXY_SECRET", "").strip()
PROXY_TS_TOLERANCE = 300  # 5 minutes

# ---------------------------------------------------------------------------
# Rate limiting (in-memory)
# ---------------------------------------------------------------------------
rate_limit_storage = defaultdict(list)
RATE_LIMIT_USER   = 20   # requests per window
RATE_LIMIT_WINDOW = 600  # 10 minutes

def check_rate_limit(identifier: str) -> bool:
    now = time.time()
    rate_limit_storage[identifier] = [
        t for t in rate_limit_storage[identifier] if now - t < RATE_LIMIT_WINDOW
    ]
    if len(rate_limit_storage[identifier]) >= RATE_LIMIT_USER:
        return False
    rate_limit_storage[identifier].append(now)
    return True

# ---------------------------------------------------------------------------
# Conversation memory (in-memory)
# ---------------------------------------------------------------------------
conversation_storage = {}
MAX_CONVERSATION_HISTORY = 10
CONVERSATION_TTL = 3600  # 1 hour

def cleanup_old_conversations():
    now = time.time()
    expired = [
        cid for cid, d in conversation_storage.items()
        if now - d.get("last_activity", 0) > CONVERSATION_TTL
    ]
    for cid in expired:
        del conversation_storage[cid]
        logger.info(f"Cleaned up expired conversation: {cid}")

def get_conversation_history(conversation_id: str) -> list:
    return conversation_storage.get(conversation_id, {}).get("messages", [])

def save_conversation_message(conversation_id: str, user_id: int, role: str, content: str):
    if conversation_id not in conversation_storage:
        conversation_storage[conversation_id] = {
            "messages": [], "user_id": user_id, "last_activity": time.time()
        }
    conv = conversation_storage[conversation_id]
    conv["messages"].append({"role": role, "content": content})
    conv["last_activity"] = time.time()
    if len(conv["messages"]) > MAX_CONVERSATION_HISTORY:
        conv["messages"] = conv["messages"][-MAX_CONVERSATION_HISTORY:]

# ---------------------------------------------------------------------------
# HMAC proxy signature verification
# ---------------------------------------------------------------------------
def verify_proxy_signature(ts_str: str, nonce: str, raw_body: bytes, sig: str) -> tuple[bool, str]:
    if not AUTOA_PROXY_SECRET:
        logger.warning("[PROXY] AUTOA_AI_PROXY_SECRET not set — skipping signature verification")
        return True, "no_secret"
    try:
        ts = int(ts_str)
    except (ValueError, TypeError):
        return False, "invalid_ts"
    now = int(time.time())
    if abs(now - ts) > PROXY_TS_TOLERANCE:
        return False, f"ts_expired (delta={abs(now - ts)}s)"
    canonical = f"{ts}.{nonce}.{raw_body.decode('utf-8', errors='replace')}"
    expected = _hmac.new(
        AUTOA_PROXY_SECRET.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    if not _hmac.compare_digest(expected, sig):
        return False, "sig_mismatch"
    return True, "ok"

# ===========================================================================
# SMART CONTEXT ROUTER — Intent Detection + Selective Context Loading
# ===========================================================================

# Intent categories with Greek keyword patterns
INTENT_PATTERNS = {
    "summary": [
        r"σύνοψη", r"συνοψη", r"περίληψη", r"περιληψη",
        r"γενική", r"γενικη", r"προφίλ", r"προφιλ",
        r"κατάστασή", r"κατασταση", r"υγεία", r"υγεια",
        r"πώς είμαι", r"πως ειμαι", r"τι έχω", r"τι εχω",
    ],
    "doctor_report": [
        r"όλο το ιστορικό", r"ολο το ιστορικο",
        r"πλήρη αναφορά", r"πληρη αναφορα",
        r"για τον γιατρό", r"για τον γιατρο",
        r"για τον ιατρό", r"για τον ιατρο",
        r"όλο το προφίλ", r"ολο το προφιλ",
        r"πλήρες ιστορικό", r"πληρες ιστορικο",
        r"πλήρες προφίλ", r"πληρες προφιλ",
        r"report", r"έκθεσ", r"εκθεσ",
    ],
    "pattern_detection": [
        r"μοτίβ", r"μοτιβ", r"pattern",
        r"trend", r"εξέλιξ", r"εξελιξ",
        r"τάση", r"ταση", r"τάσεις", r"τασεις",
        r"βελτιώνεται", r"βελτιωνεται",
        r"επιδεινώνεται", r"επιδεινωνεται",
    ],
    "education": [
        r"τι είναι", r"τι ειναι",
        r"εξήγησέ", r"εξηγησε", r"εξήγηση", r"εξηγηση",
        r"τι σημαίνει", r"τι σημαινει",
        r"πληροφορίες για", r"πληροφοριες για",
    ],
}

def _normalize_greek(text: str) -> str:
    """Normalize Greek text: lowercase + strip accents for robust matching."""
    lower = text.lower()
    # Strip combining diacritical marks (accents) via NFD decomposition
    return ''.join(
        c for c in unicodedata.normalize('NFD', lower)
        if unicodedata.category(c) != 'Mn'
    )


def detect_intent(message: str) -> str:
    """Detect primary intent deterministically. Returns a single intent string."""
    msg_norm = _normalize_greek(message)
    
    # Priority 1: doctor_report (explicit request for full history)
    for p in INTENT_PATTERNS["doctor_report"]:
        if re.search(_normalize_greek(p), msg_norm):
            return "doctor_report"
            
    # Priority 2: pattern_detection
    for p in INTENT_PATTERNS["pattern_detection"]:
        if re.search(_normalize_greek(p), msg_norm):
            return "pattern_detection"
            
    # Priority 3: education
    for p in INTENT_PATTERNS["education"]:
        if re.search(_normalize_greek(p), msg_norm):
            return "education"
            
    # Default to summary
    return "summary"


def build_selective_context(snap: dict, intent: str) -> str:
    """
    Build canonical context string based on deterministic intent.
    Context Priority Order: profile, medications, structured_exam_results, best_history, recent_checkins, health_notes, health_tracking, medication_schedule, trend_summary
    """
    if not snap or not isinstance(snap, dict):
        return ""

    # ── Change 1: Normalize aggregator v2.4.0 nested daily_checkins shape ──────
    # aggregator v2.4.0 sends: { daily_checkins: { recent: [...], averages: {...}, trend: str } }
    # build_selective_context expects flat: recent_checkins: [...]
    # Also extract weekly averages and trend for pattern_detection context.
    _daily = snap.get("daily_checkins")
    if isinstance(_daily, dict):
        # Promote nested recent list to flat recent_checkins if not already present
        if not snap.get("recent_checkins") and isinstance(_daily.get("recent"), list):
            snap = dict(snap)  # shallow copy — do not mutate caller's dict
            snap["recent_checkins"] = _daily["recent"]
        # Promote averages to weekly_stats for pattern_detection
        if not snap.get("weekly_stats") and isinstance(_daily.get("averages"), dict):
            snap = dict(snap) if "recent_checkins" not in snap else snap
            snap["weekly_stats"] = _daily["averages"]
        # Promote trend string to trend_summary if not already present
        if not snap.get("trend_summary") and isinstance(_daily.get("trend"), str):
            snap = dict(snap) if "weekly_stats" not in snap else snap
            snap["trend_summary"] = _daily["trend"]
    # ─────────────────────────────────────────────────────────────────────────

    # ── TEMPORAL ANCHOR: Current Athens date/time ──────────────────────────────
    # Injected first so the AI always has a concrete reference point for
    # relative date calculations ("πριν 4 μήνες", "σήμερα", "χθες").
    now_athens = datetime.now(ZoneInfo("Europe/Athens")).strftime("%d/%m/%Y %H:%M")
    parts = [f"ΤΡΕΧΟΥΣΑ ΗΜΕΡΟΜΗΝΙΑ/ΩΡΑ (Αθήνα): {now_athens}"]
    # ─────────────────────────────────────────────────────────────────────────

    # 1. Profile
    name = snap.get("user_name")
    cond = snap.get("autoimmune_type")
    diet = snap.get("diet_pref")
    health_info = snap.get("health_info")
    age = snap.get("age")
    gender = snap.get("gender")

    prof_parts = []
    if name: prof_parts.append(f"Χρήστης: {name}")
    if cond: prof_parts.append(f"Πάθηση: {cond}")
    if age is not None and str(age).strip():
        prof_parts.append(f"Ηλικία: {age}")
    if gender and str(gender).strip():
        prof_parts.append(f"Φύλο: {gender}")
    if diet: prof_parts.append(f"Διατροφή: {diet}")
    if health_info and isinstance(health_info, str) and health_info.strip():
        prof_parts.append(f"Ιστορικό/Υγεία: {health_info.strip()}")
    
    if prof_parts:
        parts.append("1. ΠΡΟΦΙΛ:\n" + " | ".join(prof_parts))

    # ── Change 2: Greek frequency label normalization ────────────────────────
    _FREQ_GR = {
        "once daily": "Μία φορά ημερησίως",
        "twice daily": "Δύο φορές ημερησίως",
        "three times daily": "Τρεις φορές ημερησίως",
        "four times daily": "Τέσσερις φορές ημερησίως",
        "every other day": "Κάθε δεύτερη μέρα",
        "weekly": "Εβδομαδιαία",
        "once weekly": "Μία φορά εβδομαδιαία",
        "twice weekly": "Δύο φορές εβδομαδιαία",
        "monthly": "Μηνιαία",
        "as needed": "Κατά ανάγκη",
        "daily": "Ημερησίως",
        "every 8 hours": "Κάθε 8 ώρες",
        "every 12 hours": "Κάθε 12 ώρες",
        "every 6 hours": "Κάθε 6 ώρες",
    }
    def _normalize_freq(f: str) -> str:
        return _FREQ_GR.get(f.strip().lower(), f) if f else f
    # ─────────────────────────────────────────────────────────────────────────

    # 2. Medications
    meds = snap.get("medications") or []
    if isinstance(meds, list) and meds:
        med_lines = []
        for m in meds:
            if isinstance(m, dict):
                n = m.get("medication_name") or m.get("name") or m.get("drug_name") or ""
                dose = m.get("dosage") or m.get("dose") or ""
                freq = _normalize_freq(m.get("frequency") or "")
                slots = m.get("time_slots") or []
                if n:
                    line = f"{n} {dose} {freq}".strip()
                    if isinstance(slots, list) and slots: line += f" (Ώρες: {', '.join(slots)})"
                    elif isinstance(slots, str) and slots: line += f" (Ώρες: {slots})"
                    med_lines.append(line)
        if med_lines:
            parts.append("2. ΦΑΡΜΑΚΑ:\n" + "\n".join(f"• {l}" for l in med_lines))

    # 3. Structured Exam Results
    # Header uses report_summary (report-level, performed_at-sorted) when available.
    # Individual results follow for detail. structured_exam_results is never removed.
    report_summary = snap.get("report_summary") or []
    structured_results = snap.get("structured_exam_results") or snap.get("test_results") or []

    exam_parts = []

    if isinstance(report_summary, list) and report_summary:
        # Build a temporal header: total reports + per-report summary line
        # The most recent report is first (sorted by performed_at DESC in the backend)
        total_reports = len(report_summary)
        total_results = sum(r.get("result_count", 0) for r in report_summary)
        total_abnormal = sum(r.get("abnormal_count", 0) for r in report_summary)
        exam_parts.append(
            f"ΣΥΝΟΛΟ: {total_reports} εξετάσεις (reports), {total_results} αποτελέσματα, "
            f"{total_abnormal} εκτός ορίων"
        )
        for rep in report_summary:
            p_at = rep.get("performed_at") or "άγνωστη ημερομηνία"
            e_type = rep.get("exam_type") or "Εξέταση"
            r_cnt = rep.get("result_count", 0)
            a_cnt = rep.get("abnormal_count", 0)
            abnormal_note = f", {a_cnt} εκτός ορίων" if a_cnt else ""
            exam_parts.append(f"• {e_type} — {p_at} ({r_cnt} αποτελέσματα{abnormal_note})")

    if isinstance(structured_results, list) and structured_results:
        if not exam_parts:
            # No report_summary available — fall back to flat list with header
            exam_parts.append(f"ΣΥΝΟΛΟ: {len(structured_results)} αποτελέσματα")
        exam_parts.append("ΑΝΑΛΥΤΙΚΑ ΑΠΟΤΕΛΕΣΜΑΤΑ:")
        for r in structured_results:
            if isinstance(r, dict):
                date = r.get("test_date") or r.get("created_at") or ""
                name_t = r.get("test_name") or r.get("display_name") or r.get("name") or ""
                val = r.get("result_value") or r.get("value_numeric") or r.get("value") or ""
                unit = r.get("unit") or ""
                status = r.get("status") or r.get("abnormal_flag") or ""
                line = f"{date}: {name_t} = {val} {unit}".strip().rstrip(":")
                if status and status not in ("unknown", ""):
                    _st_gr = {"normal": "φυσιολογικό", "high": "υψηλό", "low": "χαμηλό", "critical": "κρίσιμο", "abnormal": "εκτός ορίων"}.get(status.lower(), status)
                    line += f" [{_st_gr}]"
                exam_parts.append(line)

    if exam_parts:
        parts.append("3. ΕΞΕΤΑΣΕΙΣ:\n" + "\n".join(exam_parts))

    # 4. BEST History
    best_history = snap.get("best_history") or []
    best_current = snap.get("best_protocol")
    if best_current and isinstance(best_current, list): best_current = best_current[0]
    
    best_lines = []
    if best_current and isinstance(best_current, dict):
        vd = best_current.get("visit_date", "")
        vdr = best_current.get("visit_doctor", "")
        best_lines.append(f"Τελευταίο BEST ({vd} - {vdr}):")
        if best_current.get("b_labs"): best_lines.append(f"  Εξετάσεις: {best_current['b_labs']}")
        if best_current.get("s_symptoms"): best_lines.append(f"  Συμπτώματα: {best_current['s_symptoms']}")
        if best_current.get("t_questions"): best_lines.append(f"  Ερωτήσεις: {best_current['t_questions']}")
        
    if isinstance(best_history, list) and best_history:
        best_lines.append(f"Ιστορικό BEST: {len(best_history)} παλαιότερες καταχωρήσεις")
        for idx, h in enumerate(best_history[:3]): # Limit to 3 recent for context size
            e = h.get("payload") if isinstance(h, dict) and "payload" in h else h
            if isinstance(e, dict):
                vd = e.get("visit_date", "")
                vdr = e.get("visit_doctor", "")
                best_lines.append(f"  - {vd} ({vdr}): {e.get('b_notes', '')[:50]}...")
                
    if best_lines:
        parts.append("4. BEST HISTORY:\n" + "\n".join(best_lines))

    # 5. Recent Check-ins
    checkins = snap.get("recent_checkins") or []
    if isinstance(checkins, list) and checkins:
        ci_lines = []
        for ci in checkins[:7]:
            if isinstance(ci, dict):
                d = ci.get("checkin_date", "")
                pain = ci.get("pain_level", "")
                fatigue = ci.get("fatigue_level", "")
                energy = ci.get("energy_level", "")
                ci_lines.append(f"{d}: πόνος={pain}, κόπωση={fatigue}, ενέργεια={energy}")
            elif isinstance(ci, str) and ci.strip():
                ci_lines.append(ci.strip())
        if ci_lines:
            parts.append("5. RECENT CHECK-INS:\n" + "\n".join(ci_lines))

    # 6. Health Notes
    notes = snap.get("health_notes") or []
    if isinstance(notes, list) and notes:
        n_lines = []
        for n in notes[:3]:
            if isinstance(n, dict):
                d = n.get("created_at") or n.get("date") or ""
                t = n.get("note_title") or n.get("title") or ""
                n_lines.append(f"{d}: {t}")
        if n_lines:
            parts.append("6. HEALTH NOTES:\n" + "\n".join(n_lines))

    # 7. Health Tracking
    tracking = snap.get("health_tracking") or []
    if isinstance(tracking, list) and tracking:
        t_lines = []
        for t in tracking[:5]:
            if isinstance(t, dict):
                d = t.get("tracked_at") or ""
                m = t.get("metric_name") or ""
                v = t.get("metric_value") or ""
                t_lines.append(f"{d}: {m}={v}")
        if t_lines:
            parts.append("7. HEALTH TRACKING:\n" + "\n".join(t_lines))

    # 8. Medication Schedule
    sched = snap.get("medication_schedule") or []
    if isinstance(sched, list) and sched:
        s_lines = []
        for s in sched[:5]:
            if isinstance(s, dict):
                d = s.get("due_at") or ""
                m = s.get("medication_name") or ""
                st = s.get("status") or ""
                s_lines.append(f"{d}: {m} [{st}]")
        if s_lines:
            parts.append("8. MEDICATION SCHEDULE:\n" + "\n".join(s_lines))

    # 9. Trend Summary + Weekly Stats (pattern_detection enrichment)
    trend = snap.get("trend_summary")
    weekly = snap.get("weekly_stats")
    trend_parts = []
    if isinstance(trend, str) and trend:
        _trend_gr = {"improving": "βελτίωση", "worsening": "επιδείνωση", "stable": "σταθερή", "no_data": "χωρίς δεδομένα", "insufficient_data": "ανεπαρκή δεδομένα"}
        trend_parts.append(f"Τάση τελευταίας εβδομάδας: {_trend_gr.get(trend.lower(), trend)}")
    if isinstance(weekly, dict):
        avg_parts = []
        for k, label in (("pain", "Πόνος"), ("fatigue", "Κόπωση"), ("energy", "Ενέργεια"), ("mood", "Διάθεση")):
            if weekly.get(k) is not None:
                avg_parts.append(f"{label}: {weekly[k]}/10")
        if avg_parts:
            trend_parts.append("Μέσοι όροι εβδομάδας — " + ", ".join(avg_parts))
    if trend_parts:
        parts.append("9. ΤΑΣΕΙΣ ΕΒΔΟΜΑΔΑΣ:\n" + "\n".join(trend_parts))

    if not parts:
        return ""

    return (
        "\n\nCANONICAL MEDICAL CONTEXT:\n"
        + "\n\n".join(parts)
    )



def extract_context_from_wp_push(wp_context: dict, message: str = "") -> str:
    """
    Extract a formatted medical context string from the wp_context dict.
    Uses Smart Context Router to select only relevant data based on message intent.
    """
    if not wp_context or not isinstance(wp_context, dict):
        return ""

    # Shape A: pre-formatted context_text (legacy — use as-is)
    ct = wp_context.get("context_text")
    if isinstance(ct, str) and ct.strip():
        return ct.strip()

    # Shape A: nested data.context_text
    inner = wp_context.get("data") or {}
    if isinstance(inner, dict):
        ct = inner.get("context_text")
        if isinstance(ct, str) and ct.strip():
            return ct.strip()

    # Shape A: unified snapshot
    unified = wp_context.get("unified") or (inner.get("unified") if isinstance(inner, dict) else {}) or {}
    if isinstance(unified, dict) and unified:
        intent = detect_intent(message) if message else "summary"
        return build_selective_context(unified, intent)

    # Shape B: Autoa_AI_Context_Builder output
    if "user_profile" in wp_context or "health_data" in wp_context:
        return build_context_from_builder(wp_context)

    # Shape C: helpers.php autoa_rest_chat_proxy snapshot
    if any(k in wp_context for k in ("health_info", "autoimmune_type", "user_name", "recent_checkins", "medications", "best_protocol", "test_results")):
        intent = detect_intent(message) if message else "summary"
        logger.info(f"[CTX] Smart Context Router — intent={intent}")
        return build_selective_context(wp_context, intent)

    # Fallback: treat as aggregator snapshot
    intent = detect_intent(message) if message else "summary"
    return build_selective_context(wp_context, intent)


def build_context_from_builder(ctx: dict) -> str:
    """Build context string from Autoa_AI_Context_Builder::build_context() output."""
    if not ctx or not isinstance(ctx, dict):
        return ""
    parts = []
    profile = ctx.get("user_profile") or {}
    if isinstance(profile, dict):
        if profile.get("condition"):
            parts.append(f"Πάθηση: {profile['condition']}")
        if profile.get("name"):
            parts.append(f"Χρήστης: {profile['name']}")
    health = ctx.get("health_data") or {}
    if isinstance(health, dict):
        if health.get("health_information"):
            parts.append(f"Πληροφορίες Υγείας:\n{health['health_information']}")
        symptoms = health.get("symptoms")
        if symptoms:
            if isinstance(symptoms, list):
                parts.append(f"Συμπτώματα: {', '.join(str(s) for s in symptoms)}")
            elif isinstance(symptoms, str) and symptoms.strip():
                parts.append(f"Συμπτώματα: {symptoms}")
    checkins = ctx.get("recent_checkins") or {}
    if isinstance(checkins, dict) and checkins.get("averages"):
        avg = checkins["averages"]
        parts.append(
            f"Μέσοι όροι τελευταίων ημερών — "
            f"Πόνος: {avg.get('pain', '?')}/10, "
            f"Κόπωση: {avg.get('fatigue', '?')}/10, "
            f"Ενέργεια: {avg.get('energy', '?')}/10, "
            f"Διάθεση: {avg.get('mood', '?')}/10"
        )
    meds = ctx.get("medications") or {}
    if isinstance(meds, dict):
        current = meds.get("current_medications") or []
        if isinstance(current, list) and current:
            med_names = []
            for m in current:
                if isinstance(m, dict) and m.get("name"):
                    med_names.append(m["name"] + (f" ({m['dosage']})" if m.get("dosage") else ""))
                elif isinstance(m, str):
                    med_names.append(m)
            if med_names:
                parts.append(f"Φάρμακα: {', '.join(med_names)}")
    if not parts:
        return ""
    return (
        "\n\nΠΡΟΣΩΠΙΚΑ ΙΑΤΡΙΚΑ ΔΕΔΟΜΕΝΑ ΧΡΗΣΤΗ:\n"
        + "\n".join(parts)
        + "\n\nΧρησιμοποίησε αυτά τα στοιχεία για να δώσεις προσωποποιημένες απαντήσεις."
    )


# ===========================================================================
# SYSTEM PROMPTS
# ===========================================================================

SYSTEM_PROMPT_BASE = """
Είσαι ο Autoanosis Assistant — ο ψηφιακός βοηθός υγείας της πλατφόρμας Autoanosis.

ΧΑΡΑΚΤΗΡΑΣ:
Είσαι φιλικός, ζεστός και υποστηρικτικός. Μιλάς πάντα στα ελληνικά με φυσικό, ανθρώπινο τόνο.
Απαντάς σε κάθε ερώτηση του χρήστη — ιατρική, πρακτική ή απλώς φιλική.
Δεν αρνείσαι χαιρετισμούς, casual ερωτήσεις ή γενική συνομιλία. Αντίθετα, τη χρησιμοποιείς για να οικοδομήσεις εμπιστοσύνη.

ΟΡΙΑ & ΝΟΜΙΚΗ ΣΥΜΜΟΡΦΩΣΗ (GDPR / ΕΕ / Ελληνικό Δίκαιο):
- ΔΕΝ είσαι γιατρός. ΔΕΝ κάνεις ιατρική διάγνωση.
- ΔΕΝ συνταγογραφείς φάρμακα ούτε αλλάζεις δοσολογίες.
- Σε κάθε ερώτηση που αφορά συμπτώματα ή θεραπεία, παρέχεις ενημερωτικές πληροφορίες και παραπέμπεις στον θεράποντα ιατρό.
- Δεν αποκαλύπτεις, δεν μεταφέρεις και δεν αναλύεις προσωπικά δεδομένα εκτός του εξουσιοδοτημένου context του χρήστη.
- Τηρείς πλήρως τον GDPR (ΕΕ 2016/679) και τον Ν. 4624/2019.

ΑΠΑΓΟΡΕΥΕΤΑΙ:
- Να αρνείσαι να απαντήσεις σε φιλικό χαιρετισμό ή casual ερώτηση.
- Να λες "η λειτουργία μου είναι αυστηρά κλινική" — αυτό αποθαρρύνει τους χρήστες.
- Να δίνεις ιατρικές διαγνώσεις ή να επιβεβαιώνεις παθήσεις.
- Να χρησιμοποιείς εκφοβιστικό ή αλαζονικό τόνο.
"""

def build_system_prompt(snapshot: str, intent: str) -> str:
    """Build system prompt based on canonical context and deterministic intent."""
    if not snapshot:
        return SYSTEM_PROMPT_BASE

    templates = {
        "summary": """
Σταθερή δομή απάντησης (max 150 λέξεις):

ΤΙ ΒΛΕΠΩ:
[max 4 bullets — μόνο τα πιο κλινικά σημαντικά ευρήματα: abnormal τιμές, ενεργά φάρμακα, τελευταία BEST εγγραφή αν υπάρχει. ΜΗΝ κάνεις dump όλων των εξετάσεων — μόνο top abnormal/relevant.]

ΤΙ ΧΡΕΙΑΖΕΤΑΙ ΠΡΟΣΟΧΗ:
[max 2 bullets — μόνο αν υπάρχει κάτι εκτός ορίων ή αξιοσημείωτο]

ΤΙ ΔΕΝ ΜΠΟΡΩ ΝΑ ΣΥΜΠΕΡΑΝΩ:
[1 γραμμή — ρητός περιορισμός]
""",
        "pattern_detection": """
Σταθερή δομή απάντησης (max 120 λέξεις):

ΤΑΣΗ ΤΕΛΕΥΤΑΙΑΣ ΕΒΔΟΜΑΔΑΣ:
[max 3 bullets — τάσεις adherence, check-ins, abnormal results. Μιλάς ΜΟΝΟ για 7-day/recent trend. ΑΠΑΓΟΡΕΥΕΤΑΙ η λέξη "μακροχρόνιο μοτίβο".]

ΤΙ ΘΕΛΕΙ ΠΑΡΑΚΟΛΟΥΘΗΣΗ:
[max 2 bullets — αν υπάρχει επιδείνωση ή αξιοσημείωτη αλλαγή]

ΠΕΡΙΟΡΙΣΜΟΣ:
[1 γραμμή]
""",
        "doctor_report": """
ΑΥΤΟ ΕΙΝΑΙ DOCTOR REPORT MODE.
Ο χρήστης ζήτησε πλήρη αναφορά για τον γιατρό. 
ΑΠΑΓΟΡΕΥΕΤΑΙ να πεις "δεν μπορώ να δώσω όλο το ιστορικό". 
ΑΠΑΓΟΡΕΥΕΤΑΙ να δώσεις απλή σύνοψη.
Παρουσίασε το διαθέσιμο ιστορικό με καθαρή δομή, όχι raw dump.

Σταθερή δομή απάντησης:

1. ΒΑΣΙΚΟ ΠΡΟΦΙΛ
[Πάθηση, γενικά στοιχεία]

2. ΧΡΟΝΟΛΟΓΙΚΟ ΙΣΤΟΡΙΚΟ / BEST / CHECK-INS / NOTES
[Σύνοψη του ιστορικού από τα BEST, check-ins, notes]

3. ΦΑΡΜΑΚΑ
[Λίστα φαρμάκων με δοσολογίες και πρόγραμμα]

4. ΕΞΕΤΑΣΕΙΣ
[Λίστα εξετάσεων με ημερομηνίες και abnormal findings]

5. ΣΗΜΑΝΤΙΚΑ ΚΛΙΝΙΚΑ ΣΗΜΕΙΑ
[Τι ξεχωρίζει κλινικά από όλο το context]

6. ΘΕΜΑΤΑ ΠΟΥ ΧΡΕΙΑΖΟΝΤΑΙ ΙΑΤΡΙΚΗ ΑΞΙΟΛΟΓΗΣΗ
[Τι πρέπει να συζητηθεί με τον ιατρό]
""",
        "education": """
ΑΥΤΟ ΕΙΝΑΙ EDUCATION MODE.
Απάντησε γενικά και εκπαιδευτικά. Μην μπλέκεις με το ατομικό ιστορικό εκτός αν ζητηθεί.

Σταθερή δομή απάντησης:
- Τι είναι
- Συνήθη συμπτώματα / έννοιες
- Πότε χρειάζεται γιατρό
- Τι ΔΕΝ σημαίνει αυτόματα
"""
    }

    intent_template = templates.get(intent, templates["summary"])

    prompt = f"""Είσαι ο Autoanosis Assistant — ο ψηφιακός βοηθός υγείας της πλατφόρμας Autoanosis.

ΧΑΡΑΚΤΗΡΑΣ: Φιλικός, ζεστός, υποστηρικτικός. Μιλάς πάντα στα ελληνικά με φυσικό, ανθρώπινο τόνο. Απαντάς σε κάθε ερώτηση — ιατρική, πρακτική ή φιλική. Δεν αρνείσαι χαιρετισμούς ή casual συνομιλία.

ΝΟΜΙΚΗ ΣΥΜΜΟΡΦΩΣΗ (GDPR / ΕΕ / Ελληνικό Δίκαιο): ΔΕΝ κάνεις ιατρική διάγνωση. ΔΕΝ συνταγογραφείς. Σε ερωτήσεις για συμπτώματα/θεραπεία παρέχεις ενημερωτικές πληροφορίες και παραπέμπεις στον ιατρό. Τηρείς πλήρως GDPR (ΕΕ 2016/679) και Ν. 4624/2019.

{snapshot}

MODE ΛΕΙΤΟΥΡΓΙΑΣ: {intent.upper()}
{intent_template}

HARD RULES / BANNED BEHAVIOR (ΑΠΟΛΥΤΩΣ ΥΠΟΧΡΕΩΤΙΚΟ):
- ΑΠΑΓΟΡΕΥΕΤΑΙ να πεις "βλέπω μόνο όσα έχεις μοιραστεί".
- ΑΠΑΓΟΡΕΥΕΤΑΙ να πεις "δεν έχω πρόσβαση" ή "δεν μπορώ να δω προσωπικά δεδομένα" εφόσον υπάρχει context.
- ΑΠΑΓΟΡΕΥΕΤΑΙ να κάνεις raw dump όλων των εξετάσεων σε summary queries.
- ΑΠΑΓΟΡΕΥΕΤΑΙ να βαφτίζεις 7-day trend ως "μακροχρόνιο μοτίβο".
- ΑΠΑΓΟΡΕΥΕΤΑΙ να δηλώνεις "έχεις έξαρση" ή να βγάζεις clinical diagnosis από μόνος σου.
- ΑΠΑΓΟΡΕΥΕΤΑΙ να αρνείσαι full history όταν έχει ενεργοποιηθεί doctor_report.
- ΑΠΑΓΟΡΕΥΕΤΑΙ να μπερδεύεις general education με patient-specific summary.
- Αν κάποιο category λείπει από το context: παράλειψέ το σιωπηλά, ή γράψε "Δεν υπάρχει διαθέσιμο δεδομένο για την ενότητα Χ" στο doctor_report. Χωρίς filler φράσεις, χωρίς εξηγήσεις άμυνας.

TEMPORAL AWARENESS RULES (ΑΥΣΤΗΡΩΣ ΥΠΟΧΡΕΩΤΙΚΟ):
- Η τρέχουσα ημερομηνία/ώρα (Αθήνα) βρίσκεται ΠΑΝΤΑ στο context ως "ΤΡΕΧΟΥΣΑ ΗΜΕΡΟΜΗΝΙΑ/ΩΡΑ (Αθήνα)". Χρησιμοποίησέ την ως αποκλειστικό σημείο αναφοράς για κάθε χρονικό υπολογισμό.
- Χρησιμοποίησε ΠΑΝΤΑ σχετικές ημερομηνίες στις απαντήσεις σου: π.χ. "πριν 4 μήνες", "χθες", "πριν 3 εβδομάδες". Μην αναφέρεις μόνο την ακριβή ημερομηνία χωρίς σχετικό χρόνο.
- Για εξετάσεις: η «τελευταία εξέταση» είναι αυτή με το πιο πρόσφατο performed_at. Αναφέρσου σε αυτήν ως «τελευταία εξέταση» και υπολόγισε πόσο καιρό πριν έγινε.
- Για ερωτήσεις πλήθους («πόσες εξετάσεις έχω;»): απαντάς με τον αριθμό REPORTS (αναφορών), όχι των μεμονωμένων αποτελεσμάτων. Ο αριθμός βρίσκεται στο «ΣΥΝΟΛΟ: X εξετάσεις (reports)» του context.
- Για φάρμακα/δόσεις: αναφέρεσαι σε εκκρεμείς δόσεις με την ακριβή τους ώρα (π.χ. «η δόση των 20:00 φαίνεται εκκρεμής»). ΑΠΑΓΟΡΕΥΕΤΑΙ ο ψευδοϊατρικός τόνος — μην λες «έχεις παραλείψει επικίνδυνα τη θεραπεία σου» εκτός αν υπάρχει ρητός κανόνας στο context.
- Αν δεν υπάρχει ασφαλές date anchor (performed_at = null/άγνωστη): δήλωσέ το καθαρά («δεν γνωρίζω την ακριβή ημερομηνία αυτής της εξέτασης»). ΑΠΑΓΟΡΕΥΕΤΑΙ να εφευρίσκεις ή να εκτιμάς χρόνο από αέρα.

RELAPSE / FLARE SAFETY RULE:
Για queries τύπου "έχω έξαρση;", "φαίνεται έξαρση;", "είναι relapse;", "επιδεινώνομαι;":
Η απάντηση ΠΡΕΠΕΙ να είναι σταθερά: "Δεν μπορώ να επιβεβαιώσω έξαρση μόνο από αυτά τα δεδομένα. Αυτό απαιτεί νευρολογική αξιολόγηση και εξειδικευμένα κριτήρια."
Μετά επιτρέπεται ΜΟΝΟ σύντομη αναφορά στα δεδομένα που θέλουν προσοχή. Όχι συμπέρασμα ότι υπάρχει έξαρση.
"""

    return prompt


# ===========================================================================
# MEDICAL REPORT GENERATOR — Three-Pass System
# ===========================================================================

def generate_medical_report_pdf(snap: dict, user_id: int) -> bytes:
    """
    Generate a complete medical report PDF using three-pass system:
    Pass 1: Data aggregation (all categories)
    Pass 2: AI analysis per category
    Pass 3: PDF assembly
    Returns PDF bytes.
    """
    client = get_openai_client()
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    patient_name = snap.get("user_name") or f"Χρήστης #{user_id}"
    condition = snap.get("autoimmune_type") or "Αυτοάνοσο Νόσημα"

    # --- PASS 1: Data Aggregation ---
    sections = {}

    # Profile
    profile_lines = []
    if snap.get("user_name"):      profile_lines.append(f"Όνομα: {snap['user_name']}")
    if snap.get("autoimmune_type"): profile_lines.append(f"Διάγνωση: {snap['autoimmune_type']}")
    if snap.get("diet_pref"):       profile_lines.append(f"Διατροφή: {snap['diet_pref']}")
    if snap.get("health_info"):     profile_lines.append(f"Ιστορικό: {snap['health_info']}")
    sections["profile"] = "\n".join(profile_lines)

    # Medications
    meds = snap.get("medications") or []
    med_lines = []
    for m in meds:
        if isinstance(m, dict):
            n = m.get("medication_name") or m.get("name") or ""
            dose = m.get("dosage") or ""
            freq = m.get("frequency") or ""
            slots = m.get("time_slots") or []
            if n:
                line = f"{n} {dose} {freq}".strip()
                if isinstance(slots, list) and slots:
                    line += f" — {', '.join(slots)}"
                elif isinstance(slots, str) and slots:
                    line += f" — {slots}"
                med_lines.append(line)
    sections["medications"] = "\n".join(med_lines) if med_lines else "Δεν καταγράφηκαν φάρμακα."

    # Test Results — prefer structured exam data from Normalizer subsystem
    # structured_exam_results is populated by /exams/patients/<id>/snapshot
    structured_tests = snap.get("structured_exam_results") or []
    raw_tests = snap.get("test_results") or []
    tests = structured_tests if structured_tests else raw_tests
    test_lines = []
    for r in tests:
        if isinstance(r, dict):
            date = r.get("test_date") or ""
            name_t = r.get("test_name") or r.get("display_name") or r.get("test_name") or ""
            val = r.get("result_value") or r.get("value_numeric") or r.get("value") or ""
            unit = r.get("unit") or ""
            ref = r.get("reference_range") or ""
            status = r.get("status") or r.get("abnormal_flag") or ""
            line = f"{date}: {name_t} = {val} {unit}"
            if ref: line += f" (Φυσ.: {ref})"
            if status and status not in ("unknown", ""):
                _st_gr = {"normal": "φυσιολογικό", "high": "υψηλό", "low": "χαμηλό", "critical": "κρίσιμο", "abnormal": "εκτός ορίων"}.get(status.lower(), status)
                line += f" [{_st_gr}]"
            test_lines.append(line)
    data_source_note = " (Δομημένα/Επαληθευμένα)" if structured_tests else " (WP Snapshot)"
    sections["tests"] = "\n".join(test_lines) if test_lines else "Δεν καταγράφηκαν εξετάσεις."
    if test_lines:
        sections["tests"] = f"[{len(test_lines)} εγγραφές{data_source_note}]\n" + sections["tests"]

    # BEST Protocol
    best = snap.get("best_protocol") or {}
    if isinstance(best, list) and best:
        best = best[0]
    best_lines = []
    if isinstance(best, dict) and best:
        for key, label in [
            ("visit_date", "Ημερομηνία"), ("visit_doctor", "Ιατρός"),
            ("visit_goal", "Στόχος"), ("b_meds", "Φάρμακα"),
            ("b_labs", "Εξετάσεις"), ("e_stress", "Στρες"),
            ("e_infections", "Λοιμώξεις"), ("t_qol", "Στόχοι"),
            ("t_questions", "Ερωτήσεις"),
        ]:
            if best.get(key):
                best_lines.append(f"{label}: {best[key]}")
        for i in [1, 2, 3, 4, 5]:
            sn = best.get(f"s{i}_name", "").strip() if best.get(f"s{i}_name") else ""
            sv = best.get(f"s{i}_vas", "")
            if sn:
                best_lines.append(f"Σύμπτωμα {i}: {sn} VAS={sv}")
    sections["best"] = "\n".join(best_lines) if best_lines else "Δεν καταγράφηκε BEST Protocol."

    # Check-ins summary
    checkins = snap.get("recent_checkins") or []
    ci_lines = []
    for ci in checkins[:7]:
        if isinstance(ci, dict):
            d = ci.get("checkin_date", "")
            pain = ci.get("pain_level", "")
            fatigue = ci.get("fatigue_level", "")
            energy = ci.get("energy_level", "")
            mood = ci.get("mood_level", "")
            ci_lines.append(f"{d}: πόνος={pain}, κόπωση={fatigue}, ενέργεια={energy}, διάθεση={mood}")
        elif isinstance(ci, str) and ci.strip():
            ci_lines.append(ci.strip())
    sections["checkins"] = "\n".join(ci_lines) if ci_lines else "Δεν καταγράφηκαν check-ins."

    # --- PASS 2: AI Analysis per category ---
    analyses = {}

    def ai_analyze(section_name: str, data: str, instruction: str) -> str:
        if data.strip() in ["Δεν καταγράφηκαν φάρμακα.", "Δεν καταγράφηκαν εξετάσεις.", "Δεν καταγράφηκε BEST Protocol.", "Δεν καταγράφηκαν check-ins."]:
            return "Δεν υπάρχουν δεδομένα για ανάλυση."
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"Είσαι ιατρικός αναλυτής. Αναλύεις δεδομένα ασθενούς με αυτοάνοσο νόσημα ({condition}). Γράφεις στα ελληνικά. Είσαι σύντομος και κλινικά ακριβής. ΔΕΝ επινοείς δεδομένα."},
                    {"role": "user", "content": f"{instruction}\n\nΔεδομένα:\n{data}"}
                ],
                temperature=0.3,
                max_tokens=600,
                timeout=45
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"[REPORT] AI analysis error for {section_name}: {e}")
            return f"Δεν ήταν δυνατή η ανάλυση: {str(e)[:100]}"

    analyses["medications"] = ai_analyze(
        "medications",
        sections["medications"],
        "Σύνοψη τρέχουσας φαρμακευτικής αγωγής. Ανέφερε φάρμακα, δοσολογία, ώρες λήψης. Σημείωσε αν υπάρχουν πιθανές αλληλεπιδράσεις ή σημαντικές παρατηρήσεις."
    )

    analyses["tests"] = ai_analyze(
        "tests",
        sections["tests"],
        "Ανάλυση αποτελεσμάτων εξετάσεων. Ποιες τιμές είναι εκτός φυσιολογικών ορίων; Ποιες είναι φυσιολογικές; Τι κλινική σημασία έχουν για ασθενή με αυτοάνοσο;"
    )

    analyses["best"] = ai_analyze(
        "best",
        sections["best"],
        "Σύνοψη BEST Protocol. Ποιο είναι το κύριο θέμα της επίσκεψης; Ποια συμπτώματα αναφέρονται; Ποιες ερωτήσεις έχει ο ασθενής για τον γιατρό;"
    )

    analyses["checkins"] = ai_analyze(
        "checkins",
        sections["checkins"],
        "Ανάλυση καθημερινού ημερολογίου. Ποια είναι η τάση (βελτίωση/επιδείνωση/σταθερά); Ποιες μέρες ήταν χειρότερες; Ποιο σύμπτωμα κυριαρχεί;"
    )

    # Overall clinical summary
    all_data_summary = f"""
Ασθενής: {patient_name}
Διάγνωση: {condition}

ΦΑΡΜΑΚΑ:
{sections['medications']}

ΕΞΕΤΑΣΕΙΣ:
{sections['tests']}

BEST PROTOCOL:
{sections['best']}

CHECK-INS (τελευταίες 7 ημέρες):
{sections['checkins']}
"""
    try:
        overall_resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Είσαι ιατρικός αναλυτής. Γράφεις σύντομη κλινική σύνοψη για γιατρό. Στα ελληνικά. Κλινικά ακριβής. ΔΕΝ επινοείς."},
                {"role": "user", "content": f"Γράψε σύντομη κλινική σύνοψη (3-5 παράγραφοι) για τον γιατρό βάσει αυτών των δεδομένων:\n{all_data_summary}"}
            ],
            temperature=0.3,
            max_tokens=800,
            timeout=60
        )
        overall_analysis = overall_resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"[REPORT] Overall analysis error: {e}")
        overall_analysis = "Δεν ήταν δυνατή η δημιουργία συνολικής ανάλυσης."

    # --- PASS 3: PDF Assembly ---
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib.colors import HexColor, white, black
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm,
            title=f"Ιατρική Έκθεση — {patient_name}",
            author="Autoanosis Platform"
        )

        # Colors
        purple_dark = HexColor("#6B21A8")
        purple_mid = HexColor("#7C3AED")
        purple_light = HexColor("#EDE9FE")
        gray_light = HexColor("#F3F4F6")
        gray_mid = HexColor("#6B7280")

        styles = getSampleStyleSheet()

        # Custom styles
        title_style = ParagraphStyle(
            "Title", parent=styles["Normal"],
            fontSize=22, fontName="Helvetica-Bold",
            textColor=white, alignment=TA_CENTER,
            spaceAfter=6
        )
        subtitle_style = ParagraphStyle(
            "Subtitle", parent=styles["Normal"],
            fontSize=11, fontName="Helvetica",
            textColor=white, alignment=TA_CENTER,
            spaceAfter=4
        )
        section_header_style = ParagraphStyle(
            "SectionHeader", parent=styles["Normal"],
            fontSize=13, fontName="Helvetica-Bold",
            textColor=white, alignment=TA_LEFT,
            leftIndent=8, spaceAfter=4, spaceBefore=4
        )
        body_style = ParagraphStyle(
            "Body", parent=styles["Normal"],
            fontSize=10, fontName="Helvetica",
            textColor=black, alignment=TA_LEFT,
            spaceAfter=4, leading=14
        )
        analysis_style = ParagraphStyle(
            "Analysis", parent=styles["Normal"],
            fontSize=9.5, fontName="Helvetica",
            textColor=HexColor("#1F2937"), alignment=TA_LEFT,
            spaceAfter=4, leading=13,
            leftIndent=4
        )
        label_style = ParagraphStyle(
            "Label", parent=styles["Normal"],
            fontSize=9, fontName="Helvetica-Bold",
            textColor=gray_mid, alignment=TA_LEFT,
            spaceAfter=2
        )
        footer_style = ParagraphStyle(
            "Footer", parent=styles["Normal"],
            fontSize=8, fontName="Helvetica",
            textColor=gray_mid, alignment=TA_CENTER
        )

        story = []

        # --- COVER HEADER ---
        header_data = [[
            Paragraph(f"ΙΑΤΡΙΚΗ ΕΚΘΕΣΗ", title_style),
        ]]
        header_table = Table(header_data, colWidths=[17*cm])
        header_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), purple_dark),
            ("TOPPADDING", (0, 0), (-1, -1), 16),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ]))
        story.append(header_table)

        # Subtitle row
        subtitle_data = [[
            Paragraph(f"Autoanosis Platform  •  {now_str}", subtitle_style),
        ]]
        subtitle_table = Table(subtitle_data, colWidths=[17*cm])
        subtitle_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), purple_mid),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ]))
        story.append(subtitle_table)
        story.append(Spacer(1, 0.4*cm))

        # --- PATIENT INFO BOX ---
        info_rows = [
            [Paragraph("<b>Ασθενής:</b>", body_style), Paragraph(patient_name, body_style)],
            [Paragraph("<b>Διάγνωση:</b>", body_style), Paragraph(condition, body_style)],
            [Paragraph("<b>Ημερομηνία Έκθεσης:</b>", body_style), Paragraph(now_str, body_style)],
        ]
        if snap.get("diet_pref"):
            info_rows.append([Paragraph("<b>Διατροφή:</b>", body_style), Paragraph(snap["diet_pref"], body_style)])

        info_table = Table(info_rows, colWidths=[5*cm, 12*cm])
        info_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), purple_light),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#DDD6FE")),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 0.5*cm))

        # --- DISCLAIMER ---
        disclaimer = Paragraph(
            "<i>⚠ Αυτή η έκθεση δημιουργήθηκε αυτόματα από το Autoanosis AI. "
            "Δεν αντικαθιστά ιατρική γνωμάτευση. Παρακαλώ συζητήστε με τον γιατρό σας.</i>",
            ParagraphStyle("Disclaimer", parent=styles["Normal"], fontSize=8.5,
                          textColor=HexColor("#92400E"), alignment=TA_CENTER,
                          backColor=HexColor("#FEF3C7"), leftIndent=8, rightIndent=8,
                          spaceBefore=4, spaceAfter=4, leading=12)
        )
        story.append(disclaimer)
        story.append(Spacer(1, 0.4*cm))

        def add_section(title: str, raw_data: str, ai_analysis: str):
            """Add a formatted section with data and AI analysis."""
            # Section header
            header_row = [[Paragraph(f"  {title}", section_header_style)]]
            header_tbl = Table(header_row, colWidths=[17*cm])
            header_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), purple_mid),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(header_tbl)

            # Raw data
            story.append(Spacer(1, 0.15*cm))
            story.append(Paragraph("<b>Καταγεγραμμένα Δεδομένα:</b>", label_style))
            for line in raw_data.split("\n"):
                if line.strip():
                    story.append(Paragraph(f"• {line.strip()}", body_style))

            # AI Analysis
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph("<b>Κλινική Ανάλυση AI:</b>", label_style))
            # Split analysis into paragraphs
            for para in ai_analysis.split("\n"):
                if para.strip():
                    story.append(Paragraph(para.strip(), analysis_style))

            story.append(Spacer(1, 0.4*cm))

        # Add all sections
        add_section("ΦΑΡΜΑΚΕΥΤΙΚΗ ΑΓΩΓΗ", sections["medications"], analyses["medications"])
        add_section("ΑΠΟΤΕΛΕΣΜΑΤΑ ΕΞΕΤΑΣΕΩΝ", sections["tests"], analyses["tests"])
        add_section("BEST PROTOCOL (Προετοιμασία Ραντεβού)", sections["best"], analyses["best"])
        add_section("ΗΜΕΡΟΛΟΓΙΟ ΣΥΜΠΤΩΜΑΤΩΝ (Check-ins)", sections["checkins"], analyses["checkins"])

        # --- OVERALL CLINICAL SUMMARY ---
        summary_header = [[Paragraph("  ΣΥΝΟΛΙΚΗ ΚΛΙΝΙΚΗ ΣΥΝΟΨΗ", section_header_style)]]
        summary_header_tbl = Table(summary_header, colWidths=[17*cm])
        summary_header_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), purple_dark),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(summary_header_tbl)
        story.append(Spacer(1, 0.2*cm))
        for para in overall_analysis.split("\n"):
            if para.strip():
                story.append(Paragraph(para.strip(), analysis_style))
        story.append(Spacer(1, 0.5*cm))

        # --- FOOTER ---
        story.append(HRFlowable(width="100%", thickness=0.5, color=purple_mid))
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph(
            f"Δημιουργήθηκε από Autoanosis AI Platform  •  {now_str}  •  autoanosis.com  •  "
            "Εμπιστευτικό ιατρικό έγγραφο — μόνο για χρήση από εξουσιοδοτημένους ιατρούς",
            footer_style
        ))

        doc.build(story)
        buffer.seek(0)
        return buffer.read()

    except ImportError:
        # Fallback: plain text report if reportlab not available
        logger.warning("[REPORT] ReportLab not available, generating text report")
        return _generate_text_report(patient_name, condition, now_str, sections, analyses, overall_analysis)


def _generate_text_report(patient_name, condition, now_str, sections, analyses, overall_analysis) -> bytes:
    """Fallback text report if PDF generation fails."""
    lines = [
        "=" * 60,
        "ΙΑΤΡΙΚΗ ΕΚΘΕΣΗ — AUTOANOSIS PLATFORM",
        "=" * 60,
        f"Ασθενής: {patient_name}",
        f"Διάγνωση: {condition}",
        f"Ημερομηνία: {now_str}",
        "",
        "ΦΑΡΜΑΚΕΥΤΙΚΗ ΑΓΩΓΗ:",
        sections["medications"],
        "",
        "Ανάλυση:",
        analyses["medications"],
        "",
        "ΑΠΟΤΕΛΕΣΜΑΤΑ ΕΞΕΤΑΣΕΩΝ:",
        sections["tests"],
        "",
        "Ανάλυση:",
        analyses["tests"],
        "",
        "BEST PROTOCOL:",
        sections["best"],
        "",
        "Ανάλυση:",
        analyses["best"],
        "",
        "CHECK-INS:",
        sections["checkins"],
        "",
        "Ανάλυση:",
        analyses["checkins"],
        "",
        "=" * 60,
        "ΣΥΝΟΛΙΚΗ ΚΛΙΝΙΚΗ ΣΥΝΟΨΗ:",
        overall_analysis,
        "=" * 60,
        "Δημιουργήθηκε από Autoanosis AI Platform",
    ]
    return "\n".join(lines).encode("utf-8")


# ===========================================================================
# HEALTH CHECK
# ===========================================================================
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "autoanosis-ai-backend",
        "version": "6.0.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "architecture": "wp_push_smart_context",
        "features": [
            "smart_context_router",
            "intent_detection",
            "medical_report_generator",
            "pdf_generation",
            "pattern_detection",
            "wp_push_context",
            "proxy_hmac_verification",
            "session_memory",
            "rate_limiting",
            "exams_ingestion_normalizer",
            "structured_exam_reports",
            "exam_review_queue",
        ],
        "config": {
            "proxy_secret_configured": bool(AUTOA_PROXY_SECRET),
            "max_tokens": 4000,
        }
    }), 200


# ===========================================================================
# CHAT ENDPOINT (v6.0.0 — Smart Context Router)
# ===========================================================================
@app.route('/chat', methods=['POST'])
def chat():
    if len(conversation_storage) > 100:
        cleanup_old_conversations()

    # --- Verify proxy HMAC signature ---
    raw_body = request.get_data()
    ts_str = request.headers.get("X-Autoa-Proxy-TS", "")
    nonce = request.headers.get("X-Autoa-Proxy-Nonce", "")
    sig = request.headers.get("X-Autoa-Proxy-Sig", "")

    if ts_str or nonce or sig:
        ok, reason = verify_proxy_signature(ts_str, nonce, raw_body, sig)
        if not ok:
            logger.warning(f"[PROXY] Signature verification failed: {reason}")
            return jsonify({"error": f"Invalid proxy signature: {reason}"}), 403
        logger.info(f"[PROXY] Signature verified: {reason}")
    else:
        logger.warning("[PROXY] No signature headers — request not from WP proxy")

    data = request.json
    if not data:
        return jsonify({"error": "No JSON body"}), 400

    user_message = data.get("message")
    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    # --- Authenticate user ---
    user_id = None
    identity_token = data.get("identity_token")
    if identity_token:
        is_valid, payload, error = verify_identity_token(identity_token)
        if is_valid and payload:
            user_id = payload.get("uid")
            logger.info(f"[AUTH] User authenticated: {user_id}")
        else:
            logger.warning(f"[AUTH] Identity token failed: {error}")
            return jsonify({"error": "Invalid identity token"}), 401
    else:
        logger.warning("[AUTH] No identity token provided")
        return jsonify({"error": "Identity token required"}), 401

    # --- Rate limit ---
    if not check_rate_limit(f"user_{user_id}"):
        return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429

    # --- Conversation ID ---
    conversation_id = data.get("conversation_id")
    if not conversation_id:
        conversation_id = f"conv_{int(time.time())}_{uuid.uuid4().hex[:8]}"

    # --- Smart Context Router ---
    wp_context = data.get("wp_context") or data.get("medical_snapshot")
    snapshot = ""
    snapshot_source = "none"
    intent = "summary"

    if isinstance(wp_context, dict):
        ctx_key_used = "wp_context" if data.get("wp_context") else "medical_snapshot"
        logger.info(f"[CTX] received {ctx_key_used} keys={list(wp_context.keys())[:10]}")

        # Detect intent from user message
        intent = detect_intent(user_message)
        logger.info(f"[ROUTER] user={user_id} intent={intent} message_preview={user_message[:50]}")

        # Build selective context
        snapshot = extract_context_from_wp_push(wp_context, user_message)
        if snapshot:
            snapshot_source = "wp_push_smart"
            context_bytes = len(snapshot.encode("utf-8"))
            logger.info(
                f"[CONTEXT] user={user_id} source={snapshot_source} "
                f"intent={intent} context_bytes={context_bytes}"
            )
        else:
            logger.warning(f"[CONTEXT] context present but empty after extraction for user={user_id}")
    else:
        logger.warning(f"[CTX] no context received — type={type(wp_context).__name__} user={user_id}")

    # --- Build system prompt ---
    system_prompt = build_system_prompt(snapshot, intent)
    logger.info(f"[PROMPT] Medical context injected for user={user_id} source={snapshot_source} intent={intent}")

    # --- Build messages ---
    history = get_conversation_history(conversation_id)
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    # --- Call OpenAI ---
    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=4000,  # v6.0.0: 4000 for full medical profiles
            timeout=90
        )
        ai_response = response.choices[0].message.content

        save_conversation_message(conversation_id, user_id, "user", user_message)
        save_conversation_message(conversation_id, user_id, "assistant", ai_response)

        logger.info(f"[CHAT] user={user_id} conv={conversation_id} intent={intent}")

        return jsonify({
            "reply": ai_response,
            "conversation_id": conversation_id,
            "intent": intent  # For debugging
        })

    except Exception as e:
        logger.error(f"[OPENAI] error: {e}")
        return jsonify({"error": str(e)}), 500


# ===========================================================================
# MEDICAL REPORT ENDPOINT (v6.0.0 — NEW)
# ===========================================================================
@app.route('/generate-report', methods=['POST'])
def generate_report():
    """
    Generate a complete medical report PDF for doctor consultation.
    Three-pass system: aggregation -> AI analysis -> PDF assembly.
    """
    # --- Verify proxy HMAC signature ---
    raw_body = request.get_data()
    ts_str = request.headers.get("X-Autoa-Proxy-TS", "")
    nonce = request.headers.get("X-Autoa-Proxy-Nonce", "")
    sig = request.headers.get("X-Autoa-Proxy-Sig", "")

    if ts_str or nonce or sig:
        ok, reason = verify_proxy_signature(ts_str, nonce, raw_body, sig)
        if not ok:
            logger.warning(f"[PROXY] Report signature verification failed: {reason}")
            return jsonify({"error": f"Invalid proxy signature: {reason}"}), 403

    data = request.json
    if not data:
        return jsonify({"error": "No JSON body"}), 400

    # --- Authenticate user ---
    user_id = None
    identity_token = data.get("identity_token")
    if identity_token:
        is_valid, payload, error = verify_identity_token(identity_token)
        if is_valid and payload:
            user_id = payload.get("uid")
        else:
            return jsonify({"error": "Invalid identity token"}), 401
    else:
        return jsonify({"error": "Identity token required"}), 401

    # --- Rate limit (stricter for reports — expensive operation) ---
    if not check_rate_limit(f"report_{user_id}"):
        return jsonify({"error": "Rate limit exceeded for report generation."}), 429

    # --- Get medical snapshot ---
    wp_context = data.get("wp_context") or data.get("medical_snapshot")
    if not isinstance(wp_context, dict):
        return jsonify({"error": "Medical snapshot required for report generation"}), 400

    logger.info(f"[REPORT] Starting report generation for user={user_id}")

    try:
        # Generate PDF (three-pass system)
        pdf_bytes = generate_medical_report_pdf(wp_context, user_id)

        # Determine content type
        patient_name = wp_context.get("user_name") or f"user_{user_id}"
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', patient_name)
        date_str = datetime.now().strftime("%Y%m%d")
        filename = f"autoanosis_report_{safe_name}_{date_str}.pdf"

        logger.info(f"[REPORT] Report generated successfully for user={user_id} size={len(pdf_bytes)} bytes")

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        logger.error(f"[REPORT] Error generating report for user={user_id}: {e}")
        return jsonify({"error": f"Report generation failed: {str(e)[:200]}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
