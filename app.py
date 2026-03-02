"""Autoanosis AI Backend v5.9.0"
Professional Flask backend for AI Assistant with Medical Context
Deployed on Render.com
Changelog:
v5.9.0 (2026-03-02) - Fix: Clear separation of BEST Protocol vs daily check-ins in system prompt and context labels
v5.8.0 (2026-03-02) - Enhanced BEST Protocol parsing and search keys
v5.7.0 (2026-03-01) - Full medical data: ALL BEST fields + timestamps + test_results + health_notes + health_tracking + best_summary fallback
v5.7.0 (2026-02-28) - Add BEST protocol support in helpers snapshot + best_protocol detection key
v5.4.0 (2026-02-28) - Handle helpers.php snapshot structure (health_info, autoimmune_type, medications)
v5.3.0 (2026-02-28) - Accept both wp_context and medical_snapshot keys from WordPress
v5.2.0 (2026-02-28) - CTX logs, BEST system prompt fix, wp_context key logging
v5.1.0 (2026-02-28) - WP PUSH architecture (final solution)
- ARCH: Render no longer pulls from WordPress (WAF-proof)
- ARCH: WordPress chat-proxy pushes wp_context in request body
- SECURITY: HMAC-SHA256 signature on proxy requests (X-Autoa-Proxy-Sig)
- SECURITY: Timestamp anti-replay (5-min window)
- NEW: AUTOA_AI_PROXY_SECRET env var for proxy HMAC verification
- CLEAN: Removed all WordPress pull logic (WORDPRESS_AJAX_URL etc. no longer needed)
- LOGS: [PROXY], [CONTEXT], [PROMPT] structured log prefixes
v5.0.0 (2026-02-28) - Admin-ajax HMAC bridge (blocked by WAF)
v4.6.0 (2026-02-27) - WAF-bypass endpoint attempt via /wp-json/autoanosis-internal/
v4.5.0 (2026-02-27) - Fix WordPress endpoint URL
v4.4.0 (2026-02-27) - Production-grade schema validation
v4.3.0 (2026-02-27) - Accept 2xx responses from WordPress
v4.1.0 (2026-02-25) - Phase 1+2 Security Hardening
v4.0.0 (2026-02-25) - WordPress Aggregator Integration
"""
import os
import hmac as _hmac
import hashlib
import json
import logging
import time
import uuid
import requests
from collections import defaultdict
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from identity import verify_identity_token
from ocr_endpoint import ocr_bp

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

CORS(app, resources={
    r"/*": {
        "origins": ["https://autoanosis.com", "https://www.autoanosis.com"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "X-User-ID", "X-Autoa-Proxy-TS", "X-Autoa-Proxy-Nonce", "X-Autoa-Proxy-Sig"],
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
# v5.1.0: WP PUSH — Render verifies proxy signature, never pulls from WP
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
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_BASE = """Είσαι ο Autoanosis Assistant, ένας εξειδικευμένος βοηθός υγείας στα ελληνικά.
Παρέχεις:
- Ακριβείς και επιστημονικά τεκμηριωμένες πληροφορίες υγείας
- Φιλικές και κατανοητές απαντήσεις
- Υποστήριξη σε θέματα υγείας, φαρμάκων, συμπτωμάτων
Σημαντικό:
- ΔΕΝ αντικαθιστάς ιατρική συμβουλή
- Συνιστάς πάντα επίσκεψη σε γιατρό για σοβαρά θέματα
- Απαντάς στα ελληνικά

ΔΟΜΗ ΔΕΔΟΜΕΝΩΝ ΧΡΗΣΤΗ — ΚΑΤΑΝΟΗΣΕ ΤΗ ΔΙΑΦΟΡΑ:
1. "Πρόσφατα check-ins" = Καθημερινό ημερολόγιο συμπτωμάτων (πόνος, κόπωση, ενέργεια, διάθεση). Είναι ΞΕΧΩΡΙΣΤΟ από το BEST Protocol.
2. "BEST Protocol (Προετοιμασία Ραντεβού — B.E.S.T.)" = Δομημένη προετοιμασία για ιατρικό ραντεβού. Περιέχει: ημερομηνία ραντεβού, ιατρό, φάρμακα (B), γεγονότα (E), συμπτώματα BEST (S), στόχους (T). ΠΟΤΕ μην αναμιγνύεις αυτά τα δύο.
3. "Αποτελέσματα Εξετάσεων" = Εργαστηριακές εξετάσεις με ημερομηνίες και τιμές.
4. "Ιστορικό φαρμάκων / Υγεία" = Ελεύθερο κείμενο με ιστορικό θεραπειών.

Όταν ο χρήστης ρωτά για το BEST, αναφέρσου ΜΟΝΟ στα δεδομένα από την ενότητα "BEST Protocol". Όταν ρωτά για check-ins ή ημερολόγιο, αναφέρσου ΜΟΝΟ στην ενότητα "Πρόσφατα check-ins"."""

# ---------------------------------------------------------------------------
# HMAC proxy signature verification (v5.1.0)
# Canonical: TS.NONCE.RAW_BODY
# ---------------------------------------------------------------------------
def verify_proxy_signature(ts_str: str, nonce: str, raw_body: bytes, sig: str) -> tuple[bool, str]:
    """Verify HMAC signature from WordPress chat-proxy."""
    if not AUTOA_PROXY_SECRET:
        # If no secret configured, skip verification (dev mode)
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

# ---------------------------------------------------------------------------
# Medical context extraction from wp_context (v5.1.0)
# Handles both aggregator REST shape and ai-context-builder shape
# ---------------------------------------------------------------------------
def extract_context_from_wp_push(wp_context: dict) -> str:
    """
    Extract a formatted medical context string from the wp_context dict
    pushed by the WordPress chat-proxy.

    Handles two shapes:
    Shape A: Aggregator REST response (autoanosis/v1/bot/medical-context)
      { "context_text": "...", "data": {...}, "unified": {...} }
    Shape B: Autoa_AI_Context_Builder::build_context() output
      { "user_profile": {...}, "health_data": {...}, "recent_checkins": {...}, ... }
    """
    if not wp_context or not isinstance(wp_context, dict):
        return ""

    # Shape A: pre-formatted context_text
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
        return build_medical_context_from_aggregator(unified)

    # Shape B: Autoa_AI_Context_Builder output
    if "user_profile" in wp_context or "health_data" in wp_context:
        return build_medical_context_from_builder(wp_context)

    # Shape C: helpers.php autoa_rest_chat_proxy snapshot
    # Keys: user_id, user_name, autoimmune_type, diet_pref, health_info,
    #        health_profile, recent_checkins, medications, recent_symptoms,
    #        health_tracking, test_results, health_notes, medication_reminders
    if any(k in wp_context for k in ("health_info", "autoimmune_type", "user_name", "recent_checkins", "medications", "best_protocol")):
        return build_medical_context_from_helpers_snapshot(wp_context)

    # Shape A fallback: try treating the whole dict as aggregator snapshot
    return build_medical_context_from_aggregator(wp_context)


def build_medical_context_from_helpers_snapshot(snap: dict) -> str:
    """Build context string from helpers.php autoa_rest_chat_proxy snapshot."""
    if not snap or not isinstance(snap, dict):
        return ""

    parts = []

    # User name
    name = snap.get("user_name")
    if name:
        parts.append(f"Όνομα: {name}")

    # Autoimmune condition
    cond = snap.get("autoimmune_type")
    if cond:
        parts.append(f"Αυτοάνοση πάθηση: {cond}")

    # Diet preference
    diet = snap.get("diet_pref")
    if diet:
        parts.append(f"Διατροφή: {diet}")

    # Health info (free text — medication history etc.)
    health_info = snap.get("health_info")
    if health_info and isinstance(health_info, str) and health_info.strip():
        parts.append(f"Ιστορικό φαρμάκων / Υγεία: {health_info.strip()}")

    # Current medications from table
    meds = snap.get("medications") or []
    if isinstance(meds, list) and meds:
        med_names = []
        for m in meds:
            if isinstance(m, dict):
                n = m.get("medication_name") or m.get("name") or m.get("drug_name") or ""
                dose = m.get("dosage") or m.get("dose") or ""
                if n:
                    med_names.append(f"{n} {dose}".strip())
        if med_names:
            parts.append(f"Τρέχοντα φάρμακα: {', '.join(med_names)}")

    # Recent check-ins
    checkins = snap.get("recent_checkins") or []
    if isinstance(checkins, list) and checkins:
        ci_lines = []
        for ci in checkins[:5]:
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
            parts.append("Καθημερινό Ημερολόγιο Συμπτωμάτων (check-ins — ΞΕΧΩΡΙΣΤΟ ΑΠΟ BEST):\n" + "\n".join(ci_lines))

    # Recent symptoms
    symptoms = snap.get("recent_symptoms") or []
    if isinstance(symptoms, list) and symptoms:
        sym_names = []
        for s in symptoms[:5]:
            if isinstance(s, dict):
                sn = s.get("symptom_name") or s.get("name") or s.get("symptom") or ""
                if sn:
                    sym_names.append(sn)
        if sym_names:
            parts.append(f"Πρόσφατα συμπτώματα: {', '.join(sym_names)}")

    # Health profile table
    hp = snap.get("health_profile")
    if isinstance(hp, dict) and hp:
        hp_parts = []
        for k, v in hp.items():
            if v and k not in ("id", "user_id", "created_at", "updated_at"):
                hp_parts.append(f"{k}: {v}")
        if hp_parts:
            parts.append("Προφίλ υγείας: " + ", ".join(hp_parts[:8]))

    # BEST Protocol (from autoanosis_medical_snapshot_last) — ALL FIELDS v5.8.0
    # Enhanced search for BEST data in various keys
    best = snap.get("best_protocol") or snap.get("autoanosis_best_protocol") or snap.get("medical_snapshot")
    
    # If it's a list (sometimes happens in aggregator), take the first element if it looks like BEST
    if isinstance(best, list) and best:
        best = best[0]
        
    if best and isinstance(best, dict):
        bp = []
        # Visit info
        if best.get("visit_date"):    bp.append(f"Ημερομηνία Ραντεβού: {best['visit_date']}")
        if best.get("visit_doctor"):  bp.append(f"Ιατρός/Ειδικότητα: {best['visit_doctor']}")
        if best.get("visit_goal"):    bp.append(f"Στόχος επίσκεψης: {best['visit_goal']}")
        if best.get("visit_period"):  bp.append(f"Περίοδος αναφοράς: {best['visit_period']}")
        # B — Baseline
        if best.get("b_meds"):        bp.append(f"[B] Φάρμακα & δοσολογία: {best['b_meds']}")
        if best.get("b_side"):        bp.append(f"[B] Συμμόρφωση & παρενέργειες: {best['b_side']}")
        if best.get("b_labs"):        bp.append(f"[B] Εξετάσεις εκτός ορίων: {best['b_labs']}")
        if best.get("b_baseline"):    bp.append(f"[B] Σημειώσεις baseline (ύπνος/ενέργεια/πίεση): {best['b_baseline']}")
        # E — Events
        if best.get("e_infections"):  bp.append(f"[E] Λοιμώξεις/Ιώσεις: {best['e_infections']}")
        if best.get("e_stress"):      bp.append(f"[E] Στρεσογόνα γεγονότα: {best['e_stress']}")
        _e_life = best.get("e_lifestyle") or best.get("e_events")
        if _e_life:                   bp.append(f"[E] Αλλαγές τρόπου ζωής: {_e_life}")
        if best.get("e_other"):       bp.append(f"[E] Άλλα συμβάντα: {best['e_other']}")
        # S — Symptoms
        if best.get("s_symptoms"):    bp.append(f"[S] Συμπτώματα (VAS 0-10): {best['s_symptoms']}")
        if best.get("s_timing"):      bp.append(f"[S] Χρονική χαρτογράφηση: {best['s_timing']}")
        if best.get("s_impact"):      bp.append(f"[S] Λειτουργικός αντίκτυπος: {best['s_impact']}")
        # T — Targets
        if best.get("t_goals"):       bp.append(f"[T] Στόχοι ποιότητας ζωής: {best['t_goals']}")
        if best.get("t_biomarkers"):  bp.append(f"[T] Στόχοι βιοδεικτών: {best['t_biomarkers']}")
        if best.get("t_questions"):   bp.append(f"[T] Ερωτήσεις προς ιατρό: {best['t_questions']}")
        _t_plan = best.get("t_plan") or best.get("t_treatments")
        if _t_plan:                   bp.append(f"[T] Πλάνο/Θεραπείες: {_t_plan}")
        # Timestamp of BEST entry
        _ts = best.get("ts") or best.get("timestamp") or best.get("saved_at")
        if _ts:                       bp.append(f"[Ημ/νία καταχώρισης BEST: {_ts}]")
        if bp:
            parts.append("BEST Protocol (Προετοιμασία Ραντεβού — B.E.S.T.):\n" + "\n".join(bp))

    # best_summary fallback (text version built by helpers.php)
    best_summary = snap.get("best_summary")
    if best_summary and isinstance(best_summary, str) and best_summary.strip():
        if not any("BEST Protocol" in p for p in parts):
            parts.append(f"BEST Protocol (σύνοψη):\n{best_summary.strip()}")

    # Medical memory / BEST summary text
    memory = snap.get("medical_memory") or snap.get("autoanosis_medical_memory")
    if memory and isinstance(memory, str) and memory.strip():
        if not any("BEST" in p for p in parts):
            parts.append(f"Προετοιμασία Ραντεβού (B.E.S.T.):\n{memory.strip()}")

    # Test results (lab results with dates)
    test_results = snap.get("test_results") or []
    if isinstance(test_results, list) and test_results:
        res_lines = []
        for r in test_results:
            if isinstance(r, dict):
                date = r.get("test_date") or r.get("created_at") or ""
                name = r.get("test_name") or r.get("name") or ""
                val  = r.get("result_value") or r.get("value") or ""
                unit = r.get("unit") or ""
                note = r.get("notes") or r.get("note") or ""
                line = f"{date}: {name} = {val} {unit}".strip().rstrip(":")
                if note: line += f" ({note[:80]})"
                if line.strip(":"): res_lines.append(line)
        if res_lines:
            parts.append("Αποτελέσματα Εξετάσεων (με ημερομηνία):\n" + "\n".join(res_lines))

    # Health notes
    health_notes = snap.get("health_notes") or []
    if isinstance(health_notes, list) and health_notes:
        hn_lines = []
        for n in health_notes:
            if isinstance(n, dict):
                date  = n.get("created_at") or n.get("date") or ""
                title = n.get("note_title") or n.get("title") or ""
                body  = n.get("note_content") or n.get("content") or n.get("note") or ""
                line  = f"{date}: {title} — {body[:120]}".strip().rstrip("—").strip()
                if line.strip(":"): hn_lines.append(line)
        if hn_lines:
            parts.append("Σημειώσεις Υγείας:\n" + "\n".join(hn_lines))

    # Health tracking (with timestamps)
    health_tracking = snap.get("health_tracking") or []
    if isinstance(health_tracking, list) and health_tracking:
        ht_lines = []
        for t in health_tracking[:15]:
            if isinstance(t, dict):
                date   = t.get("tracked_at") or t.get("date") or ""
                metric = t.get("metric_name") or t.get("metric") or t.get("type") or ""
                val    = t.get("metric_value") or t.get("value") or ""
                unit   = t.get("unit") or ""
                line   = f"{date}: {metric} = {val} {unit}".strip().rstrip(":")
                if line.strip(":"): ht_lines.append(line)
        if ht_lines:
            parts.append("Παρακολούθηση Υγείας:\n" + "\n".join(ht_lines))

    if not parts:
        return ""

    return (
        "\n\nΠΡΟΣΩΠΙΚΑ ΙΑΤΡΙΚΑ ΔΕΔΟΜΕΝΑ ΧΡΗΣΤΗ:\n"
        + "\n".join(parts)
        + "\n\nΧρησιμοποίησε αυτά τα στοιχεία για να δώσεις προσωποποιημένες απαντήσεις."
    )


def build_medical_context_from_aggregator(snapshot: dict) -> str:
    """Build context string from aggregator snapshot dict."""
    if not snapshot or not isinstance(snapshot, dict):
        return ""

    parts = []

    meds = snapshot.get("autoanosis_medications") or snapshot.get("medications") or []
    if isinstance(meds, list) and meds:
        names = [m.get("name") or m.get("medication_name", "") for m in meds if isinstance(m, dict)]
        names = [n for n in names if n]
        if names:
            parts.append(f"Φάρμακα: {', '.join(names)}")

    conds = snapshot.get("autoanosis_conditions") or snapshot.get("conditions") or []
    if isinstance(conds, list) and conds:
        names = [c.get("name", "") for c in conds if isinstance(c, dict) and c.get("name")]
        if names:
            parts.append(f"Παθήσεις: {', '.join(names)}")

    allergies = snapshot.get("autoanosis_allergies") or snapshot.get("allergies") or []
    if isinstance(allergies, list) and allergies:
        names = [a.get("name", "") for a in allergies if isinstance(a, dict) and a.get("name")]
        if names:
            parts.append(f"Αλλεργίες: {', '.join(names)}")

    memory = snapshot.get("autoanosis_medical_memory") or snapshot.get("medical_memory")
    if memory:
        if isinstance(memory, str) and memory.strip():
            parts.append(f"Προετοιμασία Ραντεβού (B.E.S.T.):\n{memory}")
        elif isinstance(memory, list):
            notes = [m.get("note", "") for m in memory[:3] if isinstance(m, dict) and m.get("note")]
            if notes:
                parts.append(f"Σημειώσεις: {'; '.join(notes)}")

    best = snapshot.get("autoanosis_best_protocol") or snapshot.get("best_protocol")
    if best and isinstance(best, dict):
        bp = []
        if best.get("visit_doctor"): bp.append(f"Ιατρός: {best['visit_doctor']}")
        if best.get("visit_goal"):   bp.append(f"Στόχος: {best['visit_goal']}")
        if best.get("b_labs"):       bp.append(f"Baseline: {best['b_labs']}")
        if best.get("e_infections"): bp.append(f"Λοιμώξεις: {best['e_infections']}")
        if best.get("e_stress"):     bp.append(f"Stress: {best['e_stress']}")
        if bp and not any("B.E.S.T." in p for p in parts):
            parts.append("BEST Protocol:\n" + "\n".join(bp))

    if not parts:
        return ""

    return (
        "\n\nΠΡΟΣΩΠΙΚΑ ΙΑΤΡΙΚΑ ΔΕΔΟΜΕΝΑ ΧΡΗΣΤΗ:\n"
        + "\n".join(parts)
        + "\n\nΧρησιμοποίησε αυτά τα στοιχεία για να δώσεις προσωποποιημένες απαντήσεις."
    )


def build_medical_context_from_builder(ctx: dict) -> str:
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
            f"Πόνος: {avg.get('pain','?')}/10, "
            f"Κόπωση: {avg.get('fatigue','?')}/10, "
            f"Ενέργεια: {avg.get('energy','?')}/10, "
            f"Διάθεση: {avg.get('mood','?')}/10"
        )
        trend_map = {"improving": "βελτιώνονται", "worsening": "επιδεινώνονται", "stable": "σταθερά"}
        trend = checkins.get("trend")
        if trend and trend in trend_map:
            parts.append(f"Τάση: Τα συμπτώματα {trend_map[trend]}")

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

    lifestyle = ctx.get("lifestyle") or {}
    if isinstance(lifestyle, dict):
        if lifestyle.get("diet_plan"):
            parts.append(f"Διατροφή: {lifestyle['diet_plan']}")
        triggers = lifestyle.get("trigger_foods")
        if triggers:
            if isinstance(triggers, list):
                parts.append(f"Τρόφιμα που επιδεινώνουν: {', '.join(str(t) for t in triggers)}")
            elif isinstance(triggers, str) and triggers.strip():
                parts.append(f"Τρόφιμα που επιδεινώνουν: {triggers}")
        if lifestyle.get("stress_level"):
            parts.append(f"Επίπεδο στρες: {lifestyle['stress_level']}/10")

    if not parts:
        return ""

    return (
        "\n\nΠΡΟΣΩΠΙΚΑ ΙΑΤΡΙΚΑ ΔΕΔΟΜΕΝΑ ΧΡΗΣΤΗ:\n"
        + "\n".join(parts)
        + "\n\nΧρησιμοποίησε αυτά τα στοιχεία για να δώσεις προσωποποιημένες απαντήσεις."
    )

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "autoanosis-ai-backend",
        "version": "5.9.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "architecture": "wp_push",
        "features": [
            "wp_push_context",
            "proxy_hmac_verification",
            "session_memory",
            "rate_limiting",
            "audit_logging"
        ],
        "config": {
            "proxy_secret_configured": bool(AUTOA_PROXY_SECRET),
        }
    }), 200

# ---------------------------------------------------------------------------
# Chat endpoint (v5.1.0 — WP PUSH)
# ---------------------------------------------------------------------------
@app.route('/chat', methods=['POST'])
def chat():
    if len(conversation_storage) > 100:
        cleanup_old_conversations()

    # --- Verify proxy HMAC signature ---
    raw_body = request.get_data()
    ts_str   = request.headers.get("X-Autoa-Proxy-TS", "")
    nonce    = request.headers.get("X-Autoa-Proxy-Nonce", "")
    sig      = request.headers.get("X-Autoa-Proxy-Sig", "")

    if ts_str or nonce or sig:
        # Signature headers present — verify them
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

    # --- Extract medical context from wp_context or medical_snapshot (WP PUSH) ---
    # WordPress helpers.php sends key 'medical_snapshot'; chat-proxy-endpoint.php sends 'wp_context'
    wp_context = data.get("wp_context") or data.get("medical_snapshot")
    snapshot = ""
    snapshot_source = "none"

    if isinstance(wp_context, dict):
        ctx_key_used = "wp_context" if data.get("wp_context") else "medical_snapshot"
        logger.info(f"[CTX] received {ctx_key_used} keys={list(wp_context.keys())[:10]}")
        snapshot = extract_context_from_wp_push(wp_context)
        if snapshot:
            snapshot_source = "wp_push"
            context_bytes = len(snapshot.encode("utf-8"))
            logger.info(
                f"[CONTEXT] user={user_id} source={snapshot_source} "
                f"context_bytes={context_bytes} prompt_injected=true"
            )
        else:
            logger.warning(f"[CONTEXT] context present but empty after extraction for user={user_id} keys={list(wp_context.keys())[:10]}")
    else:
        logger.warning(f"[CTX] no context received — type={type(wp_context).__name__} user={user_id} body_keys={list(data.keys())}")

    # --- Build system prompt ---
    if snapshot:
        system_prompt = f"""Είσαι ο Autoanosis Assistant, ένας εξειδικευμένος βοηθός υγείας στα ελληνικά.
Παρέχεις:
- Ακριβείς και επιστημονικά τεκμηριωμένες πληροφορίες υγείας
- Φιλικές και κατανοητές απαντήσεις
- Υποστήριξη σε θέματα υγείας, φαρμάκων, συμπτωμάτων
Σημαντικό:
- ΔΕΝ αντικαθιστάς ιατρική συμβουλή
- Συνιστάς πάντα επίσκεψη σε γιατρό για σοβαρά θέματα
- Απαντάς στα ελληνικά
ΟΡΙΣΜΟΙ (ΚΡΙΣΙΜΟ):
- Το B.E.S.T. στο Autoanosis είναι το δικό μας πρωτόκολλο προετοιμασίας ραντεβού (Baseline, Events, Symptoms, Targets). ΔΕΝ είναι εξέταση αίματος.
- Αν δεν υπάρχει BEST πεδίο στο context, λες "Δεν έχει καταγραφεί ακόμα" — ΔΕΝ επινοείς.
ΙΑΤΡΙΚΟ ΠΡΟΦΙΛ ΧΡΗΣΤΗ (ΥΠΟΧΡΕΩΤΙΚΗ ΧΡΗΣΗ):
{snapshot}
ΚΑΝΟΝΕΣ:
- ΕΧΕΙΣ πρόσβαση στα παραπάνω ιατρικά δεδομένα και ΠΡΕΠΕΙ να τα χρησιμοποιείς
- ΜΗΝ πεις ΠΟΤΕ "δεν έχω πρόσβαση" ή "δεν μπορώ να δω προσωπικά δεδομένα"
- Αν κάτι λείπει από το προφίλ, πες "δεν εμφανίζεται στο προφίλ υγείας σου"
- Χρησιμοποίησε το προφίλ ΜΟΝΟ όταν είναι σχετικό με την ερώτηση
- ΜΟΝΟ τα δεδομένα που βλέπεις παραπάνω είναι αληθινά - τίποτα άλλο"""
        logger.info(f"[PROMPT] Medical context injected for user={user_id} source={snapshot_source}")
    else:
        system_prompt = SYSTEM_PROMPT_BASE
        logger.info(f"[PROMPT] No medical context for user={user_id} — base prompt used")

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
            temperature=0.7
        )
        ai_response = response.choices[0].message.content

        save_conversation_message(conversation_id, user_id, "user", user_message)
        save_conversation_message(conversation_id, user_id, "assistant", ai_response)

        logger.info(f"[CHAT] user={user_id} conv={conversation_id}")

        return jsonify({"reply": ai_response, "conversation_id": conversation_id})

    except Exception as e:
        logger.error(f"[OPENAI] error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
