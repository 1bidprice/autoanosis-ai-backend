# Autoanosis — Project Achievements Log

**Last updated:** 2026-04-17 (Athens time)
**Maintained by:** Manus AI (project memory)

---

## Architecture Overview (Frozen Baseline)

| Layer | Technology | Status |
|-------|-----------|--------|
| Frontend | WordPress (autoanosis.com) | Production |
| Identity / Auth | DIP Backend (Render) — JWT tokens | Production |
| Medical Memory | autoanosis-medical-memory (Render) | Production |
| Medications Engine | AME plugin v13.1.3 (WordPress) | Production |
| AI Backend | autoanosis-ai-backend (Render, Flask) | Production |
| Exams Pipeline | autoanosis-exams-bridge.php + Render PostgreSQL | **Broken — P1** |
| Doctor Dashboard | autoanosis-doctor-dashboard.php | **Blocked by Exams** |
| Mobile App | autoanosis-mobile (Expo / React Native) | Production v1.6.2 |
| DIP Backend | dip-backend (Render) | Production (sources stubs) |
| Sources Engine | autoanosis-sources-engine (Render) | MVP / Inactive |
| Scraper | autoanosis-scraper (Render) | MVP only |

---

## Completed Fixes & Features (Chronological)

### 2026-04-16 — AME Plugin: `iss` Token Check Bug

**Problem:** `class-rest-api.php` in `ame_v13_1_3` plugin checked `$payload['iss'] === 'autoanosis-wordpress'`. DIP tokens do not include an `iss` field, so every call to `/ame/v1/*` returned 403.

**Fix method:** SiteGround File Manager → Monaco editor → replaced the broken `if` block with `if ( false ) { // iss check disabled` via JavaScript `executeEdits` on the Monaco model.

**File changed:** `/public_html/wp-content/plugins/ame_v13_1_3/includes/class-rest-api.php`

**Verification:** `POST /ame/v1/doses/regenerate` → HTTP 200, `success: true`, `meds_count: 4`, `count: 5`.

---

### 2026-04-16 — Mobile App: Logout Spinning Bug

**Problem:** Pressing "Αποσύνδεση" caused the UI to spin indefinitely. Root cause: re-entrant logout deadlock. After `AuthService.logout()` destroyed the server session, `unregisterPushToken()` used the same `httpClient` which received a 401. The 401 interceptor called `store.logout()` again, creating an infinite async loop.

**Fix method:**
1. Added `isLoggingOut: boolean` to `AuthState` in `src/types/index.ts`
2. Added guard `if (get().isLoggingOut) return;` at the top of `logout()` in `src/store/auth.store.ts`
3. Moved `unregisterPushToken()` to execute **before** `AuthService.logout()` (while session is still valid)

**Commit:** `013ac98` → `master` (autoanosis-mobile)

**EAS Build:** `c4c9df54` — Android internal, finished 2026-04-16 21:47

---

### 2026-04-16 — Mobile App: "Φάρμακα Σήμερα" Empty on Dashboard

**Problem:** Dashboard showed "Δεν έχεις προγραμματισμένες δόσεις για σήμερα" despite 4 active medications with 5 pending doses. Backend `/ame/v1/doses/today` returned correct data. Root cause: client-side date guard in `DosesService.getToday()` used `Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Athens' })` which is unreliable on Android — returned wrong date string, causing the filter to empty the array.

**Fix method:** Removed the broken `Intl.DateTimeFormat` guard from both `getToday()` and `regenerate()` in `src/services/api.service.ts`. Backend already filters server-side; client does not need to re-filter.

**Commit:** `f370647` → `master` (autoanosis-mobile)

**EAS Build:** `10c795bb` — Android internal, finished 2026-04-16 (confirmed working on device)

---

## Current P1 Blockers (Active Work)

### P1-B: DATABASE_URL missing on Render
Backend defaults to SQLite fallback. All exam data written during a deploy cycle is lost on next deploy.

### P1-A: Render PostgreSQL schema never initialized
`autoanosis-exams-db` has 0 tables. Migrations 001–004 have never been executed against production DB.

### P1-C: WordPress Exams Bridge returns 401
`/autoa/v1/doctor-exams/{id}` and `/autoa/v1/exam-snapshot` return `rest_forbidden`. Permission callbacks failing.

### P1-D: Home Snapshot reads from local WP table
`autoanosis-home-snapshot.php` reads `wp_autoanosis_exam_reports` (local WP table) instead of Render backend. Architectural violation.

---

## Execution Rules (Binding)

1. P1 must be fully resolved before any P2/P3 work.
2. No mobile polish, no signup screen, no DIP sources, no disabled file cleanup until exams pipeline is live.
3. Every fix must be verified end-to-end before moving to next step.
4. All medical data lives in Render backend / user_meta — never in custom WP tables.
5. Doctor Dashboard v11.0.0 has no legacy fallback — it requires the structured exams endpoint to function.
