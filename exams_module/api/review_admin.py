"""
review_admin.py — Minimal Review Queue Admin UI
================================================
Blueprint: /exams/admin

Provides a read-only HTML dashboard for reviewing the exam review queue.
Protected by X-Admin-Secret header (env var: AUTOA_ADMIN_SECRET).

Endpoints:
  GET  /exams/admin                      — HTML dashboard (open items)
  GET  /exams/admin/queue                — JSON list of open review items
  GET  /exams/admin/queue/all            — JSON list of all items (any status)
  GET  /exams/admin/stats                — JSON summary stats

Auth:
  All endpoints require X-Admin-Secret header matching AUTOA_ADMIN_SECRET env var.
  Returns 403 if missing or invalid. Deny by default.

Design:
  - No write operations here — resolve is handled by PATCH /exams/review-queue/{id}/resolve
    in exams_flask.py (which uses the role-based doctor/admin gate).
  - This blueprint is for inspection and monitoring only.
  - Intentionally minimal: no JS framework, no external CDN dependencies.
"""

import os
import logging
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, Response
from sqlalchemy.orm import Session

from exams_module.db.database import get_db
from exams_module.models.exam_models import ExamReviewQueue, ExamDocument

logger = logging.getLogger(__name__)

review_admin_bp = Blueprint("review_admin", __name__, url_prefix="/exams/admin")

# ─── Auth Gate ────────────────────────────────────────────────────────────────

def _require_admin_secret() -> bool:
    """
    Verify X-Admin-Secret header against AUTOA_ADMIN_SECRET env var.
    Returns True if valid, False otherwise.
    Deny by default if env var is not set.
    """
    secret = os.environ.get("AUTOA_ADMIN_SECRET", "").strip()
    if not secret:
        logger.warning("[REVIEW_ADMIN] AUTOA_ADMIN_SECRET not configured — denying all requests")
        return False
    provided = request.headers.get("X-Admin-Secret", "").strip()
    if not provided:
        return False
    # Constant-time comparison to prevent timing attacks
    import hmac as _hmac
    return _hmac.compare_digest(secret.encode(), provided.encode())


def _auth_error() -> tuple:
    return jsonify({"error": "Forbidden — valid X-Admin-Secret required"}), 403


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _format_dt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _queue_item_to_dict(item: ExamReviewQueue, doc: ExamDocument | None) -> dict:
    return {
        "id": item.id,
        "document_id": item.document_id,
        "patient_id": item.patient_id,
        "reason_code": item.reason_code,
        "reason_text": item.reason_text,
        "resolution_status": item.resolution_status,
        "assigned_to": item.assigned_to,
        "resolved_by": item.resolved_by,
        "resolution_note": item.resolution_note,
        "created_at": _format_dt(item.created_at),
        "resolved_at": _format_dt(item.resolved_at),
        # Document metadata (if available)
        "document": {
            "original_filename": doc.original_filename if doc else None,
            "mime_type": doc.mime_type if doc else None,
            "ingestion_source": doc.ingestion_source if doc else None,
            "status": doc.status if doc else None,
            "uploaded_at": _format_dt(doc.uploaded_at) if doc else None,
        } if doc else None,
    }


# ─── JSON Endpoints ───────────────────────────────────────────────────────────

@review_admin_bp.route("/queue", methods=["GET"])
def get_open_queue():
    """GET /exams/admin/queue — JSON list of open review items."""
    if not _require_admin_secret():
        return _auth_error()

    try:
        db: Session = next(get_db())
        items = (
            db.query(ExamReviewQueue)
            .filter(ExamReviewQueue.resolution_status == "open")
            .order_by(ExamReviewQueue.created_at.desc())
            .limit(200)
            .all()
        )
        doc_ids = [i.document_id for i in items]
        docs = {d.id: d for d in db.query(ExamDocument).filter(ExamDocument.id.in_(doc_ids)).all()}

        return jsonify({
            "status": "ok",
            "count": len(items),
            "items": [_queue_item_to_dict(i, docs.get(i.document_id)) for i in items],
        })
    except Exception as e:
        logger.error(f"[REVIEW_ADMIN] get_open_queue error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@review_admin_bp.route("/queue/all", methods=["GET"])
def get_all_queue():
    """GET /exams/admin/queue/all — JSON list of all review items (any status)."""
    if not _require_admin_secret():
        return _auth_error()

    try:
        db: Session = next(get_db())
        items = (
            db.query(ExamReviewQueue)
            .order_by(ExamReviewQueue.created_at.desc())
            .limit(500)
            .all()
        )
        doc_ids = [i.document_id for i in items]
        docs = {d.id: d for d in db.query(ExamDocument).filter(ExamDocument.id.in_(doc_ids)).all()}

        return jsonify({
            "status": "ok",
            "count": len(items),
            "items": [_queue_item_to_dict(i, docs.get(i.document_id)) for i in items],
        })
    except Exception as e:
        logger.error(f"[REVIEW_ADMIN] get_all_queue error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@review_admin_bp.route("/stats", methods=["GET"])
def get_stats():
    """GET /exams/admin/stats — JSON summary stats for the review queue."""
    if not _require_admin_secret():
        return _auth_error()

    try:
        db: Session = next(get_db())
        total = db.query(ExamReviewQueue).count()
        open_count = db.query(ExamReviewQueue).filter(ExamReviewQueue.resolution_status == "open").count()
        resolved_count = db.query(ExamReviewQueue).filter(ExamReviewQueue.resolution_status == "resolved").count()
        total_docs = db.query(ExamDocument).count()

        return jsonify({
            "status": "ok",
            "review_queue": {
                "total": total,
                "open": open_count,
                "resolved": resolved_count,
            },
            "documents": {
                "total": total_docs,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.error(f"[REVIEW_ADMIN] get_stats error: {e}")
        return jsonify({"error": "Internal server error"}), 500


# ─── HTML Dashboard ───────────────────────────────────────────────────────────

@review_admin_bp.route("", methods=["GET"])
@review_admin_bp.route("/", methods=["GET"])
def admin_dashboard():
    """
    GET /exams/admin — Minimal HTML dashboard for the review queue.
    Shows open items with document metadata. No external dependencies.
    Protected by X-Admin-Secret header.
    """
    if not _require_admin_secret():
        return Response(
            "<html><body><h2>403 Forbidden</h2><p>Valid X-Admin-Secret header required.</p></body></html>",
            status=403,
            mimetype="text/html",
        )

    try:
        db: Session = next(get_db())
        open_items = (
            db.query(ExamReviewQueue)
            .filter(ExamReviewQueue.resolution_status == "open")
            .order_by(ExamReviewQueue.created_at.desc())
            .limit(200)
            .all()
        )
        doc_ids = [i.document_id for i in open_items]
        docs = {d.id: d for d in db.query(ExamDocument).filter(ExamDocument.id.in_(doc_ids)).all()}

        total = db.query(ExamReviewQueue).count()
        resolved = db.query(ExamReviewQueue).filter(ExamReviewQueue.resolution_status == "resolved").count()

        rows_html = ""
        for item in open_items:
            doc = docs.get(item.document_id)
            created = _format_dt(item.created_at) or "—"
            filename = (doc.original_filename or "—") if doc else "—"
            source = (doc.ingestion_source or "—") if doc else "—"
            rows_html += f"""
            <tr>
              <td style="font-size:11px;color:#64748b">{item.id[:8]}…</td>
              <td>{item.patient_id}</td>
              <td><code style="font-size:11px">{item.reason_code}</code></td>
              <td style="max-width:300px;font-size:12px">{item.reason_text[:120]}</td>
              <td style="font-size:11px">{filename[:40]}</td>
              <td><span style="background:#f1f5f9;padding:2px 6px;border-radius:4px;font-size:11px">{source}</span></td>
              <td style="font-size:11px;color:#64748b">{created[:19]}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="el">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Autoanosis — Review Queue Admin</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f8fafc; color: #1e293b; padding: 24px; }}
    h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 4px; }}
    .subtitle {{ color: #64748b; font-size: 13px; margin-bottom: 24px; }}
    .stats {{ display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }}
    .stat {{ background: #fff; border-radius: 10px; padding: 16px 24px; border: 1px solid #e2e8f0; min-width: 140px; }}
    .stat-value {{ font-size: 28px; font-weight: 700; color: #3b82f6; }}
    .stat-label {{ font-size: 12px; color: #64748b; margin-top: 2px; }}
    .open-badge {{ color: #f59e0b; }}
    .resolved-badge {{ color: #22c55e; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px; overflow: hidden; border: 1px solid #e2e8f0; }}
    th {{ background: #f1f5f9; padding: 10px 12px; text-align: left; font-size: 12px; font-weight: 600; color: #64748b; border-bottom: 1px solid #e2e8f0; }}
    td {{ padding: 10px 12px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #f8fafc; }}
    .empty {{ text-align: center; padding: 48px; color: #64748b; }}
    .note {{ margin-top: 16px; font-size: 12px; color: #94a3b8; }}
  </style>
</head>
<body>
  <h1>Autoanosis — Review Queue</h1>
  <p class="subtitle">Εξετάσεις που χρειάζονται χειροκίνητο έλεγχο · {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC</p>

  <div class="stats">
    <div class="stat">
      <div class="stat-value open-badge">{len(open_items)}</div>
      <div class="stat-label">Ανοιχτά</div>
    </div>
    <div class="stat">
      <div class="stat-value resolved-badge">{resolved}</div>
      <div class="stat-label">Επιλυμένα</div>
    </div>
    <div class="stat">
      <div class="stat-value">{total}</div>
      <div class="stat-label">Σύνολο</div>
    </div>
  </div>

  {'<table><thead><tr><th>ID</th><th>Patient</th><th>Reason Code</th><th>Reason</th><th>Αρχείο</th><th>Source</th><th>Δημιουργήθηκε</th></tr></thead><tbody>' + rows_html + '</tbody></table>' if open_items else '<div class="empty">✓ Δεν υπάρχουν ανοιχτά items στην ουρά.</div>'}

  <p class="note">
    Για resolve: PATCH /exams/review-queue/{{id}}/resolve με X-Identity-Token (doctor/administrator role απαιτείται).<br>
    JSON endpoints: <a href="/exams/admin/queue">/exams/admin/queue</a> · <a href="/exams/admin/stats">/exams/admin/stats</a>
  </p>
</body>
</html>"""

        return Response(html, status=200, mimetype="text/html")

    except Exception as e:
        logger.error(f"[REVIEW_ADMIN] admin_dashboard error: {e}")
        return Response(
            f"<html><body><h2>500 Internal Server Error</h2><p>{str(e)[:200]}</p></body></html>",
            status=500,
            mimetype="text/html",
        )
