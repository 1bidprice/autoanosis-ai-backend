<?php
/**
 * Plugin Name:  Autoanosis Exams Bridge
 * Plugin URI:   https://autoanosis.com
 * Description:  Exams Ingestion + Normalizer bridge for the Autoanosis platform.
 *               Connects WordPress OCR uploads to the Render backend Exams subsystem,
 *               exposes structured exam data to the Doctor Dashboard, and enforces the
 *               rule that raw blobs / OCR text / failed extracts are NEVER used as
 *               source of truth.
 * Version:      1.0.0
 * Author:       Autoanosis Dev
 * Requires PHP: 7.4
 * Text Domain:  autoanosis-exams
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

if ( ! defined( 'AUTOANOSIS_RENDER_BASE' ) ) {
    define( 'AUTOANOSIS_RENDER_BASE', 'https://autoanosis-ai-backend.onrender.com' );
}

// ---------------------------------------------------------------------------
// Helper: build a server-to-server proxy signature for the Render backend
// This mirrors the existing AUTOA_AI_PROXY_SECRET mechanism used by chat-proxy.
// ---------------------------------------------------------------------------

function autoanosis_exams_build_proxy_headers( $patient_id ) {
    $secret = defined( 'AUTOA_AI_PROXY_SECRET' ) ? AUTOA_AI_PROXY_SECRET
            : ( defined( 'AUTOANOSIS_PROXY_SECRET' ) ? AUTOANOSIS_PROXY_SECRET : '' );

    $ts    = time();
    $nonce = wp_generate_password( 16, false );

    $headers = array(
        'Content-Type'       => 'application/json',
        'X-Autoa-Proxy-TS'   => (string) $ts,
        'X-Autoa-Proxy-Nonce'=> $nonce,
    );

    if ( $secret ) {
        $canonical = $ts . '.' . $nonce . '.' . intval( $patient_id );
        $sig = hash_hmac( 'sha256', $canonical, $secret );
        $headers['X-Autoa-Proxy-Sig'] = $sig;
    }

    return $headers;
}

// ---------------------------------------------------------------------------
// Helper: fetch structured exam snapshot for a patient
// Called by helpers_v6.0.0.php snapshot builder to replace raw test_results.
// Returns array|WP_Error
// ---------------------------------------------------------------------------

function autoanosis_exams_fetch_structured_snapshot( $patient_id ) {
    $url     = rtrim( AUTOANOSIS_RENDER_BASE, '/' ) . '/exams/patients/' . intval( $patient_id ) . '/snapshot';
    $headers = autoanosis_exams_build_proxy_headers( $patient_id );

    $response = wp_remote_get( $url, array(
        'headers' => $headers,
        'timeout' => 10,
        'sslverify' => true,
    ) );

    if ( is_wp_error( $response ) ) {
        error_log( '[AUTOANOSIS EXAMS] snapshot fetch error: ' . $response->get_error_message() );
        return $response;
    }

    $code = wp_remote_retrieve_response_code( $response );
    $body = wp_remote_retrieve_body( $response );

    if ( $code !== 200 ) {
        error_log( '[AUTOANOSIS EXAMS] snapshot HTTP ' . $code . ' for patient ' . $patient_id );
        return new WP_Error( 'exams_api_error', 'Exams API returned HTTP ' . $code );
    }

    $data = json_decode( $body, true );
    if ( ! is_array( $data ) ) {
        return new WP_Error( 'exams_invalid_json', 'Invalid JSON from Exams API' );
    }

    return $data;
}

// ---------------------------------------------------------------------------
// Helper: fetch full structured reports for a patient (Doctor Dashboard)
// Returns array|WP_Error
// ---------------------------------------------------------------------------

function autoanosis_exams_fetch_structured_reports( $patient_id ) {
    $url     = rtrim( AUTOANOSIS_RENDER_BASE, '/' ) . '/exams/patients/' . intval( $patient_id ) . '/reports';
    $headers = autoanosis_exams_build_proxy_headers( $patient_id );

    $response = wp_remote_get( $url, array(
        'headers' => $headers,
        'timeout' => 15,
        'sslverify' => true,
    ) );

    if ( is_wp_error( $response ) ) {
        error_log( '[AUTOANOSIS EXAMS] reports fetch error: ' . $response->get_error_message() );
        return $response;
    }

    $code = wp_remote_retrieve_response_code( $response );
    $body = wp_remote_retrieve_body( $response );

    if ( $code !== 200 ) {
        error_log( '[AUTOANOSIS EXAMS] reports HTTP ' . $code . ' for patient ' . $patient_id );
        return new WP_Error( 'exams_api_error', 'Exams API returned HTTP ' . $code );
    }

    $data = json_decode( $body, true );
    if ( ! is_array( $data ) ) {
        return new WP_Error( 'exams_invalid_json', 'Invalid JSON from Exams API' );
    }

    return $data;
}

// ---------------------------------------------------------------------------
// Helper: ingest OCR text into the Exams subsystem
// Called after a successful OCR extraction (from ocr_endpoint.py bridge or
// the existing file-ocr.php upload flow).
// Returns array|WP_Error
// ---------------------------------------------------------------------------

function autoanosis_exams_ingest_ocr( $patient_id, $identity_token, $sha256, $raw_text, $args = array() ) {
    $url = rtrim( AUTOANOSIS_RENDER_BASE, '/' ) . '/exams/ingest-from-ocr';

    $body = array(
        'sha256'            => sanitize_text_field( $sha256 ),
        'raw_text'          => $raw_text,
        'source_type'       => isset( $args['source_type'] )       ? $args['source_type']       : 'upload',
        'original_filename' => isset( $args['original_filename'] ) ? $args['original_filename'] : null,
        'mime_type'         => isset( $args['mime_type'] )         ? $args['mime_type']         : null,
        'storage_url'       => isset( $args['storage_url'] )       ? $args['storage_url']       : null,
    );

    $response = wp_remote_post( $url, array(
        'headers' => array(
            'Content-Type'    => 'application/json',
            'X-Identity-Token'=> $identity_token,
        ),
        'body'    => wp_json_encode( $body ),
        'timeout' => 30,
        'sslverify' => true,
    ) );

    if ( is_wp_error( $response ) ) {
        error_log( '[AUTOANOSIS EXAMS] ingest error: ' . $response->get_error_message() );
        return $response;
    }

    $code = wp_remote_retrieve_response_code( $response );
    $resp_body = wp_remote_retrieve_body( $response );
    $data = json_decode( $resp_body, true );

    // Accept 201 (sync) or 202 (async background normalization)
    if ( $code !== 201 && $code !== 202 ) {
        $detail = is_array( $data ) ? ( $data['detail'] ?? $data['error'] ?? $resp_body ) : $resp_body;
        error_log( '[AUTOANOSIS EXAMS] ingest HTTP ' . $code . ': ' . $detail );
        return new WP_Error( 'exams_ingest_error', 'Exams ingest returned HTTP ' . $code . ': ' . $detail );
    }

    return $data;
}

// ---------------------------------------------------------------------------
// REST: GET /wp-json/autoa/v1/doctor-exams/<patient_id>
// Doctor Dashboard endpoint — returns ONLY structured, normalised exam reports.
// NEVER exposes raw blobs, OCR text or failed extracts.
// ---------------------------------------------------------------------------

add_action( 'rest_api_init', function () {

    // Doctor Dashboard: structured reports
    register_rest_route( 'autoa/v1', '/doctor-exams/(?P<patient_id>\d+)', array(
        'methods'             => 'GET',
        'callback'            => 'autoanosis_exams_rest_doctor_reports',
        'permission_callback' => function () { return is_user_logged_in(); },
        'args'                => array(
            'patient_id' => array(
                'required'          => true,
                'validate_callback' => function ( $v ) { return is_numeric( $v ) && intval( $v ) > 0; },
                'sanitize_callback' => 'absint',
            ),
        ),
    ) );

    // Patient self-service: structured snapshot (for AI context enrichment)
    register_rest_route( 'autoa/v1', '/exam-snapshot', array(
        'methods'             => 'GET',
        'callback'            => 'autoanosis_exams_rest_patient_snapshot',
        'permission_callback' => function () { return is_user_logged_in(); },
    ) );

    // Patient self-service: ingest OCR text
    register_rest_route( 'autoa/v1', '/exam-ingest', array(
        'methods'             => 'POST',
        'callback'            => 'autoanosis_exams_rest_ingest',
        'permission_callback' => function () { return is_user_logged_in(); },
    ) );

    // Doctor / admin: review queue
    register_rest_route( 'autoa/v1', '/exam-review-queue', array(
        'methods'             => 'GET',
        'callback'            => 'autoanosis_exams_rest_review_queue',
        'permission_callback' => function () {
            return current_user_can( 'manage_options' ) || current_user_can( 'edit_posts' );
        },
    ) );

} );

// ---------------------------------------------------------------------------
// Callback: GET /wp-json/autoa/v1/doctor-exams/<patient_id>
// ---------------------------------------------------------------------------

function autoanosis_exams_rest_doctor_reports( WP_REST_Request $request ) {
    $patient_id = intval( $request['patient_id'] );

    // Access control: admin / editor can view any patient; otherwise own data only
    $current_uid = get_current_user_id();
    $can_view_all = current_user_can( 'manage_options' ) || current_user_can( 'edit_posts' );
    if ( ! $can_view_all && $current_uid !== $patient_id ) {
        return new WP_REST_Response( array( 'error' => 'forbidden' ), 403 );
    }

    $reports = autoanosis_exams_fetch_structured_reports( $patient_id );

    if ( is_wp_error( $reports ) ) {
        return new WP_REST_Response( array(
            'error'   => $reports->get_error_code(),
            'message' => $reports->get_error_message(),
        ), 502 );
    }

    // Enforce: NEVER expose raw_extraction_json, ocr_text, or any blob field
    if ( isset( $reports['reports'] ) && is_array( $reports['reports'] ) ) {
        foreach ( $reports['reports'] as &$r ) {
            unset( $r['raw_extraction_json'], $r['ocr_text'], $r['parsing_errors'] );
        }
        unset( $r );
    }

    return new WP_REST_Response( $reports, 200 );
}

// ---------------------------------------------------------------------------
// Callback: GET /wp-json/autoa/v1/exam-snapshot
// ---------------------------------------------------------------------------

function autoanosis_exams_rest_patient_snapshot( WP_REST_Request $request ) {
    $user_id = get_current_user_id();
    if ( ! $user_id ) {
        return new WP_REST_Response( array( 'error' => 'not_logged_in' ), 401 );
    }

    $snapshot = autoanosis_exams_fetch_structured_snapshot( $user_id );

    if ( is_wp_error( $snapshot ) ) {
        return new WP_REST_Response( array(
            'error'   => $snapshot->get_error_code(),
            'message' => $snapshot->get_error_message(),
        ), 502 );
    }

    return new WP_REST_Response( $snapshot, 200 );
}

// ---------------------------------------------------------------------------
// Callback: POST /wp-json/autoa/v1/exam-ingest
// Accepts: { sha256, raw_text, source_type?, original_filename?, mime_type? }
// Requires: logged-in user + valid identity_token in body or header
// ---------------------------------------------------------------------------

function autoanosis_exams_rest_ingest( WP_REST_Request $request ) {
    $user_id = get_current_user_id();
    if ( ! $user_id ) {
        return new WP_REST_Response( array( 'error' => 'not_logged_in' ), 401 );
    }

    $body = $request->get_json_params();
    if ( empty( $body ) ) {
        return new WP_REST_Response( array( 'error' => 'missing_body' ), 400 );
    }

    $sha256   = sanitize_text_field( $body['sha256']   ?? '' );
    $raw_text = $body['raw_text'] ?? '';

    if ( empty( $sha256 ) || empty( $raw_text ) ) {
        return new WP_REST_Response( array( 'error' => 'missing_fields', 'fields' => array( 'sha256', 'raw_text' ) ), 400 );
    }

    // Retrieve identity token (body or Authorization header)
    $identity_token = $body['identity_token'] ?? '';
    if ( empty( $identity_token ) ) {
        $auth_header = $request->get_header( 'X-Identity-Token' );
        if ( $auth_header ) {
            $identity_token = $auth_header;
        }
    }

    if ( empty( $identity_token ) ) {
        return new WP_REST_Response( array( 'error' => 'missing_identity_token' ), 401 );
    }

    $result = autoanosis_exams_ingest_ocr(
        $user_id,
        $identity_token,
        $sha256,
        $raw_text,
        array(
            'source_type'       => sanitize_text_field( $body['source_type']       ?? 'upload' ),
            'original_filename' => sanitize_text_field( $body['original_filename'] ?? '' ),
            'mime_type'         => sanitize_text_field( $body['mime_type']         ?? '' ),
            'storage_url'       => esc_url_raw( $body['storage_url']               ?? '' ),
        )
    );

    if ( is_wp_error( $result ) ) {
        return new WP_REST_Response( array(
            'error'   => $result->get_error_code(),
            'message' => $result->get_error_message(),
        ), 502 );
    }

    return new WP_REST_Response( $result, 201 );
}

// ---------------------------------------------------------------------------
// Callback: GET /wp-json/autoa/v1/exam-review-queue
// ---------------------------------------------------------------------------

function autoanosis_exams_rest_review_queue( WP_REST_Request $request ) {
    $url     = rtrim( AUTOANOSIS_RENDER_BASE, '/' ) . '/exams/review-queue';
    $headers = autoanosis_exams_build_proxy_headers( 0 );

    // Review queue uses identity token of the requesting admin
    $identity_token = $request->get_header( 'X-Identity-Token' );
    if ( $identity_token ) {
        $headers['X-Identity-Token'] = $identity_token;
    }

    $response = wp_remote_get( $url, array(
        'headers' => $headers,
        'timeout' => 15,
        'sslverify' => true,
    ) );

    if ( is_wp_error( $response ) ) {
        return new WP_REST_Response( array(
            'error'   => 'backend_error',
            'message' => $response->get_error_message(),
        ), 502 );
    }

    $code = wp_remote_retrieve_response_code( $response );
    $body = wp_remote_retrieve_body( $response );
    $data = json_decode( $body, true );

    if ( $code !== 200 ) {
        return new WP_REST_Response( array(
            'error'   => 'exams_api_error',
            'message' => 'Exams API returned HTTP ' . $code,
        ), $code );
    }

    return new WP_REST_Response( $data, 200 );
}

// ---------------------------------------------------------------------------
// Hook into OCR upload flow
// When the existing OCR endpoint (ocr_endpoint.py) stores a result via WP REST,
// automatically forward the extracted text to the Exams Normalizer.
// This hook fires on the `autoanosis_ocr_complete` action, which must be
// triggered by the OCR upload handler after a successful extraction.
//
// Expected action signature:
//   do_action( 'autoanosis_ocr_complete', $user_id, $identity_token, $sha256, $ocr_text, $filename, $mime_type );
// ---------------------------------------------------------------------------

add_action( 'autoanosis_ocr_complete', function ( $user_id, $identity_token, $sha256, $ocr_text, $filename = '', $mime_type = '' ) {
    if ( empty( $sha256 ) || empty( $ocr_text ) ) {
        error_log( '[AUTOANOSIS EXAMS] autoanosis_ocr_complete: missing sha256 or ocr_text — skipping ingest' );
        return;
    }

    $result = autoanosis_exams_ingest_ocr(
        intval( $user_id ),
        $identity_token,
        $sha256,
        $ocr_text,
        array(
            'source_type'       => 'ocr_upload',
            'original_filename' => $filename,
            'mime_type'         => $mime_type,
        )
    );

    if ( is_wp_error( $result ) ) {
        error_log( '[AUTOANOSIS EXAMS] Auto-ingest failed for user ' . $user_id . ': ' . $result->get_error_message() );
    } else {
        $norm_status = $result['normalization_status'] ?? 'unknown';
        $review      = $result['review_required']      ?? false;
        error_log(
            '[AUTOANOSIS EXAMS] Auto-ingest OK for user ' . $user_id .
            ' | doc=' . ( $result['document_id'] ?? '?' ) .
            ' | status=' . $norm_status .
            ' | review=' . ( $review ? 'YES' : 'NO' )
        );
    }
}, 10, 6 );
