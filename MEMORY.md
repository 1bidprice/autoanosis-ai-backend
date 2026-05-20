# MEMORY — Autoanosis AI Backend
> Πλήρης καταγραφή αρχιτεκτονικής, αποφάσεων, fixes και γνωστών ζητημάτων.
> **Ενημερώθηκε:** 2026-05-20

---

## 1. Περιβάλλον Deployment

| Παράμετρος | Τιμή |
|---|---|
| **Platform** | Render.com — Python Web Service (ΟΧΙ Docker) |
| **URL** | https://autoanosis-ai-backend.onrender.com |
| **GitHub** | https://github.com/1bidprice/autoanosis-ai-backend |
| **Branch** | `main` |
| **Runtime** | Python 3.11, Gunicorn 2 workers, timeout 300s |
| **Start command** | `gunicorn --timeout 300 --workers 2 --bind 0.0.0.0:$PORT app:app` |

### ⚠️ ΚΡΙΣΙΜΟ: Render τρέχει Python, ΟΧΙ Docker
Το `render.yaml` έχει `env: docker` και `dockerfilePath: ./Dockerfile` αλλά το Render **αγνοεί** αυτή την αλλαγή για υπάρχουσες υπηρεσίες που δημιουργήθηκαν ως Python services. Το `in_docker` endpoint επιστρέφει `false`.

**Συνέπεια:** Το `tesseract` binary δεν είναι διαθέσιμο. Το OCR γίνεται μέσω OpenAI Vision API (βλ. §5).

**Αν χρειαστεί Docker:** Ο χρήστης πρέπει να διαγράψει και να ξαναδημιουργήσει την υπηρεσία στο Render dashboard επιλέγοντας "Docker" ως environment.

---

## 2. Αρχιτεκτονική Συστήματος

```
Android App (Autoanosis)
    ↓ REST API calls
WordPress (autoanosis.com)
    ↓ POST /chat  (HMAC-signed wp_context snapshot)
    ↓ POST /exams/documents  (OCR text από WordPress plugin)
    ↓ POST /medical-documents/upload  (binary PDF upload)
Render Backend (app.py + exams_module/)
    ↓
OpenAI GPT-4o API
    ↓
PostgreSQL (Render managed DB)
```

### Κύρια Endpoints

| Endpoint | Μέθοδος | Σκοπός | Auth |
|---|---|---|---|
| `/chat` | POST | Κύριο chat endpoint | X-Identity-Token (HMAC) |
| `/health` | GET | Health check | — |
| `/exams/documents` | POST | Ingest OCR text από WordPress | X-Proxy-Secret (HMAC) |
| `/exams/documents/ingest-and-normalize` | POST | Ingest + normalize async | X-Proxy-Secret |
| `/medical-documents/upload` | POST | Upload PDF/αρχείο | X-Identity-Token |
| `/medical-documents/list` | GET | Λίστα εγγράφων χρήστη | X-Identity-Token |
| `/medical-documents/<id>/reprocess` | POST | Re-run OCR σε υπάρχον έγγραφο | X-Identity-Token ή X-Admin-Secret |
| `/debug/ocr-check` | GET | Έλεγχος OCR διαθεσιμότητας | X-Admin-Secret |

---

## 3. Authentication

### X-Identity-Token (WordPress → Render)
- HMAC-SHA256 signed token
- Secret: `AUTOANOSIS_IDENTITY_SECRET` (env var)
- Περιέχει: `user_id`, `wp_user_id`, `timestamp`, `role`
- TTL: 300 δευτερόλεπτα

### X-Proxy-Secret / X-Admin-Secret
- Shared secret: `AUTOA_AI_PROXY_SECRET` (env var)
- Χρησιμοποιείται για server-to-server calls (WordPress → Render)
- Χρησιμοποιείται και για admin endpoints (reprocess, debug)

### AUTOA_ROLE_SYNC_SECRET
- Για role sync από WordPress
- TTL: `AUTOA_ROLE_CACHE_TTL` (default 300s)

---

## 4. Βάση Δεδομένων

### Κύριοι Πίνακες

```sql
-- Εξετάσεις (από WordPress OCR)
aa_exam_documents      -- raw OCR blobs
aa_exam_results        -- normalized lab values
aa_exam_reviews        -- review queue

-- Ιατρικά Έγγραφα (PDF uploads)
aa_medical_documents   -- file_data (base64), extracted_text, category
```

### aa_medical_documents schema
```sql
id              UUID PRIMARY KEY
patient_id      INTEGER  -- WordPress user ID
title           TEXT
category        VARCHAR  -- general|medical_opinion|imaging_report|article|insurance|other
document_date   DATE
notes           TEXT
file_data       TEXT     -- base64 encoded file bytes
mime_type       VARCHAR
file_size       INTEGER
extracted_text  TEXT     -- εξαγμένο κείμενο (Vision OCR ή PyMuPDF)
uploaded_at     TIMESTAMP
```

---

## 5. OCR Pipeline — Ιατρικά Έγγραφα

### Τρέχουσα Υλοποίηση (2026-05-20)

**Αρχείο:** `exams_module/api/medical_documents.py`

**Ροή:**
1. `_extract_text_from_bytes()` — κύρια συνάρτηση
2. Πρώτα δοκιμάζει **PyMuPDF** (`fitz`) για PDF με text layer
3. Αν δεν βρει κείμενο → καλεί `_ocr_with_vision()`
4. `_ocr_with_vision()`:
   - Μετατρέπει PDF σελίδες σε JPEG με `pdf2image` (poppler)
   - Στέλνει κάθε σελίδα ως base64 στο **GPT-4o Vision**
   - Max 8 σελίδες, 2000 tokens/σελίδα, 60s timeout/σελίδα
   - Fallback σε `pytesseract` αν OpenAI αποτύχει
5. Αποθηκεύει στο `aa_medical_documents.extracted_text`

### Γιατί Vision API αντί Tesseract
- Το Render Python environment **δεν έχει** `tesseract` binary
- Το `buildCommand` με `apt-get` δεν λειτουργεί στο Render Python
- Το Docker `env` στο render.yaml αγνοείται για υπάρχουσες υπηρεσίες
- GPT-4o Vision: καλύτερη ποιότητα, υποστηρίζει Ελληνικά, χωρίς system dependencies

### Διαθέσιμες Βιβλιοθήκες στο Render Python
| Βιβλιοθήκη | Διαθέσιμη | Σημείωση |
|---|---|---|
| `fitz` (PyMuPDF) | ✅ | PDF text layer extraction |
| `pdf2image` | ✅ | PDF → images (χρειάζεται poppler) |
| `poppler-utils` | ✅ | System binary, pre-installed |
| `pytesseract` | ✅ (Python lib) | Χρειάζεται tesseract binary |
| `tesseract` | ❌ | Binary δεν υπάρχει |
| `openai` | ✅ | Vision OCR |

---

## 6. Chat Endpoint — Context Builder

**Αρχείο:** `app.py` — `build_selective_context()`

### Ενότητες Context (1-10)
1. Βασικά δεδομένα χρήστη
2. Τρέχουσα κατάσταση υγείας
3. Φάρμακα
4. Διαγνώσεις
5. Εξετάσεις (από WordPress)
6. BEST Protocol
7. Ιστορικό
8. Σημειώσεις
9. Τάσεις εβδομάδας
10. **Αρχείο Εγγράφων** (medical_documents από DB)

### ⚠️ ΚΡΙΣΙΜΟ FIX (commit c49dcc5)
Το `wp_context` που έρχεται από WordPress **ποτέ δεν περιέχει** `medical_documents`. Το fix κάνει ανεξάρτητο DB fetch στο `/chat` endpoint:

```python
# app.py — μετά τον εντοπισμό intent
_db = SessionLocal()
_docs = _db.query(MedicalDocument)
         .filter(MedicalDocument.patient_id == int(user_id))
         .order_by(MedicalDocument.uploaded_at.desc())
         .limit(10).all()
wp_context["medical_documents"] = medical_docs_list
```

### Intent Detection
| Intent | Triggers |
|---|---|
| `document_analysis` | "άρθρο", "έγγραφο", "pdf", "ανέβασα", "αρχείο" κ.λπ. |
| `lab_results` | "εξέταση", "αιματολογικές", "τιμές" κ.λπ. |
| `medication` | "φάρμακο", "δόση", "χάπι" κ.λπ. |
| `education` | "τι είναι", "εξήγησε" κ.λπ. |

---

## 7. Exams Pipeline — Εξετάσεις

**Εντελώς ξεχωριστό σύστημα από Medical Documents.**

### Ροή
1. WordPress plugin κάνει OCR στο PDF/εικόνα (στο WordPress server)
2. Στέλνει raw OCR text στο `POST /exams/documents/ingest-and-normalize`
3. Backend normalizer (`normalizer_ai.py`) εξάγει τιμές με GPT-4o
4. Αποθηκεύει στο `aa_exam_results`
5. Εμφανίζεται στο `/chat` context (ενότητα 5)

**Το OCR γίνεται στο WordPress, ΟΧΙ στο backend.**

---

## 8. Admin / Debug Endpoints

### GET /debug/ocr-check
Ελέγχει διαθεσιμότητα OCR libraries. Απαιτεί `X-Admin-Secret`.

Επιστρέφει:
- `tesseract_available` / `tesseract_find`
- `pytesseract_available`
- `pdf2image_available`
- `poppler_available`
- `pymupdf_available`
- `in_docker`
- `PATH`, `TESSDATA_PREFIX`

### POST /medical-documents/<id>/reprocess
Re-runs OCR σε υπάρχον έγγραφο. Χρήσιμο όταν το OCR απέτυχε σιωπηλά κατά το upload.

Auth: `X-Identity-Token` (ιδιοκτήτης) ή `X-Admin-Secret` (admin).

**Χρήση:**
```bash
curl -X POST \
  "https://autoanosis-ai-backend.onrender.com/medical-documents/<doc_id>/reprocess" \
  -H "X-Admin-Secret: <AUTOA_AI_PROXY_SECRET>"
```

---

## 9. Γνωστά Ζητήματα & Περιορισμοί

### Render Free Tier
- **Cold start:** ~20-30 δευτερόλεπτα μετά από αδράνεια
- **Gunicorn timeout:** 300s — αρκετό για Vision OCR (8 σελίδες ~90s)
- **Memory:** 512MB — επαρκές για pdf2image με DPI 200

### Vision OCR Κόστος
- ~$0.01-0.05 ανά σελίδα (GPT-4o Vision, high detail)
- Max 8 σελίδες ανά PDF
- Κόστος ανά upload: ~$0.08-0.40

### PDF με Text Layer
- Αν το PDF έχει selectable text (όχι scanned), το PyMuPDF το εξάγει δωρεάν (0 API calls)
- Vision OCR καλείται μόνο για scanned/image-based PDFs

### Render Python buildCommand
- `apt-get` ΔΕΝ λειτουργεί στο Render Python buildCommand
- Μόνο `pip install` είναι διαθέσιμο
- Για system binaries (tesseract) χρειάζεται Docker service

---

## 10. Environment Variables (Render)

| Variable | Σκοπός |
|---|---|
| `OPENAI_API_KEY` | OpenAI API (chat + Vision OCR) |
| `DATABASE_URL` | PostgreSQL connection string |
| `AUTOA_AI_PROXY_SECRET` | HMAC secret για WP→Render calls + admin endpoints |
| `AUTOANOSIS_IDENTITY_SECRET` | HMAC secret για identity tokens |
| `AUTOA_ROLE_SYNC_SECRET` | HMAC secret για role sync |
| `AUTOA_ROLE_CACHE_TTL` | TTL για role cache (default: 300) |
| `PYTHON_VERSION` | 3.11.0 |

---

## 11. Commit History (Σημαντικά)

| Commit | Ημερομηνία | Περιγραφή |
|---|---|---|
| `3789674` | 2026-05-20 | **feat(ocr):** Vision API OCR αντί tesseract |
| `ecbfec3` | 2026-05-20 | fix(render): buildCommand για tesseract (απέτυχε) |
| `8af7514` | 2026-05-20 | **feat:** /reprocess endpoint για re-OCR |
| `c49dcc5` | 2026-05-20 | **fix(chat):** inject medical_documents από DB στο context |
| `4156178` | 2026-05-20 | feat: Docker + tesseract (δεν εφαρμόστηκε λόγω Render) |
| `e34269b` | 2026-05-20 | fix: auto-detect category + αρθρο intent ambiguity |
| `e0f0809` | 2026-05-20 | feat: document_analysis intent mode |
| `4275515` | 2026-05-20 | feat: text extraction + AI context section 10 |
| `cfb7943` | 2026-05-20 | feat: medical_documents στο AI context |

---

## 12. Αρχεία Κώδικα — Χάρτης

```
app.py                                    ← Κύριο Flask app, /chat, context builder
exams_module/
  api/
    medical_documents.py                  ← Upload, OCR, reprocess, list endpoints
    exams_flask.py                        ← Exams ingestion + normalizer endpoints
  models/
    medical_document_model.py             ← SQLAlchemy model για aa_medical_documents
    exam_models.py                        ← SQLAlchemy models για exams
  services/
    normalizer_ai.py                      ← GPT-4o lab result extraction
    normalizer.py                         ← Rule-based normalizer
    exam_service.py                       ← Exam business logic
  db/
    database.py                           ← SessionLocal, engine, Base
Dockerfile                                ← Docker image (ΔΕΝ χρησιμοποιείται από Render)
render.yaml                               ← Render config (env: python, αγνοεί docker)
requirements.txt                          ← Python dependencies
```

---

## 13. Τεστ Επαλήθευσης

### Έλεγχος OCR environment
```bash
curl "https://autoanosis-ai-backend.onrender.com/debug/ocr-check" \
  -H "X-Admin-Secret: <AUTOA_AI_PROXY_SECRET>"
```

### Re-OCR υπάρχοντος εγγράφου
```bash
curl -X POST \
  "https://autoanosis-ai-backend.onrender.com/medical-documents/<doc_id>/reprocess" \
  -H "X-Admin-Secret: <AUTOA_AI_PROXY_SECRET>"
```

### Health check
```bash
curl "https://autoanosis-ai-backend.onrender.com/health"
```

---

*Τελευταία ενημέρωση: 2026-05-20 | Συντάκτης: Manus AI*
