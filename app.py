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
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from openai import OpenAI
from identity import verify_identity_token
from ocr_endpoint import ocr_bp
from exams_module.api.exams_flask import exams_bp
from exams_module.api.reprocess import reprocess_bp
from exams_module.api.audit_temp import audit_bp
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
    "medications": [
        r"φάρμακ", r"φαρμακ", r"χάπι", r"χαπι", r"δόσ", r"δοσ",
        r"παίρνω", r"παιρνω", r"θεραπεί", r"θεραπει", r"αγωγ",
        r"tranxene", r"serolux", r"trebon", r"probiotic",
    ],
    "test_results": [
        r"εξέτασ", r"εξετασ", r"αποτέλεσμ", r"αποτελεσμ",
        r"αίμα", r"αιμα", r"εργαστήρ", r"εργαστηρ",
        r"φερριτίν", r"φερριτιν", r"ferritin",
        r"βιταμίν", r"βιταμιν", r"vitamin",
        r"b12", r"tkε", r"tke", r"c3", r"c4",
        r"τιμ", r"αποτέλεσμ", r"αποτελεσμ",
        r"εξετάσεις", r"εξετασεις",
        r"εξετ", r"εξέτ",
    ],
    "best_protocol": [
        r"best", r"b\.e\.s\.t", r"ραντεβού", r"ραντεβου",
        r"γιατρ", r"ιατρ", r"νεφρολόγ", r"νεφρολογ",
        r"νευρολόγ", r"νευρολογ", r"ρευματολόγ", r"ρευματολογ",
        r"επίσκεψ", r"επισκεψ", r"στόχ", r"στοχ",
        r"προετοιμασί", r"προετοιμασι",
    ],
    "checkins": [
        r"check.in", r"ημερολόγ", r"ημερολογ",
        r"πόνος", r"πονος", r"κόπωσ", r"κοπωσ",
        r"ενέργεια", r"ενεργεια", r"διάθεσ", r"διαθεσ",
        r"σήμερα", r"σημερα", r"χθες", r"εβδομάδ", r"εβδομαδ",
        r"τελευταί", r"τελευται",
    ],
    "symptoms": [
        r"σύμπτωμ", r"συμπτωμ", r"πόνος", r"πονος",
        r"κόπωσ", r"κοπωσ", r"φλεγμον", r"κρίσ", r"κρισ",
        r"επιδείνωσ", r"επιδεινωσ", r"βελτίωσ", r"βελτιωσ",
    ],
    "full_profile": [
        r"γενική", r"γενικη", r"γενικά", r"γενικα",  # γενικ not γενικ (too broad)
        r"όλα τα", r"όλα μου", r"ολα τα", r"ολα μου",  # όλα not όλ (too broad)
        r"προφίλ", r"προφιλ",
        r"κατάστασή μου", r"κατασταση μου",
        r"υγεία μου", r"υγεια μου",
        r"συνολική", r"συνολικα",
        r"πλήρης", r"πληρης", r"πλήρες", r"πληρες",
        r"επισκόπηση", r"επισκοπηση",
        r"πώς είμαι", r"πως ειμαι", r"τι έχω", r"τι εχω",
        r"τι δεδομένα", r"τι δεδομενα",
    ],
    "report": [
        r"έκθεσ", r"εκθεσ", r"αναφορ", r"report",
        r"γιατρ.*έγγραφ", r"έγγραφ.*γιατρ",
        r"εκτύπωσ", r"εκτυπωσ", r"pdf",
        r"ιατρικ.*έγγραφ", r"ιατρικ.*αναφορ",
        r"δώσε.*γιατρ", r"δωσε.*γιατρ",
    ],
    "pattern_detection": [
        r"μοτίβ", r"μοτιβ", r"pattern",
        r"trend", r"εξέλιξ", r"εξελιξ",
        r"τάση", r"ταση",  # τάση not τάσ (too broad)
        r"βελτιώνεται", r"βελτιωνεται",
        r"επιδεινώνεται", r"επιδεινωνεται",
        r"συσχέτισ", r"συσχετισ",
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


def detect_intent(message: str) -> list[str]:
    """Detect query intent from Greek message. Returns list of relevant intents."""
    # Normalize: lowercase + strip accents so ω matches ώ, ε matches έ, etc.
    msg_norm = _normalize_greek(message)
    detected = []
    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            # Also normalize the pattern itself
            norm_pattern = _normalize_greek(pattern)
            if re.search(norm_pattern, msg_norm):
                detected.append(intent)
                break
    # Default to full_profile if no specific intent detected
    if not detected:
        return ["full_profile"]
    # If report intent detected, return immediately
    if "report" in detected:
        return ["report"]
    # full_profile overrides specific intents (show everything)
    if "full_profile" in detected:
        return ["full_profile"]
    # checkins takes priority over symptoms (symptoms overlap with checkins)
    if "checkins" in detected and "symptoms" in detected:
        detected.remove("symptoms")
    # Remove pattern_detection from primary intents (it's supplementary)
    primary = [i for i in detected if i != "pattern_detection"]
    if not primary:
        return ["full_profile"]
    # If multiple different primary intents → show full profile
    if len(primary) > 1:
        return ["full_profile"]
    # Single primary intent — return it (optionally with pattern_detection)
    if "pattern_detection" in detected:
        return primary + ["pattern_detection"]
    return primary


def build_selective_context(snap: dict, intents: list[str]) -> str:
    """
    Build medical context string based on detected intents.
    Only loads data relevant to the query — prevents context overflow.
    For full_profile intent: loads everything.
    """
    if not snap or not isinstance(snap, dict):
        return ""

    parts = []

    # Always include basic profile (minimal overhead ~100 tokens)
    name = snap.get("user_name")
    if name:
        parts.append(f"Χρήστης: {name}")
    cond = snap.get("autoimmune_type")
    if cond:
        parts.append(f"Αυτοάνοση πάθηση: {cond}")
    diet = snap.get("diet_pref")
    if diet:
        parts.append(f"Διατροφή: {diet}")
    health_info = snap.get("health_info")
    if health_info and isinstance(health_info, str) and health_info.strip():
        parts.append(f"Ιστορικό φαρμάκων / Υγεία: {health_info.strip()}")

    load_all = ("full_profile" in intents)

    # --- MEDICATIONS ---
    if load_all or "medications" in intents:
        meds = snap.get("medications") or []
        if isinstance(meds, list) and meds:
            med_lines = []
            for m in meds:
                if isinstance(m, dict):
                    n = m.get("medication_name") or m.get("name") or m.get("drug_name") or ""
                    dose = m.get("dosage") or m.get("dose") or ""
                    freq = m.get("frequency") or ""
                    time_slots = m.get("time_slots") or []
                    notes = m.get("notes") or ""
                    if n:
                        line = f"{n}"
                        if dose:
                            line += f" {dose}"
                        if freq:
                            line += f" ({freq})"
                        if isinstance(time_slots, list) and time_slots:
                            line += f" — ώρες λήψης: {', '.join(time_slots)}"
                        elif isinstance(time_slots, str) and time_slots:
                            line += f" — ώρες λήψης: {time_slots}"
                        if notes:
                            line += f" [{notes[:60]}]"
                        med_lines.append(line)
            if med_lines:
                parts.append("Φάρμακα (Medical Memory):\n" + "\n".join(f"• {l}" for l in med_lines))
        # Medication schedule
        med_schedule = snap.get("medication_schedule") or []
        if isinstance(med_schedule, list) and med_schedule:
            sched_lines = []
            for d in med_schedule[:10]:
                if isinstance(d, dict):
                    med_name = d.get("medication_name") or ""
                    dose = d.get("dosage") or ""
                    due = d.get("due_at") or d.get("dose_date") or ""
                    status = d.get("status") or ""
                    if med_name and due:
                        sched_lines.append(f"{due}: {med_name} {dose} [{status}]".strip())
            if sched_lines:
                parts.append("Πρόγραμμα Δόσεων (επόμενες):\n" + "\n".join(sched_lines))

    # --- TEST RESULTS (Structured Exams — from aa_exam_reports) ---
    # IMPORTANT: Only structured, normalised exam data is used here.
    # Raw blobs, OCR text and failed extracts are NEVER exposed as source of truth.
    if load_all or "test_results" in intents:
        # Primary source: structured_exam_results from the Exams Normalizer subsystem
        structured_results = snap.get("structured_exam_results") or []
        # Legacy fallback: raw test_results from WP snapshot (accepted only if no structured data)
        raw_results = snap.get("test_results") or []

        # Prefer structured data; use raw only if structured is completely absent
        results_source = structured_results if structured_results else raw_results
        source_label = "Εξετάσεις (Δομημένα)" if structured_results else "Εξετάσεις (WP Snapshot)"

        if isinstance(results_source, list) and results_source:
            res_lines = []
            for r in results_source:
                if isinstance(r, dict):
                    date = r.get("test_date") or r.get("created_at") or ""
                    name_t = r.get("test_name") or r.get("display_name") or r.get("name") or ""
                    val = r.get("result_value") or r.get("value_numeric") or r.get("value") or ""
                    unit = r.get("unit") or ""
                    ref = r.get("reference_range") or ""
                    status = r.get("status") or r.get("abnormal_flag") or ""
                    note = r.get("notes") or r.get("note") or ""
                    norm_status = r.get("normalization_status") or ""
                    line = f"{date}: {name_t} = {val} {unit}".strip().rstrip(":")
                    if ref:
                        line += f" (Φυσιολογικό: {ref})"
                    if status and status not in ("unknown", ""):
                        # Translate English DB flags to Greek for AI readability
                        _status_gr = {
                            "normal":   "φυσιολογικό",
                            "high":     "υψηλό",
                            "low":      "χαμηλό",
                            "critical": "κρίσιμο",
                            "abnormal": "εκτός ορίων",
                        }.get(status.lower(), status)
                        line += f" [{_status_gr}]"
                    if note:
                        line += f" — {note[:80]}"
                    if line.strip(":"):
                        res_lines.append(line)
            if res_lines:
                parts.append(f"{source_label} ({len(res_lines)} εγγραφές):\n" + "\n".join(res_lines))

    # --- BEST PROTOCOL ---
    if load_all or "best_protocol" in intents:
        best = snap.get("best_protocol") or snap.get("autoanosis_best_protocol") or snap.get("medical_snapshot")
        if isinstance(best, list) and best:
            best = best[0]
        if best and isinstance(best, dict):
            bp = []
            if best.get("visit_date"):    bp.append(f"Ημερομηνία Ραντεβού: {best['visit_date']}")
            if best.get("visit_doctor"):  bp.append(f"Ιατρός/Ειδικότητα: {best['visit_doctor']}")
            if best.get("visit_goal"):    bp.append(f"Στόχος επίσκεψης: {best['visit_goal']}")
            if best.get("visit_period"):  bp.append(f"Περίοδος αναφοράς: {best['visit_period']}")
            if best.get("b_meds"):        bp.append(f"[B] Φάρμακα & δοσολογία: {best['b_meds']}")
            _b_adh = best.get("b_adherence") or best.get("b_side")
            if _b_adh:                    bp.append(f"[B] Συμμόρφωση & παρενέργειες: {_b_adh}")
            if best.get("b_labs"):        bp.append(f"[B] Εξετάσεις εκτός ορίων: {best['b_labs']}")
            _b_notes = best.get("b_notes") or best.get("b_baseline")
            if _b_notes:                  bp.append(f"[B] Σημειώσεις baseline: {_b_notes}")
            if best.get("e_infections"):  bp.append(f"[E] Λοιμώξεις/Ιώσεις: {best['e_infections']}")
            if best.get("e_stress"):      bp.append(f"[E] Στρεσογόνα γεγονότα: {best['e_stress']}")
            _e_life = best.get("e_lifestyle") or best.get("e_events")
            if _e_life:                   bp.append(f"[E] Αλλαγές τρόπου ζωής: {_e_life}")
            if best.get("e_other"):       bp.append(f"[E] Άλλα συμβάντα: {best['e_other']}")
            _s_rows = []
            for i in [1, 2, 3, 4, 5]:
                sn = best.get(f"s{i}_name", "").strip() if best.get(f"s{i}_name") else ""
                sv = best.get(f"s{i}_vas", "")
                sp = best.get(f"s{i}_peak", "").strip() if best.get(f"s{i}_peak") else ""
                sw = best.get(f"s{i}_worse", "").strip() if best.get(f"s{i}_worse") else ""
                sb = best.get(f"s{i}_better", "").strip() if best.get(f"s{i}_better") else ""
                if sn:
                    row = f"{sn} VAS={sv}"
                    if sp: row += f" | Ώρες αιχμής: {sp}"
                    if sw: row += f" | Χειροτερεύει: {sw}"
                    if sb: row += f" | Βελτιώνεται: {sb}"
                    _s_rows.append(row)
            if _s_rows:
                bp.append(f"[S] Συμπτώματα: " + " / ".join(_s_rows))
            if best.get("s_symptoms"):    bp.append(f"[S] Συμπτώματα (επιπλέον): {best['s_symptoms']}")
            _s_tl = best.get("s_timeline") or best.get("s_timing")
            if _s_tl:                     bp.append(f"[S] Χρονική χαρτογράφηση: {_s_tl}")
            _s_fn = best.get("s_functional") or best.get("s_impact")
            if _s_fn:                     bp.append(f"[S] Λειτουργικός αντίκτυπος: {_s_fn}")
            _t_qol = best.get("t_qol") or best.get("t_goals")
            if _t_qol:                    bp.append(f"[T] Στόχοι ποιότητας ζωής: {_t_qol}")
            if best.get("t_biomarkers"):  bp.append(f"[T] Στόχοι βιοδεικτών: {best['t_biomarkers']}")
            if best.get("t_questions"):   bp.append(f"[T] Ερωτήσεις προς ιατρό: {best['t_questions']}")
            _t_plan = best.get("t_plan") or best.get("t_treatments")
            if _t_plan:                   bp.append(f"[T] Πλάνο/Θεραπείες: {_t_plan}")
            _ts = best.get("ts") or best.get("timestamp") or best.get("saved_at")
            if _ts:                       bp.append(f"[Ημ/νία καταχώρισης BEST: {_ts}]")
            if bp:
                parts.append("BEST Protocol (Προετοιμασία Ραντεβού — B.E.S.T.):\n" + "\n".join(bp))

        # BEST History
        best_history = snap.get("best_history")
        if best_history and isinstance(best_history, list) and len(best_history) >= 1:
            _seen_sigs = set()
            _deduped = []
            for _h in best_history:
                if not isinstance(_h, dict): continue
                _ep = _h.get("payload") if ("payload" in _h and isinstance(_h.get("payload"), dict)) else _h
                _sig = f"{_ep.get('visit_date', '')}|{_ep.get('visit_doctor', '')}"
                if _sig in _seen_sigs: continue
                _seen_sigs.add(_sig)
                _deduped.append(_h)
            best_history = _deduped
            hist_lines = [f"Σύνολο καταχωρήσεων BEST: {len(best_history)}"]
            start_idx = 1 if any("BEST Protocol" in p for p in parts) else 0
            for idx, entry in enumerate(best_history[start_idx:], start=start_idx + 1):
                if not isinstance(entry, dict):
                    continue
                ts_raw = entry.get("_saved_ts") or entry.get("ts") or entry.get("timestamp") or ""
                e = entry.get("payload") if ("payload" in entry and isinstance(entry.get("payload"), dict)) else entry
                ts_str = ""
                if ts_raw:
                    try:
                        ts_str = f" [{datetime.fromtimestamp(int(ts_raw)).strftime('%Y-%m-%d')}]"
                    except Exception:
                        ts_str = f" [{ts_raw}]"
                vd = e.get("visit_date", "")
                vdr = e.get("visit_doctor", "")
                vg = e.get("visit_goal", "")
                header = f"  Καταχώρηση #{idx}{ts_str}: Ραντεβού {vd} — {vdr}"
                if vg: header += f" ({vg})"
                hist_lines.append(header)
                if e.get("b_meds"): hist_lines.append(f"    Φάρμακα: {e['b_meds']}")
                if e.get("b_notes"): hist_lines.append(f"    Σημειώσεις: {e['b_notes']}")
                if e.get("b_labs"): hist_lines.append(f"    Εξετάσεις: {e['b_labs']}")
                if e.get("e_stress"): hist_lines.append(f"    Στρες: {e['e_stress']}")
                if e.get("e_infections"): hist_lines.append(f"    Λοιμώξεις: {e['e_infections']}")
                if e.get("e_other"): hist_lines.append(f"    Άλλα: {e['e_other']}")
                for i in [1, 2, 3, 4, 5]:
                    sn = e.get(f"s{i}_name", "").strip() if e.get(f"s{i}_name") else ""
                    sv = e.get(f"s{i}_vas", "")
                    sw = e.get(f"s{i}_worse", "").strip() if e.get(f"s{i}_worse") else ""
                    sb = e.get(f"s{i}_better", "").strip() if e.get(f"s{i}_better") else ""
                    if sn:
                        s_line = f"    Σύμπτωμα: {sn} VAS={sv}"
                        if sw: s_line += f" | Χειροτ.: {sw}"
                        if sb: s_line += f" | Βελτ.: {sb}"
                        hist_lines.append(s_line)
                _t = e.get("t_qol") or e.get("t_goals")
                if _t: hist_lines.append(f"    Στόχος ποιότητας ζωής: {_t}")
                _tp = e.get("t_plan") or e.get("t_treatments")
                if _tp: hist_lines.append(f"    Πλάνο/Ερωτήσεις: {_tp}")
            if len(hist_lines) > 1:
                parts.append("Ιστορικό BEST (όλες οι καταχωρήσεις):\n" + "\n".join(hist_lines))
            elif hist_lines:
                parts.append(f"Σύνολο BEST καταχωρήσεων: {len(best_history)} (η τρέχουσα εγγραφή εμφανίζεται παραπάνω)")

        # best_summary fallback
        best_summary = snap.get("best_summary")
        if best_summary and isinstance(best_summary, str) and best_summary.strip():
            if not any("BEST Protocol" in p for p in parts):
                parts.append(f"BEST Protocol (σύνοψη):\n{best_summary.strip()}")

    # --- CHECK-INS ---
    if load_all or "checkins" in intents:
        checkins = snap.get("recent_checkins") or []
        if isinstance(checkins, list) and checkins:
            ci_lines = []
            for ci in checkins[:7]:
                if isinstance(ci, dict):
                    d = ci.get("checkin_date", "")
                    pain = ci.get("pain_level", "")
                    fatigue = ci.get("fatigue_level", "")
                    energy = ci.get("energy_level", "")
                    mood = ci.get("mood_level", "")
                    notes = ci.get("notes", "")
                    line = f"{d}: πόνος={pain}, κόπωση={fatigue}, ενέργεια={energy}, διάθεση={mood}"
                    if notes:
                        line += f", σημ.: {notes[:60]}"
                    ci_lines.append(line)
            if ci_lines:
                parts.append("Καθημερινό Ημερολόγιο Συμπτωμάτων (check-ins):\n" + "\n".join(ci_lines))

    # --- SYMPTOMS ---
    if load_all or "symptoms" in intents:
        symptoms = snap.get("recent_symptoms") or []
        if isinstance(symptoms, list) and symptoms:
            sym_names = []
            for s in symptoms[:10]:
                if isinstance(s, dict):
                    sn = s.get("symptom_name") or s.get("name") or s.get("symptom") or ""
                    if sn:
                        sym_names.append(sn)
            if sym_names:
                parts.append(f"Πρόσφατα συμπτώματα: {', '.join(sym_names)}")

    # --- HEALTH PROFILE (always for full_profile) ---
    if load_all:
        hp = snap.get("health_profile")
        if isinstance(hp, dict) and hp:
            hp_parts = []
            for k, v in hp.items():
                if v and k not in ("id", "user_id", "created_at", "updated_at"):
                    hp_parts.append(f"{k}: {v}")
            if hp_parts:
                parts.append("Προφίλ υγείας: " + ", ".join(hp_parts[:8]))

        # Health notes
        health_notes = snap.get("health_notes") or []
        if isinstance(health_notes, list) and health_notes:
            hn_lines = []
            for n in health_notes:
                if isinstance(n, dict):
                    date = n.get("created_at") or n.get("date") or ""
                    title = n.get("note_title") or n.get("title") or ""
                    body = n.get("note_content") or n.get("content") or n.get("note") or ""
                    line = f"{date}: {title} — {body[:120]}".strip().rstrip("—").strip()
                    if line.strip(":"): hn_lines.append(line)
            if hn_lines:
                parts.append("Σημειώσεις Υγείας:\n" + "\n".join(hn_lines))

        # Health tracking
        health_tracking = snap.get("health_tracking") or []
        if isinstance(health_tracking, list) and health_tracking:
            ht_lines = []
            for t in health_tracking[:15]:
                if isinstance(t, dict):
                    date = t.get("tracked_at") or t.get("date") or ""
                    metric = t.get("metric_name") or t.get("metric") or t.get("type") or ""
                    val = t.get("metric_value") or t.get("value") or ""
                    unit = t.get("unit") or ""
                    line = f"{date}: {metric} = {val} {unit}".strip().rstrip(":")
                    if line.strip(":"): ht_lines.append(line)
            if ht_lines:
                parts.append("Παρακολούθηση Υγείας:\n" + "\n".join(ht_lines))

    if not parts:
        return ""

    return (
        "\n\nΠΡΟΣΩΠΙΚΑ ΙΑΤΡΙΚΑ ΔΕΔΟΜΕΝΑ ΧΡΗΣΤΗ:\n"
        + "\n\n".join(parts)
        + "\n\nΧρησιμοποίησε αυτά τα στοιχεία για να δώσεις προσωποποιημένες απαντήσεις."
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
        intents = detect_intent(message) if message else ["full_profile"]
        return build_selective_context(unified, intents)

    # Shape B: Autoa_AI_Context_Builder output
    if "user_profile" in wp_context or "health_data" in wp_context:
        return build_context_from_builder(wp_context)

    # Shape C: helpers.php autoa_rest_chat_proxy snapshot
    if any(k in wp_context for k in ("health_info", "autoimmune_type", "user_name", "recent_checkins", "medications", "best_protocol", "test_results")):
        intents = detect_intent(message) if message else ["full_profile"]
        logger.info(f"[CTX] Smart Context Router — intents={intents}")
        return build_selective_context(wp_context, intents)

    # Fallback: treat as aggregator snapshot
    intents = detect_intent(message) if message else ["full_profile"]
    return build_selective_context(wp_context, intents)


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

SYSTEM_PROMPT_BASE = """Είσαι ο Autoanosis Assistant, ένας εξειδικευμένος βοηθός υγείας στα ελληνικά.
Παρέχεις:
- Ακριβείς και επιστημονικά τεκμηριωμένες πληροφορίες υγείας
- Φιλικές και κατανοητές απαντήσεις
- Υποστήριξη σε θέματα υγείας, φαρμάκων, συμπτωμάτων
Σημαντικό:
- ΔΕΝ αντικαθιστάς ιατρική συμβουλή
- Συνιστάς πάντα επίσκεψη σε γιατρό για σοβαρά θέματα
- Απαντάς στα ελληνικά"""

def build_system_prompt(snapshot: str, intents: list[str]) -> str:
    """Build system prompt based on available context and detected intents."""
    if not snapshot:
        return SYSTEM_PROMPT_BASE

    intent_instructions = {
        "medications": "Εστίασε στα φάρμακα, δοσολογία, ώρες λήψης και παρενέργειες.",
        "test_results": "Εστίασε στα αποτελέσματα εξετάσεων. Ανέφερε ΟΛΑ τα αποτελέσματα με τιμές, μονάδες και φυσιολογικά όρια.",
        "best_protocol": "Εστίασε στο BEST Protocol. Ανέφερε ΟΛΑ τα BEST entries με ημερομηνίες και λεπτομέρειες.",
        "checkins": "Εστίασε στο ημερολόγιο συμπτωμάτων. Ανέφερε τάσεις και μεταβολές.",
        "symptoms": "Εστίασε στα συμπτώματα. Ανέφερε πότε εμφανίστηκαν, ένταση και τάσεις.",
        "full_profile": "Δώσε μια σύντομη, ανθρώπινη σύνοψη της υγείας με βάση μόνο τα δεδομένα που υπάρχουν στο context. Πρώτα ανέφερε τα φάρμακα και τις εξετάσεις με τις αξιοσημείωτες τιμές. Αν υπάρχει BEST ή check-ins, συμπερίλαβέ τα συνοπτικά. ΜΗΝ αναφέρεις κατηγορίες που δεν υπάρχουν στο context.",
        "pattern_detection": "Ανάλυσε τάσεις και μοτίβα στα δεδομένα. Εντόπισε συσχετίσεις μεταξύ συμπτωμάτων, εξετάσεων και γεγονότων. ΚΡΙΣΙΜΟ: Παρουσίασε ΜΟΝΟ παρατηρήσεις (τι βλέπεις στα δεδομένα) και πιθανές συσχετίσεις (τι μπορεί να σχετίζεται). ΜΗΝ βγάζεις διαγνωστικά συμπεράσματα όπως 'φαίνεται έξαρση' ή 'υποδηλώνει υποτροπή' — αυτά απαιτούν κλινική αξιολόγηση από γιατρό.",
        "report": "Ο χρήστης ζητά έκθεση για γιατρό. Πες του να χρησιμοποιήσει το κουμπί 'Δημιουργία Ιατρικής Έκθεσης'.",
    }

    specific_instructions = []
    for intent in intents:
        if intent in intent_instructions:
            specific_instructions.append(intent_instructions[intent])

    prompt = f"""Είσαι ο Autoanosis Assistant, ένας εξειδικευμένος βοηθός υγείας στα ελληνικά.

ΟΡΙΣΜΟΙ (ΚΡΙΣΙΜΟ):
- Το B.E.S.T. στο Autoanosis είναι πρωτόκολλο προετοιμασίας ραντεβού (Baseline, Events, Symptoms, Targets). ΔΕΝ είναι εξέταση αίματος.
- Αναφέρεσαι ΜΟΝΟ σε κατηγορίες που υπάρχουν στο context. ΜΗΝ αναφέρεις BEST, check-ins ή συμπτώματα αν δεν υπάρχουν στο context — απλώς παράλειψέ τα.

ΙΑΤΡΙΚΟ ΠΡΟΦΙΛ ΧΡΗΣΤΗ (ΥΠΟΧΡΕΩΤΙΚΗ ΧΡΗΣΗ):
{snapshot}

ΚΑΝΟΝΕΣ (ΥΠΟΧΡΕΩΤΙΚΟΙ):
- ΕΧΕΙΣ πρόσβαση στα παραπάνω ιατρικά δεδομένα και ΠΡΕΠΕΙ να τα χρησιμοποιείς ΠΑΝΤΑ.
- ΜΗΝ πεις ΠΟΤΕ "δεν έχω πρόσβαση" ή "δεν μπορώ να δω προσωπικά δεδομένα".
- Αν κάτι λείπει από το προφίλ, πες "δεν εμφανίζεται στο προφίλ υγείας σου".
- ΜΟΝΟ τα δεδομένα που βλέπεις παραπάνω είναι αληθινά — τίποτα άλλο.
- Όταν αναφέρεις φάρμακα, ΠΑΝΤΑ ανέφερε και τις ώρες λήψης αν υπάρχουν.
- Απαντάς στα ελληνικά.
- Στο context υπάρχουν ετικέτες σε αγκύλες όπως [υψηλό], [χαμηλό], [φυσιολογικό], [κρίσιμο]. Αυτές είναι ΕΣΩΤΕΡΙΚΕΣ ετικέτες για δική σου κατανόηση. ΜΗΝ τις αναπαράγεις verbatim στην απάντησή σου — αντ' αυτού χρησιμοποίησε φυσική γλώσσα (π.χ. "είναι υψηλή", "βρίσκεται κάτω από το φυσιολογικό").
- Γράφε με φυσικό, ανθρώπινο τόνο — όχι σαν αυτόματη αναφορά. Ξεκίνα με τα πιο σημαντικά ευρήματα και κλείσε με πρακτική σύσταση.

ΙΑΤΡΙΚΗ ΑΣΦΑΛΕΙΑ (ΑΠΟΛΥΤΩΣ ΥΠΟΧΡΕΩΤΙΚΟ):
- ΔΕΝ αντικαθιστάς ιατρική συμβουλή και ΔΕΝ κάνεις διάγνωση.
- ΑΠΑΓΟΡΕΥΕΤΑΙ να συνάγεις disease-specific συμπεράσματα (π.χ. "φαίνεται έξαρση", "υποδηλώνει υποτροπή", "ενδέχεται να είναι relapse") από μη ειδικούς δείκτες όπως CRP, HGB, RBC, PCT, άγχος, αϋπνία ή πόνος. Αυτοί οι δείκτες δεν είναι ειδικοί για καμία αυτοάνοση νόσο.
- Χρησιμοποίησε ΠΑΝΤΑ τριεπίπεδη παρουσίαση όταν αναλύεις δεδομένα:
  1. ΠΑΡΑΤΗΡΗΣΗ: Τι δείχνουν τα δεδομένα (π.χ. "Η τιμή CRP είναι 2.89 mg/dL, πάνω από το φυσιολογικό")
  2. ΠΙΘΑΝΗ ΣΥΣΧΕΤΙΣΗ: Τι μπορεί να σχετίζεται (π.χ. "Αυξημένη CRP μπορεί να σχετίζεται με φλεγμονή ή λοίμωξη")
  3. ΠΕΡΙΟΡΙΣΜΟΣ: Τι ΔΕΝ μπορεί να συναχθεί (π.χ. "Δεν μπορώ να συνδέσω αυτά τα ευρήματα με συγκεκριμένη έξαρση — αυτό απαιτεί κλινική αξιολόγηση")
- Αντί για "φαίνεται έξαρση" ή "υποδηλώνει υποτροπή", χρησιμοποίησε: "υπάρχουν ευρήματα που χρήζουν ιατρικής αξιολόγησης".
- Αν ο χρήστης ρωτήσει ρητά αν υπάρχει έξαρση/υποτροπή, απάντησε ξεκάθαρα: Δεν μπορώ να κρίνω αν υπάρχει έξαρση — αυτό απαιτεί νευρολογική εξέταση και εξειδικευμένα κριτήρια. Τα δεδομένα που βλέπω χρειάζονται αξιολόγηση από τον γιατρό σου."""

    if specific_instructions:
        prompt += "\n\nΟΔΗΓΙΕΣ ΓΙΑ ΑΥΤΗ ΤΗΝ ΕΡΩΤΗΣΗ:\n" + "\n".join(f"• {i}" for i in specific_instructions)

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
    intents = ["full_profile"]

    if isinstance(wp_context, dict):
        ctx_key_used = "wp_context" if data.get("wp_context") else "medical_snapshot"
        logger.info(f"[CTX] received {ctx_key_used} keys={list(wp_context.keys())[:10]}")

        # Detect intent from user message
        intents = detect_intent(user_message)
        logger.info(f"[ROUTER] user={user_id} intents={intents} message_preview={user_message[:50]}")

        # Build selective context
        snapshot = extract_context_from_wp_push(wp_context, user_message)
        if snapshot:
            snapshot_source = "wp_push_smart"
            context_bytes = len(snapshot.encode("utf-8"))
            logger.info(
                f"[CONTEXT] user={user_id} source={snapshot_source} "
                f"intents={intents} context_bytes={context_bytes}"
            )
        else:
            logger.warning(f"[CONTEXT] context present but empty after extraction for user={user_id}")
    else:
        logger.warning(f"[CTX] no context received — type={type(wp_context).__name__} user={user_id}")

    # --- Build system prompt ---
    system_prompt = build_system_prompt(snapshot, intents)
    logger.info(f"[PROMPT] Medical context injected for user={user_id} source={snapshot_source} intents={intents}")

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

        logger.info(f"[CHAT] user={user_id} conv={conversation_id} intents={intents}")

        return jsonify({
            "reply": ai_response,
            "conversation_id": conversation_id,
            "intents": intents  # For debugging
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
    Three-pass system: aggregation → AI analysis → PDF assembly.
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
