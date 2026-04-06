<?php
/**
 * Plugin Name: Autoanosis User Roles API
 * Description: Internal REST endpoint that returns the WordPress roles for a given user ID.
 *              Used by the Autoanosis AI backend to perform role-based access control
 *              on doctor/admin-only endpoints without embedding roles in the identity token.
 * Version:     1.0.0
 * Author:      Autoanosis Team
 *
 * Security model:
 *   - Endpoint is NOT publicly accessible.
 *   - Every request MUST carry the header:  X-API-Key: <AUTOA_INTERNAL_API_KEY>
 *   - The key is defined as a PHP constant in wp-config.php:
 *       define('AUTOA_INTERNAL_API_KEY', 'your-secret-key-here');
 *   - The same value must be set as WORDPRESS_API_KEY in the Render environment.
 *   - Requests without a valid key receive HTTP 403.
 *   - The response contains ONLY the roles array — no other user data is returned.
 *
 * Endpoint:
 *   GET /wp-json/autoa/v1/user-roles/{user_id}
 *
 * Request headers:
 *   X-API-Key: <AUTOA_INTERNAL_API_KEY>
 *
 * Response (200 OK):
 *   { "user_id": 42, "roles": ["doctor"] }
 *
 * Error responses:
 *   403  { "code": "forbidden",   "message": "Invalid or missing API key." }
 *   404  { "code": "not_found",   "message": "User not found." }
 *   400  { "code": "bad_request", "message": "Invalid user_id." }
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

add_action( 'rest_api_init', 'autoa_register_user_roles_endpoint' );

function autoa_register_user_roles_endpoint() {
    register_rest_route(
        'autoa/v1',
        '/user-roles/(?P<user_id>\d+)',
        [
            'methods'             => 'GET',
            'callback'            => 'autoa_get_user_roles_handler',
            'permission_callback' => '__return_true', // Auth handled inside callback
            'args'                => [
                'user_id' => [
                    'required'          => true,
                    'validate_callback' => function( $param ) {
                        return is_numeric( $param ) && intval( $param ) > 0;
                    },
                    'sanitize_callback' => 'absint',
                ],
            ],
        ]
    );
}

function autoa_get_user_roles_handler( WP_REST_Request $request ) {
    // -----------------------------------------------------------------------
    // 1. API key authentication — deny by default
    // -----------------------------------------------------------------------
    $expected_key = defined( 'AUTOA_INTERNAL_API_KEY' ) ? AUTOA_INTERNAL_API_KEY : '';
    if ( empty( $expected_key ) ) {
        // Key not configured — hard fail to avoid silent open access
        return new WP_REST_Response(
            [ 'code' => 'server_misconfiguration', 'message' => 'AUTOA_INTERNAL_API_KEY is not defined.' ],
            500
        );
    }

    $provided_key = $request->get_header( 'X-API-Key' );
    if ( empty( $provided_key ) || ! hash_equals( $expected_key, $provided_key ) ) {
        return new WP_REST_Response(
            [ 'code' => 'forbidden', 'message' => 'Invalid or missing API key.' ],
            403
        );
    }

    // -----------------------------------------------------------------------
    // 2. Resolve user
    // -----------------------------------------------------------------------
    $user_id = $request->get_param( 'user_id' );
    $user    = get_userdata( $user_id );

    if ( ! $user ) {
        return new WP_REST_Response(
            [ 'code' => 'not_found', 'message' => 'User not found.' ],
            404
        );
    }

    // -----------------------------------------------------------------------
    // 3. Return roles only — no extra user data
    // -----------------------------------------------------------------------
    $roles = array_values( $user->roles ); // re-index to ensure JSON array

    return new WP_REST_Response(
        [
            'user_id' => $user_id,
            'roles'   => $roles,
        ],
        200
    );
}
