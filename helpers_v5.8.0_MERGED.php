<?php
if ( ! defined( 'ABSPATH' ) ) { exit; }
// Ensure KB helpers are loaded
if ( ! function_exists('auto_kb_find_matches') ) {
    require_once __DIR__ . '/knowledge-base.php';
}

// Hash IP for GDPR compliance
function autoa_hash_ip() {
    $ip = isset($_SERVER['REMOTE_ADDR']) ? sanitize_text_field($_SERVER['REMOTE_ADDR']) : '0.0.0.0';
    return hash('sha256', $ip . NONCE_SALT);
}

// Search WordPress posts with enhanced relevance
function autoa_search_posts_links( $q, $limit = 3 ) {
    $args = array(
        's' => $q,
        'posts_per_page' => intval($limit),
        'post_status' => 'publish',
        'ignore_sticky_posts' => true,
        'orderby' => 'relevance',
    );
    $posts = get_posts( $args );
    
    if ( empty( $posts ) ) {
        return '';
    }
    
    $response = "\n\n📚 **Σχετικά άρθρα από το Autoanosis:**\n\n";
    foreach ( $posts as $p ) {
        $response .= sprintf("- [%s](%s)\n", esc_html(get_the_title($p)), esc_url(get_permalink($p)));
    }
    
    return $response;
}

// Intelligent fallback response using knowledge base
function autoa_get_intelligent_fallback_response( $query ) {
    $query_lower = mb_strtolower($query, 'UTF-8');
    $kb = autoa_get_knowledge_base();
    
    // Detect topic based on keywords
    $topic_keywords = array(
        'stress_management' => array('άγχος', 'στρες', 'αγχος', 'χαλάρωση', 'χαλαρωση', 'διαλογισμός', 'διαλογισμος', 'αναπνοή', 'αναπνοη', 'ηρεμία', 'ηρεμια'),
        'exercise' => array('άσκηση', 'ασκηση', 'γυμναστική', 'γυμναστικη', 'κίνηση', 'κινηση', 'περπάτημα', 'περπατημα', 'γιόγκα', 'γιογκα', 'κολύμβηση', 'κολυμβηση'),
        'nutrition' => array('διατροφή', 'διατροφη', 'τροφές', 'τροφες', 'φαγητό', 'φαγητο', 'διατροφικός', 'διατροφικος', 'φλεγμονή', 'φλεγμονη'),
        'sleep' => array('ύπνος', 'υπνος', 'κοιμάμαι', 'κοιμαμαι', 'αϋπνία', 'αυπνια', 'ξεκούραση', 'ξεκουραση')
    );
    
    $detected_topic = null;
    foreach ($topic_keywords as $topic => $keywords) {
        foreach ($keywords as $keyword) {
            if (strpos($query_lower, $keyword) !== false) {
                $detected_topic = $topic;
                break 2;
            }
        }
    }
    
    // Detect condition
    $condition_keywords = array(
        'hashimoto' => array('hashimoto', 'χασιμότο', 'χασιμοτο', 'θυρεοειδίτιδα', 'θυρεοειδιτιδα', 'θυρεοειδής', 'θυρεοειδης'),
        'rheumatoid_arthritis' => array('ρευματοειδής', 'ρευματοειδης', 'αρθρίτιδα', 'αρθριτιδα', 'ρευματοειδή', 'ρευματοειδη', 'ψωριασική', 'ψωριασικη'),
        'lupus' => array('λύκος', 'λυκος', 'sle', 'ερυθηματώδης', 'ερυθηματωδης'),
        'multiple_sclerosis' => array('σκλήρυνση', 'σκληρυνση', 'πολλαπλή', 'πολλαπλη', 'ms'),
        'psoriatic_arthritis' => array('ψωριασική', 'ψωριασικη', 'ψωρίαση', 'ψωριαση')
    );
    
    $detected_condition = null;
    foreach ($condition_keywords as $condition => $keywords) {
        foreach ($keywords as $keyword) {
            if (strpos($query_lower, $keyword) !== false) {
                $detected_condition = $condition;
                break 2;
            }
        }
    }
    
    $response = '';
    
    // Generate response based on detected topic
    if ($detected_topic && isset($kb[$detected_topic])) {
        $data = $kb[$detected_topic];
        
        switch ($detected_topic) {
            case 'stress_management':
                $response = "## 🧘 Διαχείριση Άγχους\n\n";
                $response .= "Το χρόνιο στρες επηρεάζει αρνητικά το ανοσοποιητικό σύστημα. Ορισμένες αποτελεσματικές τεχνικές:\n\n";
                foreach ($data['techniques'] as $technique => $description) {
                    $response .= "**{$technique}:** {$description}\n\n";
                }
                $response .= "**Οφέλη:** " . $data['benefits'];
                break;
                
            case 'exercise':
                $response = "## 🏃 Άσκηση & Κίνηση\n\n";
                $response .= "Η μέτρια άσκηση μειώνει τη φλεγμονή κατά 20-40%. Προτεινόμενες δραστηριότητες:\n\n";
                foreach ($data['types'] as $type => $info) {
                    $response .= "**{$type}:**\n";
                    $response .= "- Παραδείγματα: {$info['examples']}\n";
                    $response .= "- Διάρκεια: {$info['duration']}\n";
                    $response .= "- Ένταση: {$info['intensity']}\n\n";
                }
                $response .= "⚠️ **Προσοχή:** " . $data['warnings'];
                break;
                
            case 'nutrition':
                $response = "## 🥗 Αντιφλεγμονώδης Διατροφή\n\n";
                $response .= "**Προτεινόμενες Τροφές:**\n\n";
                foreach ($data['recommended_foods'] as $food => $description) {
                    $response .= "- **{$food}:** {$description}\n";
                }
                $response .= "\n**Τροφές προς Αποφυγή:**\n\n";
                foreach ($data['foods_to_avoid'] as $food => $description) {
                    $response .= "- **{$food}:** {$description}\n";
                }
                break;
                
            case 'sleep':
                $response = "## 😴 Ύπνος & Αποκατάσταση\n\n";
                $response .= $data['importance'] . "\n\n**Συμβουλές:**\n\n";
                foreach ($data['tips'] as $tip => $description) {
                    $response .= "- **{$tip}:** {$description}\n";
                }
                break;
        }
    }
    
    // Add condition-specific information
    if ($detected_condition && isset($kb['conditions'][$detected_condition])) {
        $condition = $kb['conditions'][$detected_condition];
        $response .= "\n\n## 📋 " . $condition['name'] . "\n\n";
        $response .= "**Συμπτώματα:** " . $condition['symptoms'] . "\n\n";
        $response .= "**Διαχείριση:** " . $condition['management'] . "\n\n";
        $response .= "**Τρόπος Ζωής:** " . $condition['lifestyle'];
    }
    
    // If no specific topic detected, provide general guidance
    if (empty($response)) {
        $response = "Γεια σου! Μπορώ να σε βοηθήσω με πληροφορίες για:\n\n";
        $response .= "🧘 **Διαχείριση Άγχους** - Τεχνικές χαλάρωσης και διαλογισμού\n";
        $response .= "🏃 **Άσκηση** - Ασφαλείς ασκήσεις για αυτοάνοσα\n";
        $response .= "🥗 **Διατροφή** - Αντιφλεγμονώδεις τροφές\n";
        $response .= "😴 **Ύπνος** - Βελτίωση ποιότητας ύπνου\n";
        $response .= "💊 **Συμπτώματα** - Διαχείριση συμπτωμάτων\n\n";
        $response .= "Κάνε μια πιο συγκεκριμένη ερώτηση για να σε βοηθήσω καλύτερα!";
    }
    
    // Add related articles if available
    $related_articles = autoa_search_posts_links($query, 3);
    if (!empty($related_articles)) {
        $response .= $related_articles;
    }
    
    // Add disclaimer
    $response .= "\n\n💡 *Σημείωση: Αυτές οι πληροφορίες είναι ενημερωτικές. Συμβουλέψου πάντα τον ιατρό σου πριν κάνεις αλλαγές στη θεραπεία ή τον τρόπο ζωής σου.*";
    
    return $response;
}

// Build enhanced user context
function autoa_build_user_context( $user_id ){
    if ( ! $user_id ) return '';
    
    $cond   = get_user_meta($user_id, 'autoimmune_type', true);
    $diet   = get_user_meta($user_id, 'diet_pref', true);
    $trig   = get_user_meta($user_id, 'triggers', true);
    
    $ctx = array();
    if($cond) $ctx[] = "Κατάσταση: " . $cond;
    if($diet) $ctx[] = "Διατροφή: " . $diet;
    if($trig) $ctx[] = "Triggers: " . $trig;
    
    return !empty($ctx) ? implode(", ", $ctx) : '';
}

// Generate session ID
function autoa_get_session_id() {
    if ( ! session_id() ) {
        session_start();
    }
    if ( ! isset( $_SESSION['autoa_session_id'] ) ) {
        $_SESSION['autoa_session_id'] = wp_generate_password(32, false);
    }
    return $_SESSION['autoa_session_id'];
}

// Save conversation to database
function autoa_save_conversation( $session_id, $user_id, $messages ) {
    global $wpdb;
    $table = $wpdb->prefix . 'autoa_conversations';
    
    $existing = $wpdb->get_row( $wpdb->prepare(
        "SELECT id FROM $table WHERE session_id = %s",
        $session_id
    ) );
    
    $data = array(
        'session_id' => $session_id,
        'user_id' => $user_id,
        'updated_at' => current_time('mysql'),
        'messages' => wp_json_encode($messages)
    );
    
    if ( $existing ) {
        $wpdb->update( $table, $data, array('session_id' => $session_id) );
    } else {
        $data['created_at'] = current_time('mysql');
        $wpdb->insert( $table, $data );
    }
}

// Get conversation history
function autoa_get_conversation( $session_id ) {
    global $wpdb;
    $table = $wpdb->prefix . 'autoa_conversations';
    
    $conv = $wpdb->get_row( $wpdb->prepare(
        "SELECT messages FROM $table WHERE session_id = %s",
        $session_id
    ) );
    
    if ( $conv && $conv->messages ) {
        return json_decode( $conv->messages, true );
    }
    
    return array();
}

// Register REST API endpoints
add_action('rest_api_init', function(){
    // Main chat endpoint
    register_rest_route('autoa/v1', 'ask', array(
        'methods'  => 'POST',
        'permission_callback' => '__return_true',
        'callback' => 'autoa_rest_ask',
        'args' => array(
            'q' => array('required' => true, 'type' => 'string'),
            'session_id' => array('required' => false, 'type' => 'string'),
            'user_id' => array('required' => false, 'type' => 'integer')
        )
    ));
    
    // Feedback endpoint
    register_rest_route('autoa/v1', 'feedback', array(
        'methods'  => 'POST',
        'permission_callback' => '__return_true',
        'callback' => 'autoa_rest_feedback',
        'args' => array(
            'log_id' => array('required' => true, 'type' => 'integer'),
            'feedback' => array('required' => true, 'type' => 'integer')
        )
    ));
    
    // Quick actions endpoint
    register_rest_route('autoa/v1', 'quick-actions', array(
        'methods'  => 'GET',
        'permission_callback' => '__return_true',
        'callback' => 'autoa_rest_quick_actions'
    ));
    
    // Identity token endpoint - generates JWT-like token for Render backend
    // MUST match Render's identity.py verification algorithm:
    // - Signature is HMAC-SHA256 of BASE64-encoded payload (not raw JSON)
    // - Payload must include: uid, iat, exp, nonce, iss
    register_rest_route('autoa/v1', 'token', array(
        'methods'  => 'GET',
        'permission_callback' => function() {
            return is_user_logged_in();
        },
        'callback' => function() {
            $user_id = get_current_user_id();
            $secret = defined('AUTOANOSIS_IDENTITY_SECRET')
                ? AUTOANOSIS_IDENTITY_SECRET
                : 'MISSING_SECRET';
            
            // Payload must match what Render expects
            $payload = array(
                'uid'   => $user_id,
                'iat'   => time(),
                'exp'   => time() + 300,
                'nonce' => wp_generate_uuid4(),
                'iss'   => 'autoanosis-wordpress'
            );
            
            // JSON encode payload
            $json = wp_json_encode($payload);
            
            // STANDARD Base64 encoding (with padding) - Render expects this format
            $payload_b64 = base64_encode($json);
            
            // HMAC signature on BASE64-encoded payload string
            $sig_raw = hash_hmac('sha256', $payload_b64, $secret, true);
            
            // Signature as STANDARD Base64 (with padding)
            $sig_b64 = base64_encode($sig_raw);
            
            return array(
                'token' => $payload_b64 . '.' . $sig_b64
            );
        }
    ));
    
    // Chat proxy endpoint - proxies requests to Render backend
    register_rest_route('autoa/v1', 'chat-proxy', array(
        'methods'  => 'POST',
        'permission_callback' => '__return_true',
        'callback' => 'autoa_rest_chat_proxy',
        'args' => array(
            'message' => array('required' => true, 'type' => 'string'),
            'identity_token' => array('required' => false, 'type' => 'string'),
            'medical_snapshot' => array('required' => false, 'type' => 'object'),
            'conversation_id' => array('required' => false, 'type' => 'string')
        )
    ));
});

// Main chat endpoint handler
function autoa_rest_ask( WP_REST_Request $req ){
    $start_time = microtime(true);
    $q = sanitize_text_field( $req->get_param('q') );
    $session_id = $req->get_param('session_id');

    // Generate session ID if not provided
    if ( empty($session_id) ) {
        $session_id = autoa_get_session_id();
    }
    
    if ( empty( $q ) ) {
        return new WP_REST_Response(array(
            'answer' => 'Παρακαλώ γράψε την ερώτησή σου.',
            'source' => 'error'
        ), 400);
    }
    
    // FREEMIUM: TEMPORARILY DISABLED FOR TESTING
    // TODO: Fix REST API authentication issue
    $usage_status = array('can_ask' => true, 'remaining' => -1, 'is_member' => true);
    
    // DEBUG: Log freemium check
    error_log('=== FREEMIUM CHECK (DISABLED) ===');
    error_log('User ID: ' . get_current_user_id());
    error_log('Is logged in: ' . (is_user_logged_in() ? 'YES' : 'NO'));
    error_log('Freemium check: BYPASSED FOR TESTING');
    error_log('=== END FREEMIUM CHECK ===');
    
    if ( false && !$usage_status['can_ask'] ) {
        return new WP_REST_Response(array(
            'answer' => '',
            'source' => 'limit_reached',
            'limit_reached' => true,
            'is_member' => false,
            'upgrade_html' => autoa_get_upgrade_popup_html()
        ), 403);
    }

    $api_key = trim(get_option('autoa_openai_api_key', ''));
    $model   = get_option('autoa_openai_model', 'gpt-4o-mini');
    $system  = get_option('autoa_system_prompt', autoa_get_default_system_prompt());
    
    // Get user ID with proper authentication
    $user_id = 0;
    $claimed_user_id = $req->get_param('user_id') ? intval($req->get_param('user_id')) : 0;
    
    // Method 1: Check if WordPress recognizes the user (works when called from admin or logged-in pages)
    $wp_user_id = get_current_user_id();
    if ($wp_user_id > 0) {
        $user_id = $wp_user_id;
    }
    // Method 2: Use claimed user ID from request, but verify it's valid
    else if ($claimed_user_id > 0) {
        // Verify the claimed user ID exists and matches session
        $user_exists = get_userdata($claimed_user_id);
        if ($user_exists) {
            // Additional security: Check if this session_id was used by this user before
            if (!empty($session_id)) {
                global $wpdb;
                $table = $wpdb->prefix . 'autoa_conversations';
                $session_user = $wpdb->get_var($wpdb->prepare(
                    "SELECT user_id FROM $table WHERE session_id = %s LIMIT 1",
                    $session_id
                ));
                // If session exists and matches, use it
                if ($session_user && intval($session_user) === $claimed_user_id) {
                    $user_id = $claimed_user_id;
                }
                // If session doesn't exist yet, trust the claimed ID (first message)
                else if (!$session_user) {
                    $user_id = $claimed_user_id;
                }
                // If session exists but doesn't match, reject (security)
                else {
                    error_log("Autoanosis Security: User ID mismatch. Session user: $session_user, Claimed: $claimed_user_id");
                    $user_id = 0;
                }
            } else {
                // No session yet, trust claimed ID
                $user_id = $claimed_user_id;
            }
        }
    }
    // Method 3: Try to get from conversation history
    else if (!empty($session_id)) {
        global $wpdb;
        $table = $wpdb->prefix . 'autoa_conversations';
        $session_user = $wpdb->get_var($wpdb->prepare(
            "SELECT user_id FROM $table WHERE session_id = %s LIMIT 1",
            $session_id
        ));
        if ($session_user && intval($session_user) > 0) {
            $user_id = intval($session_user);
        }
    }
    
    // If still no user ID, return error (don't fallback to admin)
    if ($user_id === 0) {
        return new WP_Error('no_user', 'User authentication required. Please log in.', array('status' => 401));
    }
    
    // Build comprehensive user context using AI Context Builder
    $user_context = Autoa_AI_Context_Builder::build_context($user_id);
    $context_string = Autoa_AI_Context_Builder::format_for_ai($user_context);
    
    // Add context to system prompt
    if (!empty($context_string)) {
        $system .= "\n\n" . $context_string;
    }
    
// === Autoanosis: attach recent scientific updates with citations (SAFE) ===
$kb_block = '';
try {
    // Πάρε με ασφάλεια την ερώτηση του χρήστη (για τη συσχέτιση με το KB)
    $user_query_str = '';
    if (isset($q) && is_string($q) && $q !== '') {
        $user_query_str = $q;
    } elseif (isset($req) && $req instanceof WP_REST_Request) {
        $m = $req->get_param('message');
        $r = $req->get_param('q');
        if (is_string($m) && $m !== '') { $user_query_str = $m; }
        elseif (is_string($r) && $r !== '') { $user_query_str = $r; }
    }

    // Βρες μέχρι 5 σχετικά αποτελέσματα από τη γνώση (αν υπάρχει helper)
    $kb_matches = [];
    if ($user_query_str !== '' && function_exists('auto_kb_find_matches')) {
        $kb_matches = auto_kb_find_matches($user_query_str, 5);
    }

    // Χτίσε block με Τίτλο • (Πηγή, Ημ/νία) • Summary • URL
    if (!empty($kb_matches)) {
        $i = 1;
        $lines = [];

        foreach ($kb_matches as $x) {
            $title  = isset($x['title'])        ? wp_strip_all_tags($x['title'])        : '';
            $date   = isset($x['published_at']) ? substr($x['published_at'], 0, 10)      : '';
            $sum    = isset($x['summary'])      ? wp_strip_all_tags($x['summary'])       : '';
            $url    = isset($x['url'])          ? esc_url_raw($x['url'])                 : '';
            $source = isset($x['source'])       ? wp_strip_all_tags($x['source'])        : '';

            $parts = [];
            if ($title !== '')  { $parts[] = "**{$title}**"; }

            $meta = trim($source . ($source && $date ? ', ' : '') . $date, ', ');
            if ($meta !== '')   { $parts[] = "({$meta})"; }

            if ($sum !== '')    { $parts[] = "Summary: {$sum}"; }
            if ($url !== '')    { $parts[] = "URL: {$url}"; }

            $lines[] = $i++ . '. ' . implode(' — ', $parts);
        }

        $kb_block = "RECENT_SCIENTIFIC_UPDATES:\n" . implode("\n", $lines) . "\n";
    }
} catch (\Throwable $e) {
    // Σιωπηλή αποτυχία — δεν σπάμε τη ροή αν κάτι πάει στραβά
}

// Κόλλησε το block μέσα στο system prompt (ώστε να το “δει” το μοντέλο)
if ($kb_block !== '') {
    $system .= "\n\n" . $kb_block;
}

    // If no API key, use intelligent fallback
    if ( empty($api_key) ) {
        $answer = autoa_get_intelligent_fallback_response( $q );
        // Append KB block to fallback answer if available
        if ( !empty($kb_block) ) {
            $answer .= "\n\n" . $kb_block;
        }
        $response_time = microtime(true) - $start_time;
        
        $log_id = null;
        if ( function_exists('autoa_log_ai_interaction') ) {
            $log_id = autoa_log_ai_interaction( $user_id, $q, $answer, 0, 0, 'knowledge-base', $response_time );
        }
        
        return array(
            'answer' => $answer,
            'source' => 'knowledge-base',
            'response_time' => round($response_time, 2),
            'log_id' => $log_id,
            'session_id' => $session_id
        );
    }

    // Build conversation history
    $conversation = autoa_get_conversation( $session_id );
    $messages = array(
        array('role' => 'system', 'content' => $system)
    );
    
    // Add conversation history (last 6 messages for context)
    if ( !empty($conversation) ) {
        $recent = array_slice($conversation, -6);
        foreach ( $recent as $msg ) {
            $messages[] = $msg;
        }
    }
    
    // Add current question
    $messages[] = array('role' => 'user', 'content' => $q);
    
    // DEBUG: Log what we're sending to AI
    error_log('=== AUTOANOSIS AI DEBUG ===');
    error_log('User ID: ' . $user_id);
    error_log('System Prompt Length: ' . strlen($system));
    error_log('Context String: ' . $context_string);
    error_log('Full System Prompt: ' . $system);
    error_log('=== END DEBUG ===');

    // Call OpenAI API
    $body = array(
        'model'       => $model,
        'messages'    => $messages,
        // Use a low temperature for more stable, informational responses
        'temperature' => 0.2,
        'max_tokens'  => 800,
    );

    $resp = wp_remote_post( 'https://api.openai.com/v1/chat/completions', array(
        'headers' => array(
            'Content-Type' => 'application/json',
            'Authorization' => 'Bearer ' . $api_key
        ),
        'timeout' => 30,
        'body' => wp_json_encode($body),
    ));

    if ( is_wp_error($resp) ) {
        $answer = autoa_get_intelligent_fallback_response( $q );
        // Append KB block to fallback answer if available
        if ( !empty($kb_block) ) {
            $answer .= "\n\n" . $kb_block;
        }
        $response_time = microtime(true) - $start_time;
        
        $log_id = null;
        if ( function_exists('autoa_log_ai_interaction') ) {
            $log_id = autoa_log_ai_interaction( $user_id, $q, $answer, 0, 0, 'fallback', $response_time );
        }
        
        return array(
            'answer' => $answer,
            'source' => 'fallback',
            'response_time' => round($response_time, 2),
            'log_id' => $log_id,
            'session_id' => $session_id
        );
    }

    $code = wp_remote_retrieve_response_code($resp);
    $data = json_decode( wp_remote_retrieve_body($resp), true );
    
    if ( $code !== 200 || empty($data['choices'][0]['message']['content']) ) {
        $answer = autoa_get_intelligent_fallback_response( $q );
        // Append KB block to fallback answer if available
        if ( !empty($kb_block) ) {
            $answer .= "\n\n" . $kb_block;
        }
        $response_time = microtime(true) - $start_time;
        
        $log_id = null;
        if ( function_exists('autoa_log_ai_interaction') ) {
            $log_id = autoa_log_ai_interaction( $user_id, $q, $answer, 0, 0, 'fallback', $response_time );
        }
        
        return array(
            'answer' => $answer,
            'source' => 'fallback',
            'response_time' => round($response_time, 2),
            'log_id' => $log_id,
            'session_id' => $session_id
        );
    }
// === Build Scientific Updates block from wp_auto_kb ===
$kb_block = '';
try {
    // Βεβαιώσου ότι υπάρχει η συνάρτηση από knowledge-base.php
    if ( ! function_exists('auto_kb_find_matches') ) {
        require_once __DIR__ . '/knowledge-base.php';
    }

    // Πάρε το ερώτημα του χρήστη (ό,τι έχεις διαθέσιμο)
    $q = '';
    if (!empty($clean_user_text)) {
        $q = $clean_user_text;
    } elseif (!empty($user_message)) {
        $q = $user_message;
    } elseif (!empty($data['user_prompt'])) { // προαιρετικό, αν υπάρχει αλλού
        $q = $data['user_prompt'];
    }

    $q = is_string($q) ? trim($q) : '';

    if ($q !== '') {
        // Ζήτα έως 3 σχετικά αποτελέσματα από τον πίνακα wp_auto_kb
        $matches = auto_kb_find_matches($q, 3);

        if (!empty($matches) && is_array($matches)) {
            $lines = [];
            foreach ($matches as $m) {
                $title = isset($m['title']) ? trim($m['title']) : '';
                $src   = isset($m['source']) ? trim($m['source']) : '';
                $date  = isset($m['published_at']) ? trim($m['published_at']) : '';
                $url   = isset($m['url']) ? trim($m['url']) : '';

                // Γραμμή bullets: Τίτλος (Πηγή, Ημ/νία) + URL
                $label = $title !== '' ? $title : '[χωρίς τίτλο]';
                $meta  = [];
                if ($src !== '')  { $meta[] = $src; }
                if ($date !== '') { $meta[] = $date; }

                $line  = '- ' . $label;
                if (!empty($meta)) {
                    $line .= ' (' . implode(', ', $meta) . ')';
                }
                if ($url !== '') {
                    $line .= "\n  " . $url;
                }

                $lines[] = $line;
            }

            if (!empty($lines)) {
                // Αυτό το $kb_block θα ενωθεί παρακάτω στο τελικό $content (το έχεις ήδη)
                $kb_block = implode("\n", $lines);
            }
        }
    }
} catch (\Throwable $e) {
    // Σιωπηλό fallback: δεν εμποδίζουμε την βασική απάντηση του bot
    $kb_block = '';
}

// Extract assistant content from API response
$content = $data['choices'][0]['message']['content'] ?? '';
// --- URL & source helpers ----------------------------------------------
if ( ! function_exists('auto_clean_url') ) {
    function auto_clean_url(string $url): string {
        $p = parse_url($url);
        if (!$p || empty($p['host'])) return $url;
        $scheme = $p['scheme'] ?? 'https';
        $host   = $p['host'];
        $path   = isset($p['path']) ? urldecode($p['path']) : '';
        return $scheme . '://' . $host . $path;
    }
}

if ( ! function_exists('auto_host') ) {
    function auto_host(string $url): string {
        $p = parse_url($url);
        $host = $p['host'] ?? '';
        return preg_replace('/^www\./i', '', $host);
    }
}

// === Make KB block visible in final answer ===
// $kb_block έχει ήδη γεμίσει νωρίτερα (αν βρέθηκαν matches από τη Scientific Updates DB)
if ( ! function_exists('auto_kb_render_block') ) {
    function auto_kb_render_block($rows, $title = "ΕΠΙΣΤΗΜΟΝΙΚΕΣ ΕΝΗΜΕΡΩΣΕΙΣ") {
        if (empty($rows)) return '';
        $out = "\n\n## {$title}:\n";
        $n = 0;
        foreach ($rows as $r) {
            if (++$n > 5) break;
            $t = trim($r['title'] ?? '');
            $s = trim($r['source'] ?? '');
            $d = trim($r['published_at'] ?? '');
            $u = trim($r['url'] ?? '');

            if (!empty($u)) $u = auto_clean_url($u);
            if (empty($s)) $s = auto_host($u);

            $out .= "🔹 [{$t}]({$u})" . ($d ? " ({$d})" : '') . " — *{$s}*\n";
        }
        return $out;
    }
}

// === Επιστημονικές ενημερώσεις από τη ΒΔ (tkc_auto_kb) ===
require_once __DIR__ . '/knowledge-base.php';

// προσπάθησε να πιάσεις το ερώτημα του χρήστη από ό,τι υπάρχει διαθέσιμο
$q = $user_query
     ?? ($payload['input'] ?? null)
     ?? ($_POST['question'] ?? null)
     ?? '';

// φέρε έως 5 σχετικά αποτελέσματα
$kb_rows  = auto_kb_find_matches($q, 5);

// απόδοσή τους σε έτοιμο block με τίτλο
$kb_block = auto_kb_render_block($kb_rows, "ΕΠΙΣΤΗΜΟΝΙΚΕΣ ΕΝΗΜΕΡΩΣΕΙΣ");


if (!empty($kb_block)) {
$content .= "\n\n" . $kb_block;
}

// === Σταθερή ιατρική αποποίηση ευθύνης (μόνο μία φορά, καθαρά) ===
if (
    !str_contains($content, '⚠️ Σημείωση') &&
    !str_contains($content, 'Αυτές οι πληροφορίες είναι ενημερωτικές')
) {
    $content .= "\n\n⚠️ Σημείωση: Αυτές οι πληροφορίες είναι ενημερωτικές και δεν υποκαθιστούν ιατρική συμβουλή. " .
                "Συμβουλεύσου πάντα τον γιατρό σου πριν κάνεις αλλαγές στη θεραπεία ή τον τρόπο ζωής σου.";
}

// Το τελικό κείμενο της απάντησης
$answer = $content;

// === ΤΕΛΟΣ ΜΠΛΟΚ ΣΥΝΘΕΣΗΣ ΑΠΑΝΤΗΣΗΣ ===


    // Compute token usage and response time
    $tok_in  = isset($data['usage']['prompt_tokens']) ? intval($data['usage']['prompt_tokens']) : 0;
    $tok_out = isset($data['usage']['completion_tokens']) ? intval($data['usage']['completion_tokens']) : 0;
    $response_time = microtime(true) - $start_time;

    // Save to conversation history
    $conversation[] = array('role' => 'user', 'content' => $q);
    $conversation[] = array('role' => 'assistant', 'content' => $content);
    autoa_save_conversation( $session_id, $user_id, $conversation );

    // Log interaction
    $log_id = null;
    if ( function_exists('autoa_log_ai_interaction') ) {
        $log_id = autoa_log_ai_interaction( $user_id, $q, $content, $tok_in, $tok_out, $model, $response_time );
    }
    
    // FREEMIUM: Increment guest usage counter
    autoa_increment_guest_usage();

    return array(
        'answer' => $content,
        'source' => 'openai',
        'model' => $model,
        'tokens' => array('in' => $tok_in, 'out' => $tok_out),
        'response_time' => round($response_time, 2),
        'log_id' => $log_id,
        'session_id' => $session_id
    );
}

// Feedback endpoint handler
function autoa_rest_feedback( WP_REST_Request $req ) {
    $log_id = intval( $req->get_param('log_id') );
    $feedback = intval( $req->get_param('feedback') ); // 1 = positive, -1 = negative
    
    if ( ! $log_id || ! in_array($feedback, array(1, -1)) ) {
        return new WP_REST_Response(array('success' => false), 400);
    }
    
    global $wpdb;
    $table = $wpdb->prefix . 'autoa_ai_logs';
    
    $updated = $wpdb->update(
        $table,
        array('feedback' => $feedback),
        array('id' => $log_id),
        array('%d'),
        array('%d')
    );
    
    return array('success' => $updated !== false);
}

// Quick actions endpoint
function autoa_rest_quick_actions() {
    $actions = array(
        array(
            'id' => 'stress',
            'icon' => '🧘',
            'label' => 'Διαχείριση Άγχους',
            'query' => 'Ποιες τεχνικές μπορώ να χρησιμοποιήσω για να μειώσω το στρες και το άγχος;'
        ),
        array(
            'id' => 'exercise',
            'icon' => '🏃',
            'label' => 'Άσκηση',
            'query' => 'Ποια άσκηση είναι ασφαλής και ωφέλιμη για την κατάστασή μου;'
        ),
        array(
            'id' => 'nutrition',
            'icon' => '🥗',
            'label' => 'Διατροφή',
            'query' => 'Ποιες τροφές μειώνουν τη φλεγμονή και ποιες πρέπει να αποφύγω;'
        ),
        array(
            'id' => 'sleep',
            'icon' => '😴',
            'label' => 'Ύπνος',
            'query' => 'Πώς μπορώ να βελτιώσω την ποιότητα του ύπνου μου;'
        ),
        array(
            'id' => 'symptoms',
            'icon' => '💊',
            'label' => 'Συμπτώματα',
            'query' => 'Πώς μπορώ να διαχειριστώ καλύτερα τα συμπτώματά μου;'
        ),
        array(
            'id' => 'info',
            'icon' => '📚',
            'label' => 'Η Κατάστασή μου',
            'query' => 'Πες μου περισσότερα για την αυτοάνοση κατάστασή μου'
        )
    );
    
    return $actions;
}


/**
 * Calculate and update user profile completion percentage
 * 
 * @param int $user_id User ID
 * @return int Profile completion percentage (0-100)
 */
function autoa_calculate_profile_completion($user_id) {
    // Define profile fields to check
    $profile_fields = array(
        'autoimmune_type',  // Αυτοάνοση Κατάσταση
        'diet_pref',        // Διατροφικές Προτιμήσεις
        'health_info'       // Εξετάσεις και Πληροφορίες Υγείας
    );
    
    $filled_fields = 0;
    $total_fields = count($profile_fields);
    
    // Count filled fields
    foreach ($profile_fields as $field) {
        $value = get_user_meta($user_id, $field, true);
        if (!empty($value) && trim($value) !== '') {
            $filled_fields++;
        }
    }
    
    // Calculate percentage
    $completion = ($total_fields > 0) ? round(($filled_fields / $total_fields) * 100) : 0;
    
    // Update the meta
    update_user_meta($user_id, 'autoa_profile_completion', $completion);
    
    return $completion;
}

/**
 * Get user profile completion percentage
 * Calculates if not already set
 * 
 * @param int $user_id User ID
 * @return int Profile completion percentage (0-100)
 */
function autoa_get_profile_completion($user_id) {
    // Always recalculate to ensure accuracy
    $completion = autoa_calculate_profile_completion($user_id);
    
    return intval($completion);
}

/**
 * Chat Proxy Endpoint Handler
 * Proxies chat requests to Render backend with proper timeout and error handling
 * 
 * @param WP_REST_Request $req Request object
 * @return array|WP_Error Response data or error
 */
function autoa_rest_chat_proxy( WP_REST_Request $req ) {
    $start_time = microtime(true);
    
    // Get request parameters
    $message = sanitize_text_field( $req->get_param('message') );
    $identity_token = $req->get_param('identity_token');
    $conversation_id = $req->get_param('conversation_id');
    
    // Validate required parameters
    if ( empty($message) ) {
        return new WP_Error(
            'missing_message',
            'Message is required',
            array('status' => 400)
        );
    }
    
    // === SERVER-SIDE: Fetch comprehensive medical snapshot from ALL medical tables ===
    $user_id = get_current_user_id();
    $medical_snapshot = null;
    
    if ( $user_id ) {
        global $wpdb;
        
        // Initialize medical data array
        $snapshot = array(
            'user_id' => $user_id,
        );
        
        // Get user display name
        $user = get_userdata($user_id);
        if ($user) {
            $snapshot['user_name'] = $user->display_name;
        }
        
        // 1. Get user meta fields (basic medical info)
        $snapshot['autoimmune_type'] = get_user_meta($user_id, 'autoimmune_type', true);
        $snapshot['diet_pref'] = get_user_meta($user_id, 'diet_pref', true);
        $snapshot['health_info'] = get_user_meta($user_id, 'health_info', true);
        
        // 2. Get health profile from dedicated table
        $health_profile_table = $wpdb->prefix . 'autoanosis_health_profiles';
        if ($wpdb->get_var("SHOW TABLES LIKE '$health_profile_table'") === $health_profile_table) {
            $health_profile = $wpdb->get_row($wpdb->prepare(
                "SELECT * FROM $health_profile_table WHERE user_id = %d ORDER BY created_at DESC LIMIT 1",
                $user_id
            ), ARRAY_A);
            
            if ($health_profile) {
                $snapshot['health_profile'] = $health_profile;
            }
        }
        
        // 3. Get recent daily check-ins
        $checkins_table = $wpdb->prefix . 'autoa_daily_checkins';
        if ($wpdb->get_var("SHOW TABLES LIKE '$checkins_table'") === $checkins_table) {
            $recent_checkins = $wpdb->get_results($wpdb->prepare(
                "SELECT checkin_date, pain_level, fatigue_level, energy_level, mood_level, notes 
                 FROM $checkins_table 
                 WHERE user_id = %d 
                 ORDER BY checkin_date DESC 
                 LIMIT 7",
                $user_id
            ), ARRAY_A);
            
            if (!empty($recent_checkins)) {
                $snapshot['recent_checkins'] = $recent_checkins;
            }
        }
        
        // 4. Get current medications
        // 4a. Legacy autoanosis_medications table
        $medications_table = $wpdb->prefix . 'autoanosis_medications';
        if ($wpdb->get_var("SHOW TABLES LIKE '$medications_table'") === $medications_table) {
            $medications = $wpdb->get_results($wpdb->prepare(
                "SELECT * FROM $medications_table WHERE user_id = %d AND is_active = 1 ORDER BY created_at DESC",
                $user_id
            ), ARRAY_A);
            
            if (!empty($medications)) {
                $snapshot['medications'] = $medications;
            }
        }
        
        // 4b. Medical Memory plugin mm_medications table (v12+) — PRIMARY source
        // This table stores medications with time_slots for scheduled reminders.
        $mm_medications_table = $wpdb->prefix . 'mm_medications';
        if ($wpdb->get_var("SHOW TABLES LIKE '$mm_medications_table'") === $mm_medications_table) {
            $mm_medications = $wpdb->get_results($wpdb->prepare(
                "SELECT medication_name, dosage, frequency, time_slots, active, instructions AS notes, created_at FROM $mm_medications_table WHERE patient_id = %d ORDER BY created_at DESC",
                $user_id
            ), ARRAY_A);
            
            if (!empty($mm_medications)) {
                // Decode time_slots JSON if stored as string
                foreach ($mm_medications as &$mm_med) {
                    if (isset($mm_med['time_slots']) && is_string($mm_med['time_slots'])) {
                        $decoded_slots = json_decode($mm_med['time_slots'], true);
                        if (is_array($decoded_slots)) {
                            $mm_med['time_slots'] = $decoded_slots;
                        }
                    }
                }
                unset($mm_med);
                // Merge or override: mm_medications is the primary source
                $snapshot['medications'] = $mm_medications;
            }
        }
        
        // 5. Get recent symptoms (last 30 days)
        $symptoms_table = $wpdb->prefix . 'autoanosis_symptoms';
        if ($wpdb->get_var("SHOW TABLES LIKE '$symptoms_table'") === $symptoms_table) {
            $symptoms = $wpdb->get_results($wpdb->prepare(
                "SELECT * FROM $symptoms_table WHERE user_id = %d AND recorded_at >= DATE_SUB(NOW(), INTERVAL 30 DAY) ORDER BY recorded_at DESC",
                $user_id
            ), ARRAY_A);
            
            if (!empty($symptoms)) {
                $snapshot['recent_symptoms'] = $symptoms;
            }
        }
        
        // 6. Get health tracking data
        $tracking_table = $wpdb->prefix . 'autoanosis_health_tracking';
        if ($wpdb->get_var("SHOW TABLES LIKE '$tracking_table'") === $tracking_table) {
            $tracking = $wpdb->get_results($wpdb->prepare(
                "SELECT * FROM $tracking_table WHERE user_id = %d ORDER BY tracked_at DESC LIMIT 30",
                $user_id
            ), ARRAY_A);
            
            if (!empty($tracking)) {
                $snapshot['health_tracking'] = $tracking;
            }
        }
        
        // 7. Get structured exam results from Exams Normalizer subsystem
        // RULE: Doctor Dashboard reads ONLY structured exam data.
        // Raw blobs / OCR text / failed extracts are NEVER used as source of truth.
        if ( function_exists('autoanosis_exams_fetch_structured_snapshot') ) {
            $structured_exams = autoanosis_exams_fetch_structured_snapshot( $user_id );
            if ( !is_wp_error($structured_exams) && !empty($structured_exams['structured_exam_results']) ) {
                $snapshot['structured_exam_results'] = $structured_exams['structured_exam_results'];
                $snapshot['exam_report_count']       = $structured_exams['report_count'] ?? 0;
                // test_results intentionally NOT set — backend prefers structured_exam_results
            } else {
                // Fallback: raw WP table only if Exams API is unavailable
                $test_results_table = $wpdb->prefix . 'autoanosis_test_results';
                if ($wpdb->get_var("SHOW TABLES LIKE '$test_results_table'") === $test_results_table) {
                    $test_results = $wpdb->get_results($wpdb->prepare(
                        "SELECT id, user_id, test_date, test_name, result_value, unit, reference_range, test_type, doctor_name, notes, created_at
                        FROM $test_results_table
                        WHERE user_id = %d
                        ORDER BY test_date DESC, created_at DESC
                        LIMIT 50",
                        $user_id
                    ), ARRAY_A);
                    if (!empty($test_results)) {
                        $snapshot['test_results'] = $test_results;
                        error_log('[AUTOANOSIS EXAMS] FALLBACK (v5.8): raw test_results for user ' . $user_id);
                    }
                }
            }
        } else {
            // autoanosis-exams-bridge plugin not active — use raw table as emergency fallback
            $test_results_table = $wpdb->prefix . 'autoanosis_test_results';
            if ($wpdb->get_var("SHOW TABLES LIKE '$test_results_table'") === $test_results_table) {
                $test_results = $wpdb->get_results($wpdb->prepare(
                    "SELECT id, user_id, test_date, test_name, result_value, unit, reference_range, test_type, doctor_name, notes, created_at
                    FROM $test_results_table
                    WHERE user_id = %d
                    ORDER BY test_date DESC, created_at DESC
                    LIMIT 50",
                    $user_id
                ), ARRAY_A);
                if (!empty($test_results)) {
                    $snapshot['test_results'] = $test_results;
                    error_log('[AUTOANOSIS EXAMS] EMERGENCY FALLBACK (v5.8): exams bridge not active for user ' . $user_id);
                }
            }
        }
        
        // 8. Get health notes
        $notes_table = $wpdb->prefix . 'autoanosis_health_notes';
        if ($wpdb->get_var("SHOW TABLES LIKE '$notes_table'") === $notes_table) {
            $notes = $wpdb->get_results($wpdb->prepare(
                "SELECT * FROM $notes_table WHERE user_id = %d ORDER BY created_at DESC LIMIT 10",
                $user_id
            ), ARRAY_A);
            
            if (!empty($notes)) {
                $snapshot['health_notes'] = $notes;
            }
        }
        
        // 9. Get medication reminders
        $reminders_table = $wpdb->prefix . 'autoanosis_medication_reminders';
        if ($wpdb->get_var("SHOW TABLES LIKE '$reminders_table'") === $reminders_table) {
            $reminders = $wpdb->get_results($wpdb->prepare(
                "SELECT * FROM $reminders_table WHERE user_id = %d AND status IN ('pending','sent') ORDER BY reminder_time DESC",
                $user_id
            ), ARRAY_A);
            
            if (!empty($reminders)) {
                $snapshot['medication_reminders'] = $reminders;
            }
        }
        
        
    // --- BEST Protocol (B.E.S.T. = Baseline • Events • Symptoms • Targets) ---
    // Stored server-side in user_meta (various historical keys). get_user_meta() unserializes automatically.
    $best = get_user_meta($user_id, 'autoanosis_best_protocol_last', true);
    if (empty($best)) {
        $best = get_user_meta($user_id, 'autoanosis_medical_snapshot_last', true);
    }
    if (empty($best)) {
        $best = get_user_meta($user_id, 'autoanosis_medical_snapshot_last_v2', true);
    }
    // Some versions store wrapper array like: ['source'=>..., 'payload'=>..., 'timestamp'=>...]
    if (is_array($best) && isset($best['payload']) && is_array($best['payload'])) {
        $best = $best['payload'];
    }
    // Defensive unserialize for edge cases where meta is stored as a raw serialized string
    if (is_string($best)) {
        $tmp = @unserialize($best);
        if ($tmp !== false || $best === 'b:0;') {
            $best = $tmp;
        }
    }

    if (is_array($best) && !empty($best)) {
        $snapshot['best_protocol'] = $best;

        // Full human-readable summary — ALL fields exposed to AI
        $best_lines = array();
        if (!empty($best['visit_date']))      { $best_lines[] = 'Ημερομηνία ραντεβού: ' . $best['visit_date']; }
        if (!empty($best['visit_doctor']))    { $best_lines[] = 'Ιατρός/Ειδικότητα: ' . $best['visit_doctor']; }
        if (!empty($best['visit_goal']))      { $best_lines[] = 'Κύριος στόχος επίσκεψης: ' . $best['visit_goal']; }
        if (!empty($best['visit_period']))    { $best_lines[] = 'Περίοδος αναφοράς: ' . $best['visit_period'] . ' ημέρες'; }
        // B — Baseline
        if (!empty($best['b_meds']))          { $best_lines[] = 'B - Φάρμακα/Δοσολογία: ' . $best['b_meds']; }
        if (!empty($best['b_notes']))         { $best_lines[] = 'B - Σημειώσεις baseline: ' . $best['b_notes']; }
        if (!empty($best['b_labs']))          { $best_lines[] = 'B - Εξετάσεις/Trend: ' . $best['b_labs']; }
        if (!empty($best['b_weight']))        { $best_lines[] = 'B - Βάρος: ' . $best['b_weight']; }
        if (!empty($best['b_bp']))            { $best_lines[] = 'B - Πίεση: ' . $best['b_bp']; }
        // E — Events
        if (!empty($best['e_infections']))    { $best_lines[] = 'E - Λοιμώξεις/Συμβάντα: ' . $best['e_infections']; }
        if (!empty($best['e_stress']))        { $best_lines[] = 'E - Στρεσογόνα γεγονότα: ' . $best['e_stress']; }
        if (!empty($best['e_travel']))        { $best_lines[] = 'E - Ταξίδια: ' . $best['e_travel']; }
        if (!empty($best['e_other']))         { $best_lines[] = 'E - Άλλα γεγονότα: ' . $best['e_other']; }
        // S — Symptoms (up to 5)
        for ($si = 1; $si <= 5; $si++) {
            $s_name  = $best['s' . $si . '_name']  ?? '';
            $s_vas   = $best['s' . $si . '_vas']   ?? '';
            $s_worse = $best['s' . $si . '_worse'] ?? '';
            $s_better= $best['s' . $si . '_better']?? '';
            if (!empty($s_name)) {
                $s_line = 'S' . $si . ' - Σύμπτωμα: ' . $s_name;
                if (!empty($s_vas))    { $s_line .= ' (VAS=' . $s_vas . ')'; }
                if (!empty($s_worse))  { $s_line .= ' | Χειροτερεύει: ' . $s_worse; }
                if (!empty($s_better)) { $s_line .= ' | Βελτιώνεται: ' . $s_better; }
                $best_lines[] = $s_line;
            }
        }
        // T — Targets
        if (!empty($best['t_qol']))           { $best_lines[] = 'T - Στόχοι ποιότητας ζωής: ' . $best['t_qol']; }
        if (!empty($best['t_plan']))          { $best_lines[] = 'T - Πλάνο/Ερωτήσεις για γιατρό: ' . $best['t_plan']; }
        if (!empty($best['t_questions']))     { $best_lines[] = 'T - Ερωτήσεις: ' . $best['t_questions']; }

        if (!empty($best_lines)) {
            $snapshot['best_summary'] = implode("\n", $best_lines);
        }
    }

    // --- BEST Protocol History v5.8.0 (3 sources: official + legacy + latest) ---
    // Merged from autoanosis-v17-debug5-BEST-HISTORY-FIXED2
    // Loads from ALL available sources, de-duplicates, sorts desc, keeps last 10
    $best_history_merged = array();

    // Source 1: Official history meta (autoanosis_medical_snapshot_history)
    $best_meta_history = get_user_meta($user_id, 'autoanosis_medical_snapshot_history', true);
    if (is_array($best_meta_history)) {
        foreach ($best_meta_history as $h) {
            if (!is_array($h)) continue;
            $payload = (isset($h['payload']) && is_array($h['payload'])) ? $h['payload'] : $h;
            $ts  = isset($h['timestamp']) ? intval($h['timestamp']) : 0;
            $src = isset($h['source'])    ? sanitize_text_field($h['source']) : 'BEST_PROTOCOL';
            if (!is_array($payload) || empty($payload)) continue;
            $best_history_merged[] = array('source' => $src, 'timestamp' => $ts, 'payload' => $payload);
        }
    }

    // Source 2: Legacy history meta (autoanosis_best_history)
    $legacy_best_history = get_user_meta($user_id, 'autoanosis_best_history', true);
    if (is_array($legacy_best_history)) {
        foreach ($legacy_best_history as $h) {
            if (!is_array($h)) continue;
            // Support both {ts, payload} and {timestamp, payload} formats
            $payload = isset($h['payload']) && is_array($h['payload']) ? $h['payload'] : null;
            if (empty($payload)) continue;
            $ts  = isset($h['ts'])     ? intval($h['ts'])                          :
                   (isset($h['timestamp']) ? intval($h['timestamp']) : 0);
            $src = isset($h['source']) ? sanitize_text_field($h['source'])         : 'BEST_PROTOCOL';
            $best_history_merged[] = array('source' => $src, 'timestamp' => $ts, 'payload' => $payload);
        }
    }

    // Source 3: Always include the latest BEST entry (from best_protocol loaded above)
    if (!empty($best) && is_array($best)) {
        $best_last_meta = get_user_meta($user_id, 'autoanosis_medical_snapshot_last_v2', true);
        if (empty($best_last_meta)) {
            $best_last_meta = get_user_meta($user_id, 'autoanosis_medical_snapshot_last', true);
        }
        $best_last_ts  = 0;
        $best_last_src = 'BEST_PROTOCOL';
        if (is_array($best_last_meta)) {
            if (isset($best_last_meta['timestamp'])) $best_last_ts  = intval($best_last_meta['timestamp']);
            if (isset($best_last_meta['source']))    $best_last_src = sanitize_text_field($best_last_meta['source']);
        }
        $best_history_merged[] = array('source' => $best_last_src, 'timestamp' => $best_last_ts, 'payload' => $best);
    }

    // De-dup by (timestamp + payload hash), sort desc, keep last 10
    $dedup_keys = array();
    $best_uniq  = array();
    foreach ($best_history_merged as $h) {
        if (!is_array($h) || empty($h['payload'])) continue;
        $ts    = isset($h['timestamp']) ? intval($h['timestamp']) : 0;
        $phash = md5(wp_json_encode($h['payload']));
        $k     = $ts . '|' . $phash;
        if (isset($dedup_keys[$k])) continue;
        $dedup_keys[$k] = true;
        $best_uniq[] = $h;
    }
    usort($best_uniq, function($a, $b) {
        $ta = isset($a['timestamp']) ? intval($a['timestamp']) : 0;
        $tb = isset($b['timestamp']) ? intval($b['timestamp']) : 0;
        return $tb - $ta; // descending
    });
    $best_uniq = array_slice($best_uniq, 0, 10);

    if (!empty($best_uniq)) {
        $snapshot['best_history']       = $best_uniq;
        $snapshot['best_history_count'] = count($best_uniq);
    }

// Always set medical snapshot (even if empty, for consistency)
        $medical_snapshot = $snapshot;
    }
    
    // Build request body
    $request_body = array(
        'message' => $message
    );
    
    if ( !empty($identity_token) ) {
        $request_body['identity_token'] = $identity_token;
    }
    
    if ( !empty($medical_snapshot) ) {
        $request_body['medical_snapshot'] = $medical_snapshot;
    }
    
    if ( !empty($conversation_id) ) {
        $request_body['conversation_id'] = $conversation_id;
    }
    
    // Log the request
    error_log('=== AUTOANOSIS CHAT PROXY ===');
    error_log('Message length: ' . strlen($message));
    error_log('Has identity token: ' . (!empty($identity_token) ? 'YES' : 'NO'));
    error_log('Has medical snapshot: ' . (!empty($medical_snapshot) ? 'YES' : 'NO'));
    error_log('Conversation ID: ' . ($conversation_id ?: 'NEW'));
    
    // Make request to Render backend with extended timeout
    $response = wp_remote_post('https://autoanosis-ai-backend.onrender.com/chat', array(
        'headers' => array(
            'Content-Type' => 'application/json'
        ),
        'body' => wp_json_encode($request_body),
        'timeout' => 60, // 60 seconds timeout for AI processing
        'sslverify' => true
    ));
    
    // Handle errors
    if ( is_wp_error($response) ) {
        $error_message = $response->get_error_message();
        error_log('Chat proxy error: ' . $error_message);
        
        return new WP_Error(
            'backend_error',
            'Failed to connect to AI backend: ' . $error_message,
            array('status' => 503)
        );
    }
    
    // Get response code and body
    $response_code = wp_remote_retrieve_response_code($response);
    $response_body = wp_remote_retrieve_body($response);
    
    // Log response
    $response_time = microtime(true) - $start_time;
    error_log('Response code: ' . $response_code);
    error_log('Response time: ' . round($response_time, 2) . 's');
    error_log('=== END CHAT PROXY ===');
    
    // Handle non-200 responses
    if ( $response_code !== 200 ) {
        return new WP_Error(
            'backend_error',
            'AI backend returned error: ' . $response_code,
            array('status' => $response_code)
        );
    }
    
    // Parse and return response
    $data = json_decode($response_body, true);
    
    if ( json_last_error() !== JSON_ERROR_NONE ) {
        return new WP_Error(
            'invalid_response',
            'Invalid JSON response from backend',
            array('status' => 502)
        );
    }
    
    // Add response time to data
    if ( is_array($data) ) {
        $data['proxy_response_time'] = round($response_time, 2);
    }
    
    return $data;
}
