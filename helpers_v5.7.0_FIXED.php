<?php
/**
 * Autoanosis AI Helper Functions - v5.7.0 (STABILIZATION)
 * SECURITY FIX: Enforces strict user isolation in chat-proxy endpoint.
 * CHANGE: The autoa_rest_chat_proxy function now IGNORES any user_id passed from the client.
 * It exclusively uses the server-side get_current_user_id() to build the medical snapshot.
 * This prevents any possibility of a user context leak.
 */

// It's assumed other functions from a full helpers file would be here.
// The focus is on the corrected chat proxy function.

/**
 * Main REST endpoint for the AI chat proxy.
 * Receives a message, builds a server-side medical context for the LOGGED-IN user,
 * and forwards it to the Render backend for the AI to process.
 *
 * @param WP_REST_Request $req The request object.
 * @return WP_REST_Response|WP_Error The response from the AI backend or an error.
 */
function autoa_rest_chat_proxy( WP_REST_Request $req ) {
    $start_time = microtime(true);

    // Get request parameters
    $message = sanitize_text_field( $req->get_param("message") );
    $identity_token = $req->get_param("identity_token");
    $conversation_id = $req->get_param("conversation_id");

    if ( empty($message) ) {
        return new WP_Error("missing_message", "Message is required", array("status" => 400));
    }

    // === SERVER-SIDE MEDICAL CONTEXT AGGREGATION ===
    // SECURITY: Use ONLY the server-verified logged-in user. Ignore any user_id from the client.
    $user_id = get_current_user_id();
    $medical_snapshot = null;

    // Only build a context if a user is securely identified by the server.
    if ( $user_id > 0 ) {
        global $wpdb;

        $snapshot = array("user_id" => $user_id);

        $user = get_userdata($user_id);
        if ($user) {
            $snapshot["user_name"] = $user->display_name;
        }

        // 1. Get user meta fields (basic medical info)
        $snapshot["autoimmune_type"] = get_user_meta($user_id, "autoimmune_type", true);
        $snapshot["diet_pref"] = get_user_meta($user_id, "diet_pref", true);
        $snapshot["health_info"] = get_user_meta($user_id, "health_info", true);

        // 2. Get medications from Medical Memory (using correct prefix and time_slots)
        $medications_table = $wpdb->prefix . "mm_medications";
        if ($wpdb->get_var("SHOW TABLES LIKE "."'" . $medications_table . "'" ) === $medications_table) {
            $medications = $wpdb->get_results($wpdb->prepare(
                "SELECT medication_name, dosage, frequency, time_slots, status, created_at FROM $medications_table WHERE user_id = %d ORDER BY created_at DESC", // Fetch active and inactive for history
                $user_id
            ), ARRAY_A);
            if (!empty($medications)) {
                $snapshot["medications"] = $medications;
            }
        }

        // 3. Get BEST Protocol History (all entries)
        $best_history = get_user_meta($user_id, "autoanosis_best_history", true);
        if (!empty($best_history) && is_array($best_history)) {
            $snapshot["best_history"] = array_slice($best_history, 0, 5); // Pass last 5 entries
            $snapshot["best_protocol"] = $best_history[0]; // The latest is the current one
        }

        // 4. Get Lab Results (PDF OCR data) - Full History
        $test_results_table = $wpdb->prefix . "autoanosis_test_results";
        if ($wpdb->get_var("SHOW TABLES LIKE "."'" . $test_results_table . "'" ) === $test_results_table) {
            $test_results = $wpdb->get_results($wpdb->prepare(
                "SELECT * FROM $test_results_table WHERE user_id = %d ORDER BY test_date DESC", // Full history
                $user_id
            ), ARRAY_A);
            if (!empty($test_results)) {
                $snapshot["test_results"] = $test_results;
            }
        }

        // 5. Get Symptoms Diary - Last 30 days
        $symptoms_table = $wpdb->prefix . "autoanosis_symptoms";
        if ($wpdb->get_var("SHOW TABLES LIKE "."'" . $symptoms_table . "'" ) === $symptoms_table) {
            $symptoms = $wpdb->get_results($wpdb->prepare(
                "SELECT * FROM $symptoms_table WHERE user_id = %d AND recorded_at >= DATE_SUB(NOW(), INTERVAL 30 DAY) ORDER BY recorded_at DESC",
                $user_id
            ), ARRAY_A);
            if (!empty($symptoms)) {
                $snapshot["recent_symptoms"] = $symptoms;
            }
        }

        $medical_snapshot = $snapshot;
    }

    // Build request body for Render backend
    $request_body = array(
        "message" => $message
    );

    if ( !empty($identity_token) ) {
        $request_body["identity_token"] = $identity_token;
    }

    if ( !empty($medical_snapshot) ) {
        $request_body["medical_snapshot"] = $medical_snapshot;
    }

    if ( !empty($conversation_id) ) {
        $request_body["conversation_id"] = $conversation_id;
    }

    error_log("=== AUTOANOSIS CHAT PROXY (v5.7.0 STABLE) ===");
    error_log("User ID (Server-Verified): " . $user_id);
    error_log("Has medical snapshot: " . (!empty($medical_snapshot) ? "YES" : "NO"));

    $response = wp_remote_post( "https://autoanosis-ai-backend.onrender.com/chat", array(
        "method"    => "POST",
        "headers"   => array("Content-Type" => "application/json; charset=utf-8"),
        "body"      => wp_json_encode($request_body),
        "timeout"   => 90,
    ));

    if ( is_wp_error($response) ) {
        return new WP_Error("proxy_error", $response->get_error_message(), array("status" => 500));
    }

    return rest_ensure_response(json_decode(wp_remote_retrieve_body($response), true));
}

// This function needs to be registered to a REST route, for example:
// add_action("rest_api_init", function () {
//     register_rest_route("autoa/v1", "/chat-proxy", array(
//         "methods"  => "POST",
//         "callback" => "autoa_rest_chat_proxy",
//         "permission_callback" => "__return_true", // Should be is_user_logged_in() in production
//     ));
// });
