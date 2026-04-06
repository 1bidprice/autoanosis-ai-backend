<?php
/**
 * Plugin Name: Autoanosis Home Snapshot
 * Plugin URI:  https://autoanosis.com
 * Description: Provides the GET /autoa/v1/home-snapshot endpoint for the Autoanosis mobile app
 *              Home / Dashboard 2.0 screen. Strictly read-only aggregator — no writes,
 *              no side effects, no AI-context reuse, no mutation of existing flows.
 *
 * Endpoint:    GET /wp-json/autoa/v1/home-snapshot
 * Auth:        Requires logged-in WordPress session (cookie) or identity_token header.
 *
 * Response contract:
 * {
 *   "today_checkin": {
 *     "date":          "YYYY-MM-DD",
 *     "pain_level":    0-10 | null,
 *     "fatigue_level": 0-10 | null,
 *     "energy_level":  0-10 | null,
 *     "mood_level":    0-10 | null,
 *     "notes":         string | null
 *   } | null,
 *
 *   "weekly_stats": {
 *     "days_with_checkin": 0-7,
 *     "avg_pain":          float | null,
 *     "avg_fatigue":       float | null,
 *     "avg_energy":        float | null,
 *     "avg_mood":          float | null,
 *     "checkin_dates":     ["YYYY-MM-DD", ...]   // up to 7 entries
 *   },
 *
 *   "latest_updates": [   // max 2 items, sorted newest-first
 *     {
 *       "type":    "exam_report" | "best_protocol",
 *       "title":   string,
 *       "date":    "YYYY-MM-DD" | null,
 *       "exam_id": string | null   // only for type=exam_report
 *     }
 *   ]
 * }
 *
 * Empty-state contract:
 *   today_checkin  → null   (no check-in today)
 *   weekly_stats   → { days_with_checkin: 0, avg_*: null, checkin_dates: [] }
 *   latest_updates → []     (no recent updates)
 *
 * Version:     1.0.0
 * Author:      Autoanosis
 */

defined( 'ABSPATH' ) || exit;

// ─── Register REST route ──────────────────────────────────────────────────────

add_action( 'rest_api_init', function () {
    register_rest_route( 'autoa/v1', '/home-snapshot', array(
        'methods'             => 'GET',
        'permission_callback' => 'autoa_home_snapshot_auth',
        'callback'            => 'autoa_home_snapshot_handler',
    ) );
} );

// ─── Auth callback ────────────────────────────────────────────────────────────

/**
 * Accepts:
 *   1. Standard WordPress cookie session (is_user_logged_in).
 *   2. X-Identity-Token header (same HMAC format used by the mobile app).
 *
 * Returns true and sets the current user if auth succeeds.
 * Returns WP_Error on failure.
 */
function autoa_home_snapshot_auth( WP_REST_Request $request ): bool|WP_Error {

    // Path 1 — cookie session (web / same-domain)
    if ( is_user_logged_in() ) {
        return true;
    }

    // Path 2 — X-Identity-Token (mobile app)
    $token = trim( $request->get_header( 'X-Identity-Token' ) ?? '' );
    if ( empty( $token ) ) {
        return new WP_Error( 'rest_forbidden', 'Authentication required.', array( 'status' => 401 ) );
    }

    $user_id = autoa_home_snapshot_verify_token( $token );
    if ( ! $user_id ) {
        return new WP_Error( 'rest_forbidden', 'Invalid or expired identity token.', array( 'status' => 401 ) );
    }

    // Temporarily set the current user so get_current_user_id() works in the handler
    wp_set_current_user( $user_id );
    return true;
}

/**
 * Verifies the HMAC identity token produced by /autoa/v1/token.
 * Token format: Base64(JSON payload) . Base64(HMAC-SHA256 signature)
 *
 * @param  string   $token
 * @return int|null Verified user_id, or null on failure.
 */
function autoa_home_snapshot_verify_token( string $token ): ?int {

    $parts = explode( '.', $token );
    if ( count( $parts ) !== 2 ) {
        return null;
    }

    [ $payload_b64, $sig_b64 ] = $parts;

    // Decode payload
    $json = base64_decode( $payload_b64, true );
    if ( $json === false ) {
        return null;
    }

    $payload = json_decode( $json, true );
    if ( ! is_array( $payload ) ) {
        return null;
    }

    // Verify expiry
    if ( empty( $payload['exp'] ) || time() > (int) $payload['exp'] ) {
        return null;
    }

    // Verify issuer
    if ( ( $payload['iss'] ?? '' ) !== 'autoanosis-wordpress' ) {
        return null;
    }

    // Verify HMAC signature
    $secret = defined( 'AUTOANOSIS_IDENTITY_SECRET' ) ? AUTOANOSIS_IDENTITY_SECRET : '';
    if ( empty( $secret ) ) {
        return null;
    }

    $expected_sig_raw = hash_hmac( 'sha256', $payload_b64, $secret, true );
    $expected_sig_b64 = base64_encode( $expected_sig_raw );

    if ( ! hash_equals( $expected_sig_b64, $sig_b64 ) ) {
        return null;
    }

    $uid = (int) ( $payload['uid'] ?? 0 );
    return $uid > 0 ? $uid : null;
}

// ─── Main handler ─────────────────────────────────────────────────────────────

/**
 * Aggregates today_checkin, weekly_stats, and latest_updates for the
 * authenticated user. Strictly read-only — no writes or side effects.
 *
 * @param  WP_REST_Request $request
 * @return WP_REST_Response
 */
function autoa_home_snapshot_handler( WP_REST_Request $request ): WP_REST_Response {

    global $wpdb;

    $user_id = get_current_user_id();
    if ( ! $user_id ) {
        return new WP_REST_Response( array( 'error' => 'unauthenticated' ), 401 );
    }

    $today = gmdate( 'Y-m-d' );

    // ── 1. today_checkin ──────────────────────────────────────────────────────
    $today_checkin = autoa_home_snapshot_today_checkin( $wpdb, $user_id, $today );

    // ── 2. weekly_stats ───────────────────────────────────────────────────────
    $weekly_stats = autoa_home_snapshot_weekly_stats( $wpdb, $user_id, $today );

    // ── 3. latest_updates (max 2) ─────────────────────────────────────────────
    $latest_updates = autoa_home_snapshot_latest_updates( $wpdb, $user_id );

    $response = array(
        'today_checkin'  => $today_checkin,
        'weekly_stats'   => $weekly_stats,
        'latest_updates' => $latest_updates,
    );

    return new WP_REST_Response( $response, 200 );
}

// ─── Section builders ─────────────────────────────────────────────────────────

/**
 * Returns today's check-in row, or null if none exists.
 */
function autoa_home_snapshot_today_checkin( wpdb $wpdb, int $user_id, string $today ): ?array {

    $table = $wpdb->prefix . 'autoa_daily_checkins';

    // Guard: table may not exist on all environments
    if ( $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $table ) ) !== $table ) {
        return null;
    }

    $row = $wpdb->get_row(
        $wpdb->prepare(
            "SELECT checkin_date, pain_level, fatigue_level, energy_level, mood_level, notes
             FROM `{$table}`
             WHERE user_id = %d
               AND checkin_date = %s
             LIMIT 1",
            $user_id,
            $today
        ),
        ARRAY_A
    );

    if ( empty( $row ) ) {
        return null;
    }

    return array(
        'date'          => $row['checkin_date'],
        'pain_level'    => isset( $row['pain_level'] )    ? (int) $row['pain_level']    : null,
        'fatigue_level' => isset( $row['fatigue_level'] ) ? (int) $row['fatigue_level'] : null,
        'energy_level'  => isset( $row['energy_level'] )  ? (int) $row['energy_level']  : null,
        'mood_level'    => isset( $row['mood_level'] )    ? (int) $row['mood_level']    : null,
        'notes'         => ! empty( $row['notes'] ) ? (string) $row['notes'] : null,
    );
}

/**
 * Returns aggregated stats for the last 7 days (including today).
 * Empty state: { days_with_checkin: 0, avg_*: null, checkin_dates: [] }
 */
function autoa_home_snapshot_weekly_stats( wpdb $wpdb, int $user_id, string $today ): array {

    $empty = array(
        'days_with_checkin' => 0,
        'avg_pain'          => null,
        'avg_fatigue'       => null,
        'avg_energy'        => null,
        'avg_mood'          => null,
        'checkin_dates'     => array(),
    );

    $table = $wpdb->prefix . 'autoa_daily_checkins';
    if ( $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $table ) ) !== $table ) {
        return $empty;
    }

    // 7-day window: today inclusive, going back 6 days
    $week_start = gmdate( 'Y-m-d', strtotime( $today . ' -6 days' ) );

    $rows = $wpdb->get_results(
        $wpdb->prepare(
            "SELECT checkin_date, pain_level, fatigue_level, energy_level, mood_level
             FROM `{$table}`
             WHERE user_id = %d
               AND checkin_date BETWEEN %s AND %s
             ORDER BY checkin_date ASC",
            $user_id,
            $week_start,
            $today
        ),
        ARRAY_A
    );

    if ( empty( $rows ) ) {
        return $empty;
    }

    $dates        = array();
    $pain_vals    = array();
    $fatigue_vals = array();
    $energy_vals  = array();
    $mood_vals    = array();

    foreach ( $rows as $r ) {
        $dates[] = $r['checkin_date'];
        if ( $r['pain_level']    !== null ) { $pain_vals[]    = (int) $r['pain_level'];    }
        if ( $r['fatigue_level'] !== null ) { $fatigue_vals[] = (int) $r['fatigue_level']; }
        if ( $r['energy_level']  !== null ) { $energy_vals[]  = (int) $r['energy_level'];  }
        if ( $r['mood_level']    !== null ) { $mood_vals[]    = (int) $r['mood_level'];    }
    }

    $avg = static function ( array $vals ): ?float {
        if ( empty( $vals ) ) {
            return null;
        }
        return round( array_sum( $vals ) / count( $vals ), 1 );
    };

    return array(
        'days_with_checkin' => count( $rows ),
        'avg_pain'          => $avg( $pain_vals ),
        'avg_fatigue'       => $avg( $fatigue_vals ),
        'avg_energy'        => $avg( $energy_vals ),
        'avg_mood'          => $avg( $mood_vals ),
        'checkin_dates'     => $dates,
    );
}

/**
 * Returns at most 2 latest health updates, sorted newest-first.
 * Sources: (a) latest structured exam report from wp_autoanosis_exam_reports,
 *          (b) latest BEST protocol entry from user_meta.
 *
 * Empty state: []
 */
function autoa_home_snapshot_latest_updates( wpdb $wpdb, int $user_id ): array {

    $updates = array();

    // ── Source A: latest exam report (from wp_autoanosis_exam_reports if it exists) ──
    $exam_table = $wpdb->prefix . 'autoanosis_exam_reports';
    if ( $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $exam_table ) ) === $exam_table ) {
        $exam_row = $wpdb->get_row(
            $wpdb->prepare(
                "SELECT id, exam_type, exam_category, performed_at
                 FROM `{$exam_table}`
                 WHERE patient_id = %d
                   AND status = 'active'
                   AND normalization_status IN ('auto_verified','manually_corrected','published','needs_review')
                 ORDER BY performed_at DESC
                 LIMIT 1",
                $user_id
            ),
            ARRAY_A
        );

        if ( ! empty( $exam_row ) ) {
            $exam_date = null;
            if ( ! empty( $exam_row['performed_at'] ) ) {
                // performed_at may be a full datetime; extract date portion only
                $exam_date = substr( $exam_row['performed_at'], 0, 10 );
            }

            $exam_label = ! empty( $exam_row['exam_type'] )
                ? ucfirst( str_replace( '_', ' ', (string) $exam_row['exam_type'] ) )
                : 'Εξέταση';

            $updates[] = array(
                'type'    => 'exam_report',
                'title'   => $exam_label,
                'date'    => $exam_date,
                'exam_id' => (string) $exam_row['id'],
            );
        }
    }

    // ── Source B: latest BEST protocol entry from user_meta ──
    $best = get_user_meta( $user_id, 'autoanosis_best_protocol_last', true );

    // Fallback meta keys (legacy)
    if ( empty( $best ) ) {
        $best = get_user_meta( $user_id, 'autoanosis_medical_snapshot_last', true );
    }
    if ( empty( $best ) ) {
        $best = get_user_meta( $user_id, 'autoanosis_medical_snapshot_last_v2', true );
    }

    // Unwrap wrapper arrays produced by some plugin versions
    if ( is_array( $best ) && isset( $best['payload'] ) && is_array( $best['payload'] ) ) {
        $best = $best['payload'];
    }

    // Defensive unserialize for edge cases
    if ( is_string( $best ) ) {
        $tmp = @unserialize( $best );
        if ( $tmp !== false || $best === 'b:0;' ) {
            $best = $tmp;
        }
    }

    if ( is_array( $best ) && ! empty( $best ) ) {
        $best_date = null;

        // Prefer saved_at timestamp, then visit_date
        if ( ! empty( $best['saved_at'] ) ) {
            $best_date = substr( (string) $best['saved_at'], 0, 10 );
        } elseif ( ! empty( $best['ts'] ) ) {
            $best_date = substr( (string) $best['ts'], 0, 10 );
        } elseif ( ! empty( $best['visit_date'] ) ) {
            $best_date = substr( (string) $best['visit_date'], 0, 10 );
        }

        $updates[] = array(
            'type'    => 'best_protocol',
            'title'   => 'Ενημέρωση Ιατρικού Προφίλ',
            'date'    => $best_date,
            'exam_id' => null,
        );
    }

    // Sort all updates newest-first (nulls go last)
    usort( $updates, static function ( array $a, array $b ): int {
        $da = $a['date'] ?? '';
        $db = $b['date'] ?? '';
        if ( $da === $db ) {
            return 0;
        }
        if ( empty( $da ) ) {
            return 1;
        }
        if ( empty( $db ) ) {
            return -1;
        }
        return strcmp( $db, $da ); // descending
    } );

    // Cap at 2 items as per spec
    return array_slice( $updates, 0, 2 );
}
