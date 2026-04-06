<?php
/**
 * Plugin Name: Autoanosis Role Sync Hook
 * Description: Pushes WordPress user roles to the Autoanosis Render backend on every login.
 *              Uses HMAC-SHA256 signature for secure server-to-server communication.
 *              Replaces the old "Autoanosis User Roles API" pull model with a push model
 *              that avoids SiteGround CDN/WAF blocking of inbound Render requests.
 *
 * Version:     1.0.0
 * Author:      Autoanosis Team
 *
 * Security model:
 *   - Payload is signed with HMAC-SHA256 using AUTOA_ROLE_SYNC_SECRET constant.
 *   - Signature covers: timestamp + "." + raw_json_body
 *   - Timestamp is included in both the header and the body for double validation.
 *   - The Render backend verifies the signature and rejects stale timestamps (>60s).
 *   - AUTOA_ROLE_SYNC_SECRET must be defined in wp-config.php and must match
 *     the AUTOA_ROLE_SYNC_SECRET env var on Render.
 *   - AUTOA_RENDER_BACKEND_URL must be defined in wp-config.php.
 *     Example: define('AUTOA_RENDER_BACKEND_URL', 'https://autoanosis-ai-backend.onrender.com');
 *
 * Endpoint called:
 *   POST {AUTOA_RENDER_BACKEND_URL}/internal/role-sync
 *
 * Payload:
 *   { "uid": 42, "roles": ["doctor"], "timestamp": 1712345678 }
 *
 * Headers sent:
 *   Content-Type:    application/json
 *   X-Autoa-Role-TS: <unix_timestamp>
 *   X-Autoa-Role-Sig: <hmac_sha256_hex>
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

/**
 * Hook: fires after a user successfully logs in.
 * Pushes uid + roles to the Render backend with HMAC signature.
 */
add_action( 'wp_login', 'autoa_push_roles_on_login', 10, 2 );

function autoa_push_roles_on_login( $user_login, $user ) {
    // -----------------------------------------------------------------------
    // 1. Validate configuration
    // -----------------------------------------------------------------------
    if ( ! defined( 'AUTOA_ROLE_SYNC_SECRET' ) || empty( AUTOA_ROLE_SYNC_SECRET ) ) {
        error_log( '[AUTOA_ROLE_SYNC] AUTOA_ROLE_SYNC_SECRET is not defined — role push skipped.' );
        return;
    }
    if ( ! defined( 'AUTOA_RENDER_BACKEND_URL' ) || empty( AUTOA_RENDER_BACKEND_URL ) ) {
        error_log( '[AUTOA_ROLE_SYNC] AUTOA_RENDER_BACKEND_URL is not defined — role push skipped.' );
        return;
    }

    // -----------------------------------------------------------------------
    // 2. Build payload
    // -----------------------------------------------------------------------
    $uid       = (int) $user->ID;
    $roles     = array_values( $user->roles );   // re-index → JSON array
    $timestamp = time();

    $payload = wp_json_encode( [
        'uid'       => $uid,
        'roles'     => $roles,
        'timestamp' => $timestamp,
    ] );

    if ( $payload === false ) {
        error_log( '[AUTOA_ROLE_SYNC] Failed to encode payload for uid=' . $uid );
        return;
    }

    // -----------------------------------------------------------------------
    // 3. Compute HMAC-SHA256 signature
    //    Message = timestamp_string + "." + raw_json_body
    // -----------------------------------------------------------------------
    $ts_string = (string) $timestamp;
    $message   = $ts_string . '.' . $payload;
    $signature = hash_hmac( 'sha256', $message, AUTOA_ROLE_SYNC_SECRET );

    // -----------------------------------------------------------------------
    // 4. Send to Render backend (non-blocking: timeout 5s)
    // -----------------------------------------------------------------------
    $endpoint = rtrim( AUTOA_RENDER_BACKEND_URL, '/' ) . '/internal/role-sync';

    $response = wp_remote_post( $endpoint, [
        'method'    => 'POST',
        'timeout'   => 5,
        'blocking'  => false,   // fire-and-forget — do not delay login
        'headers'   => [
            'Content-Type'    => 'application/json',
            'X-Autoa-Role-TS' => $ts_string,
            'X-Autoa-Role-Sig' => $signature,
        ],
        'body'      => $payload,
        'sslverify' => true,
    ] );

    if ( is_wp_error( $response ) ) {
        error_log( '[AUTOA_ROLE_SYNC] Push failed for uid=' . $uid . ': ' . $response->get_error_message() );
    } else {
        error_log( '[AUTOA_ROLE_SYNC] Push sent for uid=' . $uid . ' roles=' . implode( ',', $roles ) );
    }
}
