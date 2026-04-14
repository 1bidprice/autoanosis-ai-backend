<?php
/*
Plugin Name: Autoanosis Doctor Dashboard Rescue Stable
Description: Production build for Autoanosis doctor workflow. Horizontal lab-style table display with units, reference ranges, and abnormal flags. AI normalizer integration via Render backend. Legacy user_meta exam parsing removed (v11.0.0).
Version: 11.0.0
Author: Autoanosis Team
*/

if (!defined('ABSPATH')) { exit; }

final class Autoanosis_Doctor_Dashboard_Rescue_Stable {
    private static $instance = null;
    private $requests_table;
    private $assignments_table;
    private $audit_table;

    public static function instance() {
        if (self::$instance === null) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    private function __construct() {
        global $wpdb;
        $this->requests_table    = $wpdb->prefix . 'autoanosis_doctor_requests';
        $this->assignments_table = $wpdb->prefix . 'autoanosis_doctor_assignments';
        $this->audit_table       = $wpdb->prefix . 'autoanosis_doctor_audit';

        add_action('init', array($this, 'register_role'));
        add_action('init', array($this, 'handle_actions'));
        add_action('wp_enqueue_scripts', array($this, 'enqueue_assets'));
        add_filter('body_class', array($this, 'add_app_webview_body_class'));

        add_shortcode('autoanosis_doctor_dashboard', array($this, 'render_doctor_dashboard'));
        add_shortcode('autoanosis_doctor_connect', array($this, 'render_patient_request_form'));
        add_shortcode('autoanosis_doctor_connections', array($this, 'render_patient_connections'));
        add_shortcode('autoanosis_connect_doctor', array($this, 'render_patient_request_form'));
        add_shortcode('autoanosis_my_doctor', array($this, 'render_patient_connections'));

        add_action('admin_post_autoanosis_doctor_download_report', array($this, 'download_doctor_report'));
        add_action('admin_post_nopriv_autoanosis_doctor_download_report', array($this, 'download_doctor_report'));
    }

    public static function activate() {
        self::instance()->register_role();
        self::instance()->create_tables();
        flush_rewrite_rules();
    }

    public static function deactivate() {
        flush_rewrite_rules();
    }

    public function register_role() {
        if (!get_role('autoanosis_doctor')) {
            add_role('autoanosis_doctor', 'Autoanosis Doctor', array('read' => true));
        }
    }

    private function create_tables() {
        global $wpdb;
        require_once ABSPATH . 'wp-admin/includes/upgrade.php';
        $charset = $wpdb->get_charset_collate();

        $sql1 = "CREATE TABLE {$this->requests_table} (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            patient_id BIGINT UNSIGNED NOT NULL,
            doctor_id BIGINT UNSIGNED NOT NULL,
            consent_text LONGTEXT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            KEY patient_id (patient_id),
            KEY doctor_id (doctor_id),
            KEY status (status)
        ) {$charset};";

        $sql2 = "CREATE TABLE {$this->assignments_table} (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            patient_id BIGINT UNSIGNED NOT NULL,
            doctor_id BIGINT UNSIGNED NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE KEY patient_doctor (patient_id, doctor_id),
            KEY doctor_id (doctor_id),
            KEY patient_id (patient_id),
            KEY status (status)
        ) {$charset};";

        $sql3 = "CREATE TABLE {$this->audit_table} (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            actor_id BIGINT UNSIGNED NULL,
            actor_type VARCHAR(20) NOT NULL,
            patient_id BIGINT UNSIGNED NULL,
            doctor_id BIGINT UNSIGNED NULL,
            action VARCHAR(100) NOT NULL,
            details LONGTEXT NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            KEY actor_id (actor_id),
            KEY patient_id (patient_id),
            KEY doctor_id (doctor_id),
            KEY action (action)
        ) {$charset};";

        dbDelta($sql1);
        dbDelta($sql2);
        dbDelta($sql3);
    }

    public function enqueue_assets() {
        $css = '
        *,*::before,*::after{box-sizing:border-box}
        .aodd-wrap{display:grid;gap:20px;max-width:100%;overflow-x:hidden}
        .aodd-card{background:#fff;border:1px solid #e9e9f3;border-radius:20px;padding:20px;box-shadow:0 10px 28px rgba(14,20,64,.06);max-width:100%;overflow:hidden}
        .aodd-title{margin:0 0 12px;font-size:30px;line-height:1.15;font-weight:800;color:#1f2233}
        .aodd-subtitle{margin:0 0 16px;color:#62667a}
        .aodd-grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:16px}
        .aodd-col-12{grid-column:span 12}.aodd-col-6{grid-column:span 6}.aodd-col-4{grid-column:span 4}.aodd-col-3{grid-column:span 3}
        .aodd-stat{padding:16px;border:1px solid #ececf5;border-radius:16px;background:#fcfcff}
        .aodd-stat strong{display:block;font-size:14px;color:#656a7c;margin-bottom:6px}
        .aodd-stat span{font-size:28px;font-weight:800;color:#1f2233}
        .aodd-label{display:block;font-weight:700;margin:0 0 6px;color:#1f2233}
        .aodd-input,.aodd-textarea{width:100%;box-sizing:border-box;border:1px solid #cfd4df;border-radius:12px;padding:12px 14px;background:#fff;font-size:15px}
        .aodd-textarea{min-height:100px;resize:vertical}
        .aodd-btn{display:inline-block;background:#6f55f2;color:#fff !important;border:none;border-radius:12px;padding:12px 16px;font-weight:800;text-decoration:none;cursor:pointer}
        .aodd-btn-green{background:#12b76a}.aodd-btn-red{background:#e5484d}.aodd-btn-blue{background:#1992ff}
        .aodd-row{display:flex;gap:10px;flex-wrap:wrap}
        .aodd-notice{padding:12px 14px;border-radius:12px;font-weight:700}.aodd-success{background:#edfdf3;color:#157347}.aodd-warning{background:#fff7e6;color:#b54708}.aodd-error{background:#fff1f2;color:#b42318}
        .aodd-list{display:grid;gap:12px}.aodd-item{border:1px solid #ececf5;border-radius:16px;padding:16px;background:#fff}
        .aodd-item-head{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;flex-wrap:wrap}
        .aodd-item-name{font-weight:800;font-size:18px;color:#1f2233}.aodd-meta{color:#62667a;font-size:14px}
        .aodd-table{width:100%;border-collapse:collapse;min-width:740px}.aodd-table th,.aodd-table td{padding:10px;border-bottom:1px solid #ececf5;text-align:left;vertical-align:top}.aodd-table th{font-size:13px;color:#62667a}
        .aodd-table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;width:100%}
        .aodd-section-title{margin:0 0 12px;font-size:24px;font-weight:800;color:#1f2233}.aodd-small{font-size:13px;color:#62667a}.aodd-empty{color:#62667a;margin:0}
        .aodd-report{border:1px solid #ececf5;border-radius:16px;padding:14px;background:#fcfcff;margin-bottom:12px}
        .aodd-report h4{margin:0 0 10px;font-size:18px}.aodd-kv{display:grid;gap:8px}.aodd-kv div{border:1px solid #ececf5;border-radius:10px;padding:8px 10px;background:#fff}
        .aodd-meds{display:grid;gap:14px}.aodd-med{border:1px solid #ececf5;border-radius:16px;padding:14px;background:#fff}
        .aodd-raw details{border:1px solid #ececf5;border-radius:14px;margin-bottom:10px;background:#fff}.aodd-raw summary{cursor:pointer;padding:12px 14px;font-weight:800}.aodd-raw pre{white-space:pre-wrap;word-break:break-word;margin:0;padding:14px;background:#fcfcff;border-top:1px solid #ececf5;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:13px;line-height:1.55}
        .aodd-raw-head{padding:0 14px 12px;color:#62667a;font-size:13px}
        .aodd-report-head{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}
        .aodd-badge{display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border-radius:999px;background:#eef4ff;color:#2457d6;font-size:12px;font-weight:800}
        .aodd-meta-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-bottom:12px}
        .aodd-meta-pill{border:1px solid #ececf5;border-radius:12px;padding:10px 12px;background:#fff}
        .aodd-meta-pill strong{display:block;font-size:12px;color:#62667a;margin-bottom:4px}
        .aodd-lab-block{border:1px solid #ececf5;border-radius:14px;background:#fff;margin-bottom:12px;overflow:hidden}
        .aodd-lab-block-title{padding:10px 12px;background:#f7f8fc;border-bottom:1px solid #ececf5;font-size:14px;font-weight:800;color:#1f2233}
        .aodd-lab-table{width:100%;border-collapse:collapse}
        .aodd-lab-table th,.aodd-lab-table td{padding:10px 12px;border-bottom:1px solid #ececf5;vertical-align:top;text-align:left}
        .aodd-lab-table th{width:34%;font-size:13px;font-weight:700;color:#2b3145;background:#fcfcff}
        .aodd-lab-table tr:last-child th,.aodd-lab-table tr:last-child td{border-bottom:none}
        .aodd-pretty-date{font-variant-numeric:tabular-nums}
        .aodd-hz-table{width:100%;border-collapse:collapse;min-width:700px}
        .aodd-hz-table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;width:100%}
        .aodd-hz-table thead th{padding:10px 12px;background:#f7f8fc;border-bottom:2px solid #dde0ed;font-size:12px;font-weight:800;color:#62667a;text-transform:uppercase;letter-spacing:.3px;text-align:left}
        .aodd-hz-table tbody td{padding:10px 12px;border-bottom:1px solid #ececf5;font-size:14px;color:#1f2233;vertical-align:middle}
        .aodd-hz-table tbody tr:last-child td{border-bottom:none}
        .aodd-hz-table tbody tr:hover{background:#f9f9ff}
        .aodd-hz-table .aodd-flag-high{color:#e5484d;font-weight:800}
        .aodd-hz-table .aodd-flag-low{color:#2457d6;font-weight:800}
        .aodd-hz-table .aodd-flag-critical{color:#fff;background:#e5484d;padding:2px 8px;border-radius:6px;font-weight:800;font-size:12px}
        .aodd-hz-table .aodd-flag-normal{color:#12b76a;font-weight:700}
        .aodd-hz-table .aodd-val-cell{font-variant-numeric:tabular-nums;font-weight:700}
        .aodd-hz-table .aodd-ref-cell{color:#62667a;font-size:13px}
        .aodd-hz-table .aodd-unit-cell{color:#62667a;font-size:13px}
        .aodd-confidence-bar{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:#62667a}
        .aodd-confidence-bar .aodd-bar{width:60px;height:6px;background:#ececf5;border-radius:3px;overflow:hidden}
        .aodd-confidence-bar .aodd-bar-fill{height:100%;border-radius:3px}
        .aodd-needs-review{display:inline-flex;align-items:center;gap:4px;padding:4px 10px;border-radius:999px;background:#fff7e6;color:#b54708;font-size:12px;font-weight:800}
        .aodd-review-banner{background:#fff7e6;border:1px solid #f5c97a;border-radius:10px;padding:10px 14px;margin-bottom:10px;display:flex;align-items:center;gap:8px;font-size:13px;color:#b54708;font-weight:700}
        .aodd-review-banner .aodd-review-icon{font-size:18px}
        .aodd-confidence-indicator{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:#62667a}
        .aodd-confidence-indicator .aodd-conf-bar{width:50px;height:5px;background:#ececf5;border-radius:3px;overflow:hidden;display:inline-block}
        .aodd-confidence-indicator .aodd-conf-fill{height:100%;border-radius:3px}
        .aodd-conf-high{background:#30a46c}
        .aodd-conf-medium{background:#f5a623}
        .aodd-conf-low{background:#e5484d}
        @media (max-width: 900px){.aodd-col-6,.aodd-col-4,.aodd-col-3{grid-column:span 12}.aodd-title{font-size:26px}.aodd-meta-grid{grid-template-columns:1fr}}
        @media (max-width: 768px){
          .aodd-wrap{gap:12px}
          .aodd-card{padding:14px;border-radius:14px}
          .aodd-col-12,.aodd-col-6,.aodd-col-4,.aodd-col-3{grid-column:span 12}
          .aodd-grid{gap:10px}
          .aodd-title{font-size:22px}
          .aodd-section-title{font-size:18px}
          .aodd-stat span{font-size:22px}
          .aodd-stat{padding:12px}
          .aodd-meta-grid{grid-template-columns:1fr}
          .aodd-report-head{flex-direction:column;align-items:flex-start;gap:8px}
          .aodd-report-head h4{font-size:16px;margin-bottom:4px}
          .aodd-report-head>div{display:flex;flex-wrap:wrap;gap:6px;width:100%}
          .aodd-badge{font-size:11px;padding:5px 8px}
          .aodd-confidence-indicator{font-size:11px}
          .aodd-needs-review{font-size:11px}
          .aodd-review-banner{font-size:12px;padding:8px 12px}
          .aodd-item-head{flex-direction:column;gap:8px}
          .aodd-item-name{font-size:16px}
          .aodd-meta{font-size:13px}
          .aodd-lab-table th{width:40%;font-size:12px;padding:8px 10px}
          .aodd-lab-table td{font-size:13px;padding:8px 10px}
          .aodd-btn{padding:10px 14px;font-size:14px}
          .aodd-row{gap:8px}
          .aodd-input,.aodd-textarea{font-size:14px;padding:10px 12px}
          .aodd-wrap{padding-bottom:env(safe-area-inset-bottom,80px)}
        }
        @media (max-width: 700px){.aodd-card{padding:14px}.aodd-title{font-size:20px}.aodd-section-title{font-size:17px}.aodd-stat span{font-size:20px}}
        body.autoa-app-webview header.header,
        body.autoa-app-webview .nv-navbar,
        body.autoa-app-webview footer#site-footer,
        body.autoa-app-webview #wpadminbar,
        body.autoa-app-webview #autoa-assistant,
        body.autoa-app-webview #cmplz-cookiebanner-container
        {display:none!important;visibility:hidden!important;pointer-events:none!important}
        body.autoa-app-webview{overflow-x:hidden!important;padding-top:0!important;margin-top:0!important}
        body.autoa-app-webview .neve-main{padding-top:8px!important}
        body.autoa-app-webview .aodd-wrap{padding-bottom:calc(env(safe-area-inset-bottom,0px) + 80px)!important}
        body.autoa-app-webview *{max-width:100vw;box-sizing:border-box}
        ';
        wp_register_style('aodd-rescue-style', false);
        wp_enqueue_style('aodd-rescue-style');
        wp_add_inline_style('aodd-rescue-style', $css);
    }

    public function add_app_webview_body_class($classes) {
        if (!empty($_GET['app_mode'])) {
            $classes[] = 'autoa-app-webview';
        }
        return $classes;
    }

    private function notice($msg, $type) {
        return '<div class="aodd-notice aodd-' . esc_attr($type) . '">' . esc_html($msg) . '</div>';
    }

    private function user_can_doctor_access($user_id) {
        $user = get_userdata($user_id);
        if (!$user) { return false; }
        $roles = (array) $user->roles;
        if (in_array('autoanosis_doctor', $roles, true)) { return true; }
        if (user_can($user_id, 'manage_options')) { return true; }
        if (user_can($user_id, 'edit_pages')) { return true; }
        return false;
    }

    private function current_user_can_doctor_access() {
        return is_user_logged_in() && $this->user_can_doctor_access(get_current_user_id());
    }

    private function assignment_exists($patient_id, $doctor_id) {
        global $wpdb;
        $row = $wpdb->get_var($wpdb->prepare("SELECT id FROM {$this->assignments_table} WHERE patient_id=%d AND doctor_id=%d AND status='active' LIMIT 1", $patient_id, $doctor_id));
        return !empty($row);
    }

    private function request_exists($patient_id, $doctor_id) {
        global $wpdb;
        $row = $wpdb->get_var($wpdb->prepare("SELECT id FROM {$this->requests_table} WHERE patient_id=%d AND doctor_id=%d AND status='pending' LIMIT 1", $patient_id, $doctor_id));
        return !empty($row);
    }

    private function pull_notice($key) {
        if (empty($_GET[$key])) { return ''; }
        $message = rawurldecode((string) $_GET[$key]);
        $type = sanitize_key((string) ($_GET[$key . '_type'] ?? 'success'));
        if (!in_array($type, array('success', 'warning', 'error'), true)) {
            $type = 'success';
        }
        return $this->notice($message, $type);
    }

    private function redirect_back_with_notice($key, $message, $type) {
        $url = wp_get_referer() ? wp_get_referer() : home_url('/');
        $url = add_query_arg(array($key => rawurlencode($message), $key . '_type' => $type), $url);
        wp_safe_redirect($url);
        exit;
    }

    public function handle_actions() {
        if (!is_user_logged_in()) { return; }
        if (isset($_POST['aodd_send_request'])) { $this->handle_send_request(); }
        if (isset($_POST['aodd_request_action'])) { $this->handle_request_action(); }
        if (isset($_POST['aodd_revoke_connection'])) { $this->handle_revoke(); }
        if (isset($_POST['aodd_save_medication'])) { $this->handle_medication_save(); }
        if (isset($_POST['aodd_add_medication'])) { $this->handle_medication_add(); }
    }

    private function send_mail($to, $subject, $body) {
        return wp_mail($to, $subject, $body, array('Content-Type: text/plain; charset=UTF-8'));
    }

    private function add_audit($actor_id, $actor_type, $patient_id, $doctor_id, $action, $details = array()) {
        global $wpdb;
        $wpdb->insert(
            $this->audit_table,
            array(
                'actor_id' => $actor_id,
                'actor_type' => $actor_type,
                'patient_id' => $patient_id,
                'doctor_id' => $doctor_id,
                'action' => $action,
                'details' => !empty($details) ? wp_json_encode($details, JSON_UNESCAPED_UNICODE) : null,
                'created_at' => current_time('mysql'),
            ),
            array('%d','%s','%d','%d','%s','%s','%s')
        );
    }

    private function handle_send_request() {
        if (!wp_verify_nonce($_POST['_wpnonce'] ?? '', 'aodd_send_request')) { return; }

        $patient_id = get_current_user_id();
        if ($this->user_can_doctor_access($patient_id)) {
            $this->redirect_back_with_notice('aodd_connect_notice', 'Η φόρμα σύνδεσης είναι μόνο για ασθενείς.', 'error');
        }

        $doctor_email = sanitize_email((string) ($_POST['doctor_email'] ?? ''));
        $consent = !empty($_POST['doctor_consent']);

        if (!$doctor_email || !$consent) {
            $this->redirect_back_with_notice('aodd_connect_notice', 'Συμπλήρωσε email γιατρού και αποδοχή συγκατάθεσης.', 'error');
        }

        $doctor = get_user_by('email', $doctor_email);
        if (!$doctor) {
            $this->redirect_back_with_notice('aodd_connect_notice', 'Δεν βρέθηκε λογαριασμός με αυτό το email.', 'error');
        }

        if (!$this->user_can_doctor_access((int) $doctor->ID)) {
            $this->redirect_back_with_notice('aodd_connect_notice', 'Ο χρήστης υπάρχει αλλά δεν έχει πρόσβαση γιατρού.', 'error');
        }

        if ($this->assignment_exists($patient_id, (int) $doctor->ID)) {
            $this->redirect_back_with_notice('aodd_connect_notice', 'Ο γιατρός είναι ήδη συνδεδεμένος με το προφίλ σου.', 'warning');
        }

        if ($this->request_exists($patient_id, (int) $doctor->ID)) {
            $this->redirect_back_with_notice('aodd_connect_notice', 'Υπάρχει ήδη εκκρεμές αίτημα προς αυτόν τον γιατρό.', 'warning');
        }

        global $wpdb;
        $wpdb->insert(
            $this->requests_table,
            array(
                'patient_id' => $patient_id,
                'doctor_id' => (int) $doctor->ID,
                'consent_text' => 'Ο ασθενής δίνει πρόσβαση στο doctor dashboard, στο structured health profile και στο My Medications μέχρι ανάκλησης.',
                'status' => 'pending',
                'created_at' => current_time('mysql'),
                'updated_at' => current_time('mysql'),
            ),
            array('%d','%d','%s','%s','%s','%s')
        );

        $this->add_audit($patient_id, 'patient', $patient_id, (int) $doctor->ID, 'request_created');
        $patient = get_userdata($patient_id);
        $subject = 'Νέο αίτημα σύνδεσης ασθενούς — Autoanosis';
        $body = "Έχεις νέο αίτημα σύνδεσης στο Autoanosis.\n\nΑσθενής: " . ($patient ? $patient->display_name : 'Ασθενής') . "\nEmail: " . ($patient ? $patient->user_email : '') . "\n\nDashboard: " . home_url('/doctor-dashboard/');
        $sent = $this->send_mail($doctor->user_email, $subject, $body);

        if ($sent) {
            $this->redirect_back_with_notice('aodd_connect_notice', 'Το αίτημα στάλθηκε και ειδοποιήθηκε ο γιατρός.', 'success');
        }
        $this->redirect_back_with_notice('aodd_connect_notice', 'Το αίτημα καταχωρήθηκε αλλά το email δεν στάλθηκε.', 'warning');
    }

    private function handle_request_action() {
        if (!$this->current_user_can_doctor_access()) { return; }
        if (!wp_verify_nonce($_POST['_wpnonce'] ?? '', 'aodd_request_action')) { return; }

        $doctor_id = get_current_user_id();
        $request_id = absint($_POST['request_id'] ?? 0);
        $action = sanitize_key((string) ($_POST['aodd_request_action'] ?? ''));
        global $wpdb;

        $request = $wpdb->get_row($wpdb->prepare("SELECT * FROM {$this->requests_table} WHERE id=%d AND doctor_id=%d LIMIT 1", $request_id, $doctor_id));
        if (!$request || $request->status !== 'pending') { return; }

        if ($action === 'approve') {
            if (!$this->assignment_exists((int) $request->patient_id, $doctor_id)) {
                $wpdb->insert($this->assignments_table, array(
                    'patient_id' => (int) $request->patient_id,
                    'doctor_id' => $doctor_id,
                    'status' => 'active',
                    'created_at' => current_time('mysql'),
                    'updated_at' => current_time('mysql'),
                ), array('%d','%d','%s','%s','%s'));
            }
            $wpdb->update($this->requests_table, array('status' => 'approved', 'updated_at' => current_time('mysql')), array('id' => $request_id), array('%s','%s'), array('%d'));
            $this->add_audit($doctor_id, 'doctor', (int) $request->patient_id, $doctor_id, 'request_approved');
        } elseif ($action === 'reject') {
            $wpdb->update($this->requests_table, array('status' => 'rejected', 'updated_at' => current_time('mysql')), array('id' => $request_id), array('%s','%s'), array('%d'));
            $this->add_audit($doctor_id, 'doctor', (int) $request->patient_id, $doctor_id, 'request_rejected');
        }

        wp_safe_redirect(add_query_arg('aodd_doctor_notice', 'updated', wp_get_referer() ? wp_get_referer() : home_url('/doctor-dashboard/')));
        exit;
    }

    private function handle_revoke() {
        if (!wp_verify_nonce($_POST['_wpnonce'] ?? '', 'aodd_revoke')) { return; }
        $patient_id = get_current_user_id();
        $doctor_id = absint($_POST['doctor_id'] ?? 0);
        global $wpdb;

        $wpdb->update(
            $this->assignments_table,
            array('status' => 'revoked', 'updated_at' => current_time('mysql')),
            array('patient_id' => $patient_id, 'doctor_id' => $doctor_id, 'status' => 'active'),
            array('%s','%s'),
            array('%d','%d','%s')
        );
        $this->add_audit($patient_id, 'patient', $patient_id, $doctor_id, 'assignment_revoked');
        $this->redirect_back_with_notice('aodd_connections_notice', 'Η πρόσβαση ανακλήθηκε.', 'success');
    }

    private function handle_medication_add() {
        if (!$this->current_user_can_doctor_access()) { return; }
        if (!wp_verify_nonce($_POST['_wpnonce'] ?? '', 'aodd_add_medication')) { return; }

        $doctor_id = get_current_user_id();
        $patient_id = absint($_POST['patient_id'] ?? 0);
        if (!$this->assignment_exists($patient_id, $doctor_id)) { return; }

        $name = sanitize_text_field((string) ($_POST['med_name_new'] ?? ''));
        if ($name === '') {
            $this->redirect_back_with_notice('aodd_doctor_notice_custom', 'Χρειάζεται όνομα φαρμάκου.', 'error');
        }

        $bundle = $this->get_medications_bundle($patient_id);
        $meds = $bundle['items'];
        $new = array(
            'id' => 0,
            'source' => ($bundle['source_key'] === 'mm_medications' ? 'mm_table' : 'meta'),
            'name' => $name,
            'dose' => sanitize_text_field((string) ($_POST['med_dose_new'] ?? '')),
            'frequency' => sanitize_text_field((string) ($_POST['med_frequency_new'] ?? '')),
            'time' => sanitize_text_field((string) ($_POST['med_time_new'] ?? '')),
            'instructions' => sanitize_textarea_field((string) ($_POST['med_instructions_new'] ?? '')),
            'status' => 'active',
        );

        if ($bundle['source_key'] === 'mm_medications') {
            $this->persist_mm_medication($patient_id, $new, 0);
        }

        $meds[] = $new;
        $this->save_medications($patient_id, $meds, $bundle['source_key']);
        $this->add_audit($doctor_id, 'doctor', $patient_id, $doctor_id, 'medication_added', $new);

        wp_safe_redirect(add_query_arg(array('patient' => $patient_id, 'aodd_doctor_notice' => 'med_saved'), wp_get_referer() ? wp_get_referer() : home_url('/doctor-dashboard/')));
        exit;
    }
    private function handle_medication_save() {
        if (!$this->current_user_can_doctor_access()) { return; }
        if (!wp_verify_nonce($_POST['_wpnonce'] ?? '', 'aodd_save_medication')) { return; }

        $doctor_id = get_current_user_id();
        $patient_id = absint($_POST['patient_id'] ?? 0);
        $index = absint($_POST['med_index'] ?? -1);
        $source_key = sanitize_key((string) ($_POST['med_source_key'] ?? 'autoanosis_medications'));
        $med_row_id = absint($_POST['med_row_id'] ?? 0);
        if (!$this->assignment_exists($patient_id, $doctor_id)) { return; }

        $bundle = $this->get_medications_bundle($patient_id);
        $meds = $bundle['items'];
        if (!isset($meds[$index])) { return; }

        $meds[$index] = array(
            'id' => $med_row_id,
            'source' => ($source_key === 'mm_medications' ? 'mm_table' : 'meta'),
            'name' => sanitize_text_field((string) ($_POST['med_name'] ?? '')),
            'dose' => sanitize_text_field((string) ($_POST['med_dose'] ?? '')),
            'frequency' => sanitize_text_field((string) ($_POST['med_frequency'] ?? '')),
            'time' => sanitize_text_field((string) ($_POST['med_time'] ?? '')),
            'instructions' => sanitize_textarea_field((string) ($_POST['med_instructions'] ?? '')),
            'status' => sanitize_key((string) ($_POST['med_status'] ?? 'active')),
        );

        if ($source_key === 'mm_medications' && $med_row_id > 0) {
            $this->persist_mm_medication($patient_id, $meds[$index], $med_row_id);
        }
        $this->save_medications($patient_id, $meds, $source_key);
        $this->add_audit($doctor_id, 'doctor', $patient_id, $doctor_id, 'medication_updated', array('index' => $index));

        wp_safe_redirect(add_query_arg(array('patient' => $patient_id, 'aodd_doctor_notice' => 'med_saved'), wp_get_referer() ? wp_get_referer() : home_url('/doctor-dashboard/')));
        exit;
    }
    private function decode_maybe($value) {
        if (is_string($value)) {
            $json = json_decode($value, true);
            if (json_last_error() === JSON_ERROR_NONE) { return $json; }
            $maybe = @maybe_unserialize($value);
            if ($maybe !== false || $value === 'b:0;') { return $maybe; }
        }
        return $value;
    }

    private function mb_lower($text) {
        $text = (string) $text;
        return function_exists('mb_strtolower') ? mb_strtolower($text) : strtolower($text);
    }

    private function mb_length($text) {
        $text = (string) $text;
        return function_exists('mb_strlen') ? mb_strlen($text) : strlen($text);
    }
    private function clean_scalar_text($value) {
        if (is_array($value)) {
            $out = array();
            foreach ($value as $v) {
                $v = $this->clean_scalar_text($v);
                if ($v !== '') { $out[] = $v; }
            }
            return implode(', ', $out);
        }
        $value = html_entity_decode((string) $value, ENT_QUOTES | ENT_HTML5, 'UTF-8');
        $value = wp_unslash($value);
        $value = preg_replace('/\\\\+/u', '', $value);
        $value = preg_replace('/\s+/u', ' ', $value);
        return trim((string) $value);
    }

    private function normalize_time_value($value) {
        $value = $this->decode_maybe($value);
        if (is_array($value)) {
            $flat = array();
            foreach ($value as $v) {
                $v = $this->clean_scalar_text($v);
                $v = trim($v, "[]'\"");
                if ($v !== '') { $flat[] = $v; }
            }
            return implode(', ', $flat);
        }
        $value = $this->clean_scalar_text($value);
        if ($value === '') { return ''; }
        if ((substr($value, 0, 1) === '[' && substr($value, -1) === ']') || (substr($value, 0, 1) === '{' && substr($value, -1) === '}')) {
            $decoded = json_decode($value, true);
            if (json_last_error() === JSON_ERROR_NONE) {
                return $this->normalize_time_value($decoded);
            }
        }
        $value = preg_replace('/^[\[]|[\]]$/u', '', $value);
        $value = str_replace(array('"', "'"), '', $value);
        $parts = preg_split('/[,;]+/u', $value);
        if (is_array($parts) && count($parts) > 1) {
            $parts = array_values(array_filter(array_map('trim', $parts)));
            return implode(', ', $parts);
        }
        return trim($value);
    }


    private function table_exists($table_name) {
        global $wpdb;
        return $wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $table_name)) === $table_name;
    }

    private function table_columns($table_name) {
        global $wpdb;
        $cols = array();
        $rows = $wpdb->get_results("SHOW COLUMNS FROM {$table_name}", ARRAY_A);
        if (is_array($rows)) {
            foreach ($rows as $row) {
                if (!empty($row['Field'])) { $cols[] = $row['Field']; }
            }
        }
        return $cols;
    }

    private function select_existing_first($row, $candidates) {
        foreach ($candidates as $key) {
            if (isset($row[$key])) { return $row[$key]; }
        }
        return '';
    }

    private function normalize_display_datetime($value) {
        $value = trim((string) $value);
        if ($value === '') { return ''; }
        $value = preg_replace('/\s+/', ' ', $value);
        if (!preg_match('/^(?:\d{1,2}[\/\.-]\d{1,2}[\/\.-]\d{2,4})(?:\s+\d{1,2}:\d{2})?$/u', $value)) {
            return $value;
        }
        $normalized = str_replace('.', '/', $value);
        $ts = strtotime($normalized);
        if (!$ts) { return $value; }
        if (preg_match('/\d{1,2}:\d{2}/', $value)) {
            return date_i18n('d/m/Y H:i', $ts);
        }
        return date_i18n('d/m/Y', $ts);
    }

    private function extract_report_display_datetime($report) {
        // v11.0.0: Only reads from structured metadata. Raw fallback removed.
        $meta = (array) ($report['metadata'] ?? array());
        foreach (array('Ημ/νία εξέτασης','Ημερομηνία εξέτασης') as $mk) {
            if (!empty($meta[$mk])) {
                return $this->normalize_display_datetime($meta[$mk]);
            }
        }
        return '';
    }


    private function is_simple_scalar_value($line) {
        $line = trim((string) $line);
        if ($line === '') { return false; }
        $simple = array('ΟΧΙ','ΝΑΙ','ΑΡΝΗΤΙΚΟ','ΘΕΤΙΚΟ','ΚΙΤΡΙΝΗ','ΔΙΑΥΓΗΣ','ΑΡΡΕΝ','ΘΗΛΥ','MALE','FEMALE');
        if (in_array(mb_strtoupper($line, 'UTF-8'), $simple, true)) { return true; }
        if (preg_match('/^\d{1,2}[\/\.-]\d{1,2}[\/\.-]\d{2,4}(?:\s+\d{1,2}:\d{2})?$/u', $line)) { return true; }
        if (preg_match('/^\d+(?:[\.,]\d+)?(?:\s*[xX×]\s*10\^?\d+)?\s*(?:%|mg\/dl|ng\/ml|pg\/ml|mm\/h|g\/dL|g\/dl|fL|ml|μL|μl|OΠ|ΟΠ)?$/u', $line)) { return true; }
        return false;
    }


    private function get_condition($user_id) {
        $keys = array('autoimmune_type','autoa_condition','autoanosis_condition','autoanosis_conditions','condition','conditions');
        foreach ($keys as $key) {
            $val = get_user_meta($user_id, $key, true);
            $val = $this->decode_maybe($val);
            if (is_array($val)) {
                $parts = array_filter(array_map('trim', array_map('strval', $val)));
                if (!empty($parts)) { return implode(', ', array_unique($parts)); }
            }
            if (is_string($val) && trim($val) !== '') { return trim($val); }
        }
        return '—';
    }

    private function note_keys() {
        return array('autoanosis_clinical_notes','autoanosis_notes','medical_notes','doctor_notes');
    }

    private function is_noise_line($line) {
        // v11.0.0: Simplified — no longer depends on legacy parsing helpers.
        $line = $this->clean_scalar_text($line);
        if ($line === '') { return true; }
        if (preg_match('/^(author|date|status|purpose|mysql|pypdf2|natural language|generation|contextual responses|code snippet)\s*:?/iu', $line)) { return true; }
        if (preg_match('/^(https?:\/\/|wp-content\/|render\.com|openai api|javascript\/jquery|user interface|ocr text|samples\.)/iu', $line)) { return true; }
        return false;
    }

    private function get_clean_notes($user_id) {
        $notes = array();

        foreach ($this->note_keys() as $key) {
            $raw = get_user_meta($user_id, $key, true);
            if (is_string($raw) && trim($raw) !== '') {
                $parts = preg_split('/\r\n|\r|\n/u', $this->clean_scalar_text($raw));
                if (is_array($parts)) {
                    foreach ($parts as $part) {
                        $part = $this->clean_scalar_text($part);
                        if ($part === '' || $this->is_noise_line($part)) { continue; }
                        if (preg_match('/^(ονοματεπωνυμο|ημερ?ομηνια|κωδικος|φυλο|πατρωνυμο|amka|αμκα)\s*:?$/iu', $part)) { continue; }
                        $notes[] = $part;
                    }
                }
            }
        }

        // v11.0.0: Legacy report_keys note extraction removed.

        foreach ($this->get_recent_checkins($user_id, 5) as $row) {
            $note = $this->clean_scalar_text((string) ($row['notes'] ?? $row['comment'] ?? ''));
            if ($note === '' || $this->is_noise_line($note)) { continue; }
            $notes[] = $note;
        }

        $filtered = array();
        $seen = array();
        foreach ($notes as $note) {
            $note = trim($note, " •-\t\n\r\0\x0B");
            if ($note === '') { continue; }
            if ($this->mb_length($note) < 6 || $this->mb_length($note) > 220) { continue; }
            if (preg_match('/^(ονοματεπωνυμο|ημερ?\.?(?:εξετασης)?|κωδικος|φυλο|πατρωνυμο|amka|αμκα)\s*:?$/iu', $note)) { continue; }
            if (preg_match('/^(?:\d{1,2}[\/\.-]\d{1,2}[\/\.-]\d{2,4}(?:\s+\d{1,2}:\d{2})?|\d{6,})$/u', $note)) { continue; }
            $hash = md5($this->mb_lower($note));
            if (isset($seen[$hash])) { continue; }
            $seen[$hash] = true;
            $filtered[] = $note;
        }

        return array_slice($filtered, 0, 8);
    }
    private function label_is_date_like($label) {
        // v11.0.0: Inlined condensed_line logic (condensed_line removed with legacy stack)
        $label = mb_strtolower(preg_replace('/[^\p{L}]/u', '', (string) $label), 'UTF-8');
        if ($label === '') { return false; }
        foreach (array('ημερεξετασης','ημερομηνιαεξετασης','ημνιαεξετασης','ημγεννησης','ημνιαγεννησης','ημερομηνιαγεννησης','ημγεννησεως','ημγεννησησ','ημγεννησεωσ') as $needle) {
            if (strpos($label, $needle) !== false) { return true; }
        }
        return false;
    }

    /**
     * Get structured reports — SOLE source: Render backend via exams-bridge.
     *
     * v9.1.0 — Switched primary data source from user_meta to Render backend.
     * v11.0.0 — Legacy user_meta fallback removed. Render is the only source.
     */
    private function get_structured_reports($user_id) {
        // ── PRIMARY: Render backend via exams-bridge ──
        $render_reports = $this->fetch_reports_from_render($user_id);
        if (!empty($render_reports)) {
            return $render_reports;
        }

        // v11.0.0: Legacy user_meta fallback removed. Render backend is the sole source.
        // If Render is unavailable, return empty — the UI shows a clear "no data" message.
        return array();
    }

    /**
     * Fetch structured reports from Render backend and transform
     * them into the format expected by the dashboard renderer.
     *
     * Returns an array of report arrays compatible with render_report_sections(),
     * or an empty array if the Render backend is unavailable / returns no data.
     */
    private function fetch_reports_from_render($user_id) {
        if (!function_exists('autoanosis_exams_fetch_structured_reports')) {
            return array();
        }

        $data = autoanosis_exams_fetch_structured_reports($user_id);

        // WP_Error or non-array = backend unavailable
        if (is_wp_error($data) || !is_array($data)) {
            return array();
        }

        $api_reports = isset($data['reports']) ? $data['reports'] : $data;
        if (empty($api_reports) || !is_array($api_reports)) {
            return array();
        }

        $out = array();
        $index = 1;
        foreach ($api_reports as $r) {
            $out[] = $this->transform_render_report($r, $index);
            $index++;
        }
        return $out;
    }

    /**
     * Transform a single Render backend report into the format
     * expected by the dashboard renderer.
     *
     * v10.0.0 — Preserves full structured result data (value, unit, reference range,
     *           abnormal flag, clinical group) for horizontal lab-style table rendering.
     *           Also keeps backward-compatible 'sections' for legacy fallback.
     */
    private function transform_render_report($r, $index) {
        $category = isset($r['exam_category']) ? $r['exam_category'] : '';
        $exam_type = isset($r['exam_type']) ? $r['exam_type'] : '';

        // ── Title ──
        $title = 'Αναφορά #' . $index;
        if ($category !== '') {
            $title .= ': ' . $category;
        } elseif ($exam_type !== '') {
            $title .= ': ' . $exam_type;
        }

        // ── Metadata ──
        $metadata = array();
        if (!empty($r['performed_at'])) {
            $ts = strtotime($r['performed_at']);
            $metadata['Ημ/νία εξέτασης'] = $ts ? date('d/m/Y H:i', $ts) : $r['performed_at'];
        }
        if (!empty($r['lab_name'])) {
            $metadata['Εργαστήριο'] = $r['lab_name'];
        }
        if (!empty($r['ordering_doctor'])) {
            $metadata['Γιατρός'] = $r['ordering_doctor'];
        }
        if (!empty($r['confidence_score'])) {
            $metadata['Βαθμός εμπιστοσύνης'] = round($r['confidence_score'] * 100) . '%';
        }
        if (!empty($r['normalization_status'])) {
            $metadata['Κατάσταση'] = $r['normalization_status'];
        }

        // ── Structured results for horizontal table (v10.0.0) ──
        $structured_results = array();
        $results = isset($r['results']) && is_array($r['results']) ? $r['results'] : array();
        foreach ($results as $res) {
            $group = !empty($res['clinical_group']) ? $res['clinical_group'] : ($category !== '' ? $category : 'Αποτελέσματα');
            $structured_results[] = array(
                'display_name'   => isset($res['display_name']) ? $res['display_name'] : 'Τιμή',
                'value_numeric'  => isset($res['value_numeric']) ? $res['value_numeric'] : null,
                'value_text'     => isset($res['value_text']) ? $res['value_text'] : '',
                'unit'           => isset($res['unit']) ? $res['unit'] : '',
                'reference_low'  => isset($res['reference_low']) ? $res['reference_low'] : null,
                'reference_high' => isset($res['reference_high']) ? $res['reference_high'] : null,
                'reference_text' => isset($res['reference_text']) ? $res['reference_text'] : '',
                'abnormal_flag'  => isset($res['abnormal_flag']) ? $res['abnormal_flag'] : '',
                'clinical_group' => $group,
            );
        }

        // ── Legacy sections (backward compat for fallback renderer) ──
        $sections = array();
        foreach ($structured_results as $sr) {
            $group = $sr['clinical_group'];
            $value_parts = array();
            if ($sr['value_text'] !== '' && $sr['value_text'] !== null) {
                $value_parts[] = $sr['value_text'];
            } elseif ($sr['value_numeric'] !== null) {
                $value_parts[] = (string) $sr['value_numeric'];
            }
            if ($sr['unit'] !== '') { $value_parts[] = $sr['unit']; }
            $value = implode(' ', $value_parts);
            if ($sr['reference_text'] !== '') {
                $value .= ' (' . $sr['reference_text'] . ')';
            } elseif ($sr['reference_low'] !== null && $sr['reference_high'] !== null) {
                $value .= ' (' . $sr['reference_low'] . '-' . $sr['reference_high'] . ')';
            }
            if ($sr['abnormal_flag'] !== '') {
                $flag_map = array('high' => '↑', 'low' => '↓', 'critical' => '⚠');
                $flag = isset($flag_map[$sr['abnormal_flag']]) ? $flag_map[$sr['abnormal_flag']] : $sr['abnormal_flag'];
                $value .= ' ' . $flag;
            }
            if (!isset($sections[$group])) { $sections[$group] = array(); }
            $sections[$group][] = array('label' => $sr['display_name'], 'value' => $value);
        }

        // ── Impressions as a section ──
        $impressions = isset($r['impressions']) && is_array($r['impressions']) ? $r['impressions'] : array();
        if (!empty($impressions)) {
            $imp_pairs = array();
            foreach ($impressions as $imp) {
                $imp_label = !empty($imp['section_type']) ? ucfirst($imp['section_type']) : 'Σχόλιο';
                $imp_text = isset($imp['text']) ? $imp['text'] : '';
                if (!empty($imp['severity_flag'])) {
                    $imp_text .= ' [' . $imp['severity_flag'] . ']';
                }
                $imp_pairs[] = array('label' => $imp_label, 'value' => $imp_text);
            }
            $sections['Ευρήματα / Σχόλια'] = $imp_pairs;
        }

        return array(
            'title' => $title,
            'metadata' => $metadata,
            'sections' => $sections,
            'structured_results' => $structured_results,
            'confidence_score' => isset($r['confidence_score']) ? $r['confidence_score'] : null,
            'normalization_status' => isset($r['normalization_status']) ? $r['normalization_status'] : '',
            'raw' => '',
            'source' => 'render_api',
        );
    }

    private function normalize_medication_item($value) {
        $value = $this->decode_maybe($value);

        if (is_array($value)) {
            $status_raw = $value['status'] ?? ($value['active'] ?? 'active');
            if ($status_raw === 1 || $status_raw === '1' || $status_raw === true) {
                $status_raw = 'active';
            } elseif ($status_raw === 0 || $status_raw === '0' || $status_raw === false) {
                $status_raw = 'stopped';
            }

            return array(
                'id'           => absint($value['id'] ?? 0),
                'source'       => trim((string) ($value['source'] ?? 'meta')),
                'name'         => $this->clean_scalar_text($value['name'] ?? $value['medication'] ?? $value['drug'] ?? $value['title'] ?? $value['medication_name'] ?? ''),
                'dose'         => $this->clean_scalar_text($value['dose'] ?? $value['dosage'] ?? $value['strength'] ?? ''),
                'frequency'    => $this->clean_scalar_text($value['frequency'] ?? $value['freq'] ?? $value['schedule'] ?? ''),
                'time'         => $this->normalize_time_value($value['time'] ?? $value['hour'] ?? $value['hours'] ?? ($value['time_slots'] ?? '')),
                'instructions' => $this->clean_scalar_text($value['instructions'] ?? $value['notes'] ?? $value['doctor_instructions'] ?? ''),
                'status'       => trim((string) ($status_raw ?: 'active')),
            );
        }

        if (is_string($value) && trim($value) !== '') {
            return array('id' => 0, 'source' => 'meta', 'name' => $this->clean_scalar_text($value), 'dose' => '', 'frequency' => '', 'time' => '', 'instructions' => '', 'status' => 'active');
        }
        return null;
    }

    private function is_probable_medication_name($name) {
        $name = trim((string) $name);
        if ($name === '') { return false; }
        if ($this->mb_length($name) < 2 || $this->mb_length($name) > 90) { return false; }
        if (preg_match('/^\d{4}-\d{2}-\d{2}/', $name)) { return false; }
        if (preg_match('/^\d{1,2}\/\d{1,2}\/\d{4}/', $name)) { return false; }
        if (preg_match('/^\d{1,2}:\d{2}/', $name)) { return false; }
        if (preg_match('/^[0-9\-\:\/\s\.,]+$/', $name)) { return false; }
        if (preg_match('/(συμπτω|παρενεργ|γνώμη|άγχ|στρες|δυσκαμψ|πόνος|κόπωση|ύπνος|ορθοστασ|διατροφή|ξεκούραση|χαλάρωση|λοιμωξ|ψυχολογ|πρωινή|check-in|render|openai|documentation)/iu', $name)) { return false; }
        return true;
    }

    private function medication_keys() {
        return array('autoanosis_medications','autoanosis_medication_list','autoanosis_medication','autoa_medications','my_medications','medications','auto_medications');
    }

    private function extract_medications_from_value($raw_value) {
        $raw_value = $this->decode_maybe($raw_value);
        $items = array();

        if (is_array($raw_value)) {
            foreach ($raw_value as $value) {
                $item = $this->normalize_medication_item($value);
                if ($item) { $items[] = $item; }
            }
        } else {
            $item = $this->normalize_medication_item($raw_value);
            if ($item) { $items[] = $item; }
        }
        return $items;
    }

    private function get_mm_table_medications($user_id) {
        global $wpdb;
        $table = $wpdb->prefix . 'mm_medications';
        if (!$this->table_exists($table)) { return array(); }

        $columns = $this->table_columns($table);
        if (empty($columns) || !in_array('medication_name', $columns, true)) { return array(); }

        $where_field = in_array('patient_id', $columns, true) ? 'patient_id' : (in_array('user_id', $columns, true) ? 'user_id' : '');
        if ($where_field === '') { return array(); }

        $select = array();
        foreach (array('id','patient_id','user_id','medication_name','dosage','frequency','time_slots','instructions','notes','active','created_at','updated_at') as $col) {
            if (in_array($col, $columns, true)) { $select[] = $col; }
        }

        $where = "{$where_field} = %d";
        if (in_array('active', $columns, true)) { $where .= ' AND active = 1'; }

        $sql = "SELECT " . implode(',', $select) . " FROM {$table} WHERE {$where} ORDER BY " . (in_array('created_at', $columns, true) ? 'created_at DESC' : 'id DESC');
        $rows = $wpdb->get_results($wpdb->prepare($sql, $user_id), ARRAY_A);
        if (empty($rows)) { return array(); }

        $items = array();
        foreach ($rows as $row) {
            $item = $this->normalize_medication_item(array(
                'id'              => $row['id'] ?? 0,
                'source'          => 'mm_table',
                'medication_name' => $row['medication_name'] ?? '',
                'dosage'          => $row['dosage'] ?? '',
                'frequency'       => $row['frequency'] ?? '',
                'time_slots'      => $row['time_slots'] ?? '',
                'instructions'    => $this->select_existing_first($row, array('instructions','notes')),
                'active'          => $row['active'] ?? 1,
            ));
            if ($item) { $items[] = $item; }
        }
        return $items;
    }

    private function persist_mm_medication($patient_id, $med, $existing_id = 0) {
        global $wpdb;
        $table = $wpdb->prefix . 'mm_medications';
        if (!$this->table_exists($table)) { return false; }

        $columns = $this->table_columns($table);
        if (empty($columns)) { return false; }

        $data = array();
        $formats = array();
        if (in_array('patient_id', $columns, true)) { $data['patient_id'] = $patient_id; $formats[] = '%d'; }
        if (in_array('user_id', $columns, true)) { $data['user_id'] = $patient_id; $formats[] = '%d'; }
        if (in_array('medication_name', $columns, true)) { $data['medication_name'] = $med['name']; $formats[] = '%s'; }
        if (in_array('dosage', $columns, true)) { $data['dosage'] = $med['dose']; $formats[] = '%s'; }
        if (in_array('frequency', $columns, true)) { $data['frequency'] = $med['frequency']; $formats[] = '%s'; }
        if (in_array('time_slots', $columns, true)) {
            $slots = array_values(array_filter(array_map('trim', preg_split('/[,;]+/', (string) $med['time']))));
            $data['time_slots'] = wp_json_encode($slots);
            $formats[] = '%s';
        }
        if (in_array('instructions', $columns, true)) { $data['instructions'] = $med['instructions']; $formats[] = '%s'; }
        elseif (in_array('notes', $columns, true)) { $data['notes'] = $med['instructions']; $formats[] = '%s'; }
        if (in_array('active', $columns, true)) { $data['active'] = (($med['status'] ?? 'active') === 'stopped') ? 0 : 1; $formats[] = '%d'; }
        if (in_array('updated_at', $columns, true)) { $data['updated_at'] = current_time('mysql'); $formats[] = '%s'; }
        if (!$existing_id && in_array('created_at', $columns, true)) { $data['created_at'] = current_time('mysql'); $formats[] = '%s'; }

        if ($existing_id > 0) {
            return false !== $wpdb->update($table, $data, array('id' => $existing_id), $formats, array('%d'));
        }
        return false !== $wpdb->insert($table, $data, $formats);
    }

    private function get_medications_bundle($user_id) {
        $all = get_user_meta($user_id);
        $candidates = array();
        $source_key = 'autoanosis_medications';

        $mm_items = $this->get_mm_table_medications($user_id);
        if (!empty($mm_items)) {
            foreach ($mm_items as $item) { $candidates[] = $item; }
            $source_key = 'mm_medications';
        }

        foreach ($this->medication_keys() as $key) {
            if (!isset($all[$key][0])) { continue; }
            $items = $this->extract_medications_from_value($all[$key][0]);
            if (empty($items)) { continue; }
            foreach ($items as $item) { $candidates[] = $item; }
            if ($source_key === 'autoanosis_medications') { $source_key = $key; }
        }

        $clean = array();
        $seen = array();
        foreach ($candidates as $item) {
            if (!is_array($item)) { continue; }
            $name = trim((string) ($item['name'] ?? ''));
            if (!$this->is_probable_medication_name($name)) { continue; }
            $hash = md5($this->mb_lower($name . '|' . ($item['dose'] ?? '') . '|' . ($item['frequency'] ?? '') . '|' . ($item['time'] ?? '')));
            if (isset($seen[$hash])) {
                $existing_index = $seen[$hash];
                if ($existing_index !== null) {
                    if ($clean[$existing_index]['instructions'] === '' && trim((string) ($item['instructions'] ?? '')) !== '') {
                        $clean[$existing_index]['instructions'] = trim((string) ($item['instructions'] ?? ''));
                    }
                    if ($clean[$existing_index]['source'] !== 'mm_table' && ($item['source'] ?? '') === 'mm_table') {
                        $clean[$existing_index]['source'] = 'mm_table';
                        $clean[$existing_index]['id'] = absint($item['id'] ?? 0);
                    }
                }
                continue;
            }
            $seen[$hash] = count($clean);
            $clean[] = array(
                'id' => absint($item['id'] ?? 0),
                'source' => (string) ($item['source'] ?? ($source_key === 'mm_medications' ? 'mm_table' : 'meta')),
                'name' => $name,
                'dose' => trim((string) ($item['dose'] ?? '')),
                'frequency' => trim((string) ($item['frequency'] ?? '')),
                'time' => trim((string) ($item['time'] ?? '')),
                'instructions' => trim((string) ($item['instructions'] ?? '')),
                'status' => trim((string) ($item['status'] ?? 'active')),
            );
        }
        return array('items' => $clean, 'source_key' => $source_key);
    }

    private function get_medications($user_id) {
        $bundle = $this->get_medications_bundle($user_id);
        return $bundle['items'];
    }

    private function save_medications($user_id, $meds, $source_key = 'autoanosis_medications') {
        $meds = array_values($meds);
        update_user_meta($user_id, 'autoanosis_medications', $meds);
        update_user_meta($user_id, 'autoanosis_medication_list', $meds);

        foreach ($this->medication_keys() as $key) {
            if ($key === 'autoanosis_medications') { continue; }
            $existing = get_user_meta($user_id, $key, true);
            if ($existing !== '' || $key === $source_key) {
                update_user_meta($user_id, $key, $meds);
            }
        }
    }
    private function checkin_keys() {
        return array('autoanosis_checkins','autoanosis_daily_checkins','auto_checkins','checkins');
    }

    private function get_checkins($user_id, $limit = 14) {
        if (class_exists('Autoa_Daily_Checkin') && method_exists('Autoa_Daily_Checkin', 'get_recent_checkins')) {
            $rows = Autoa_Daily_Checkin::get_recent_checkins($user_id, $limit);
            if (is_array($rows) && !empty($rows)) { return $rows; }
        }
        foreach ($this->checkin_keys() as $key) {
            $val = get_user_meta($user_id, $key, true);
            $val = $this->decode_maybe($val);
            if (is_array($val) && !empty($val)) { return $val; }
        }
        return array();
    }

    private function sort_rows_desc(&$rows) {
        usort($rows, function($a, $b) {
            $da = strtotime((string) ($a['checkin_date'] ?? $a['created_at'] ?? $a['date'] ?? ''));
            $db = strtotime((string) ($b['checkin_date'] ?? $b['created_at'] ?? $b['date'] ?? ''));
            return $db <=> $da;
        });
    }

    private function get_recent_checkins($user_id, $limit = 5) {
        $rows = $this->get_checkins($user_id, max($limit, 14));
        if (empty($rows)) { return array(); }
        $this->sort_rows_desc($rows);
        return array_slice($rows, 0, $limit);
    }

    private function average_metric($rows, $keys) {
        $sum = 0;
        $count = 0;
        foreach ($rows as $row) {
            foreach ($keys as $key) {
                if (isset($row[$key]) && $row[$key] !== '') {
                    $sum += (float) $row[$key];
                    $count++;
                    break;
                }
            }
        }
        return $count > 0 ? round($sum / $count, 1) : null;
    }

    private function get_metrics_summary($user_id) {
        $rows = $this->get_checkins($user_id, 14);
        return array(
            'pain' => $this->average_metric($rows, array('pain','pain_level')),
            'fatigue' => $this->average_metric($rows, array('fatigue','fatigue_level')),
            'energy' => $this->average_metric($rows, array('energy','energy_level')),
            'mood' => $this->average_metric($rows, array('mood','mood_level')),
            'stiffness' => $this->average_metric($rows, array('stiffness','stiffness_level')),
            'inflammation' => $this->average_metric($rows, array('inflammation','inflammation_level')),
        );
    }

    private function latest_checkin_date($user_id) {
        $rows = $this->get_recent_checkins($user_id, 1);
        if (empty($rows)) { return '—'; }
        $date = (string) ($rows[0]['checkin_date'] ?? $rows[0]['created_at'] ?? $rows[0]['date'] ?? '');
        if ($date === '') { return '—'; }
        $ts = strtotime($date);
        return $ts ? date_i18n('d/m/Y', $ts) : $date;
    }

    public function render_patient_request_form() {
        if (!is_user_logged_in()) { return $this->notice('Χρειάζεται σύνδεση χρήστη.', 'warning'); }
        if ($this->current_user_can_doctor_access()) { return $this->notice('Η φόρμα σύνδεσης είναι μόνο για ασθενείς.', 'warning'); }

        ob_start();
        ?>
        <div class="aodd-wrap">
            <?php echo $this->pull_notice('aodd_connect_notice'); ?>
            <div class="aodd-card">
                <h2 class="aodd-title">Σύνδεση με Γιατρό</h2>
                <p class="aodd-subtitle">Ο ασθενής ξεκινά τη σύνδεση. Ο γιατρός αποδέχεται από το doctor dashboard.</p>
                <form method="post">
                    <?php wp_nonce_field('aodd_send_request'); ?>
                    <label class="aodd-label">Email γιατρού</label>
                    <input class="aodd-input" type="email" name="doctor_email" required>
                    <div style="height:14px"></div>
                    <label style="display:flex;gap:10px;align-items:flex-start;">
                        <input type="checkbox" name="doctor_consent" value="1" required style="margin-top:4px;">
                        <span>Δίνω πρόσβαση στον γιατρό στο doctor dashboard, στα structured δεδομένα και στο My Medications μέχρι ανάκλησης.</span>
                    </label>
                    <div style="height:16px"></div>
                    <button class="aodd-btn" type="submit" name="aodd_send_request">Αποστολή αιτήματος σύνδεσης</button>
                </form>
            </div>
        </div>
        <?php
        return (string) ob_get_clean();
    }

    public function render_patient_connections() {
        if (!is_user_logged_in()) { return ''; }

        $patient_id = get_current_user_id();
        global $wpdb;
        $rows = $wpdb->get_results($wpdb->prepare(
            "SELECT a.*, u.display_name, u.user_email FROM {$this->assignments_table} a INNER JOIN {$wpdb->users} u ON u.ID = a.doctor_id WHERE a.patient_id=%d AND a.status='active' ORDER BY a.created_at DESC",
            $patient_id
        ));

        ob_start();
        ?>
        <div class="aodd-wrap">
            <?php echo $this->pull_notice('aodd_connections_notice'); ?>
            <div class="aodd-card">
                <h2 class="aodd-title">Οι γιατροί μου</h2>
                <?php if (empty($rows)) : ?>
                    <p class="aodd-empty">Δεν υπάρχει ενεργή σύνδεση αυτή τη στιγμή.</p>
                <?php else : ?>
                    <div class="aodd-list">
                        <?php foreach ($rows as $row) : ?>
                            <div class="aodd-item">
                                <div class="aodd-item-head">
                                    <div>
                                        <div class="aodd-item-name"><?php echo esc_html($row->display_name); ?></div>
                                        <div class="aodd-meta"><?php echo esc_html($row->user_email); ?></div>
                                    </div>
                                    <form method="post" onsubmit="return confirm('Να ανακληθεί η πρόσβαση του γιατρού;');">
                                        <?php wp_nonce_field('aodd_revoke'); ?>
                                        <input type="hidden" name="doctor_id" value="<?php echo esc_attr((string) $row->doctor_id); ?>">
                                        <button class="aodd-btn aodd-btn-red" type="submit" name="aodd_revoke_connection">Ανάκληση πρόσβασης</button>
                                    </form>
                                </div>
                            </div>
                        <?php endforeach; ?>
                    </div>
                <?php endif; ?>
            </div>
        </div>
        <?php
        return (string) ob_get_clean();
    }

    public function render_doctor_dashboard() {
        if (!is_user_logged_in()) { return $this->notice('Χρειάζεται σύνδεση.', 'warning'); }
        if (!$this->current_user_can_doctor_access()) { return $this->notice('Πρόσβαση μόνο για γιατρούς / staff.', 'error'); }

        $doctor_id = get_current_user_id();
        global $wpdb;
        $pending = $wpdb->get_results($wpdb->prepare(
            "SELECT r.*, u.display_name, u.user_email FROM {$this->requests_table} r INNER JOIN {$wpdb->users} u ON u.ID = r.patient_id WHERE r.doctor_id=%d AND r.status='pending' ORDER BY r.created_at DESC",
            $doctor_id
        ));
        $assigned = $wpdb->get_results($wpdb->prepare(
            "SELECT a.*, u.display_name, u.user_email FROM {$this->assignments_table} a INNER JOIN {$wpdb->users} u ON u.ID = a.patient_id WHERE a.doctor_id=%d AND a.status='active' ORDER BY a.updated_at DESC",
            $doctor_id
        ));

        $selected_patient_id = absint($_GET['patient'] ?? 0);
        $selected_html = '';
        if ($selected_patient_id > 0 && $this->assignment_exists($selected_patient_id, $doctor_id)) {
            $selected_html = $this->render_selected_patient($selected_patient_id, $doctor_id);
        }

        ob_start();
        ?>
        <div class="aodd-wrap">
            <?php
            echo $this->pull_notice('aodd_doctor_notice_custom');
            if (!empty($_GET['aodd_doctor_notice'])) {
                $map = array('updated' => 'Η ενέργεια ολοκληρώθηκε.', 'med_saved' => 'Η αγωγή ενημερώθηκε επιτυχώς.');
                $code = sanitize_key((string) $_GET['aodd_doctor_notice']);
                if (isset($map[$code])) { echo $this->notice($map[$code], 'success'); }
            }
            ?>
            <div class="aodd-card">
                <h1 class="aodd-title">Doctor Dashboard</h1>
                <p class="aodd-subtitle">Ασθενείς που έχουν εγκρίνει πρόσβαση στο προφίλ και στο My Medications.</p>
            </div>

            <div class="aodd-card">
                <h2 class="aodd-section-title">Εκκρεμή αιτήματα</h2>
                <?php if (empty($pending)) : ?>
                    <p class="aodd-empty">Δεν υπάρχουν νέα αιτήματα.</p>
                <?php else : ?>
                    <div class="aodd-list">
                        <?php foreach ($pending as $row) : ?>
                            <div class="aodd-item">
                                <div class="aodd-item-head">
                                    <div>
                                        <div class="aodd-item-name"><?php echo esc_html($row->display_name); ?></div>
                                        <div class="aodd-meta"><?php echo esc_html($row->user_email); ?></div>
                                    </div>
                                    <div class="aodd-row">
                                        <form method="post">
                                            <?php wp_nonce_field('aodd_request_action'); ?>
                                            <input type="hidden" name="request_id" value="<?php echo esc_attr((string) $row->id); ?>">
                                            <button class="aodd-btn aodd-btn-green" type="submit" name="aodd_request_action" value="approve">Αποδοχή</button>
                                        </form>
                                        <form method="post">
                                            <?php wp_nonce_field('aodd_request_action'); ?>
                                            <input type="hidden" name="request_id" value="<?php echo esc_attr((string) $row->id); ?>">
                                            <button class="aodd-btn aodd-btn-red" type="submit" name="aodd_request_action" value="reject">Απόρριψη</button>
                                        </form>
                                    </div>
                                </div>
                            </div>
                        <?php endforeach; ?>
                    </div>
                <?php endif; ?>
            </div>

            <div class="aodd-card">
                <h2 class="aodd-section-title">Ασθενείς μου</h2>
                <?php if (empty($assigned)) : ?>
                    <p class="aodd-empty">Δεν υπάρχουν ανατεθειμένοι ασθενείς ακόμη.</p>
                <?php else : ?>
                    <div class="aodd-list">
                        <?php foreach ($assigned as $row) : ?>
                            <div class="aodd-item">
                                <div class="aodd-item-head">
                                    <div>
                                        <div class="aodd-item-name"><?php echo esc_html($row->display_name); ?></div>
                                        <div class="aodd-meta">Πάθηση: <?php echo esc_html($this->get_condition((int) $row->patient_id)); ?> · Τελευταίο check-in: <?php echo esc_html($this->latest_checkin_date((int) $row->patient_id)); ?></div>
                                    </div>
                                    <a class="aodd-btn" href="<?php echo esc_url(add_query_arg('patient', (string) $row->patient_id)); ?>">Άνοιγμα ασθενή</a>
                                </div>
                            </div>
                        <?php endforeach; ?>
                    </div>
                <?php endif; ?>
            </div>

            <?php echo $selected_html; ?>
        </div>
        <?php
        return (string) ob_get_clean();
    }

    private function render_report_metadata_grid($metadata) {
        if (empty($metadata)) { return ''; }
        ob_start(); ?>
        <div class="aodd-meta-grid">
            <?php foreach ($metadata as $label => $value) : ?>
                <?php if (trim((string) $value) === '') { continue; } ?>
                <?php $display_value = $this->label_is_date_like($label) ? $this->normalize_display_datetime($value) : $value; ?>
                <div class="aodd-meta-pill"><strong><?php echo esc_html($label); ?></strong><span class="aodd-pretty-date"><?php echo esc_html($display_value); ?></span></div>
            <?php endforeach; ?>
        </div>
        <?php return (string) ob_get_clean();
    }

    /**
     * Render exam results as horizontal lab-style table (v10.0.0).
     *
     * Format: Exam | Result | Unit | Reference Range | Status
     * Groups results by clinical_group with section headers.
     * Falls back to legacy vertical rendering for non-API reports.
     */
    private function render_report_sections($report) {
        // v10.0.0: Use horizontal table if structured_results are available
        $structured = isset($report['structured_results']) ? $report['structured_results'] : array();
        if (!empty($structured)) {
            return $this->render_horizontal_lab_table($structured);
        }

        // v11.0.0: Legacy vertical fallback removed. Only structured API results are rendered.
        return '';
    }

    /**
     * Render structured results as a horizontal lab-style table.
     *
     * Columns: Εξέταση | Αποτέλεσμα | Μονάδα | Τιμές Αναφοράς | Κατάσταση
     * Groups results by clinical_group with inline section headers.
     */
    private function render_horizontal_lab_table($structured_results) {
        if (empty($structured_results)) { return ''; }

        // Group by clinical_group
        $groups = array();
        foreach ($structured_results as $res) {
            $group = !empty($res['clinical_group']) ? $res['clinical_group'] : 'Αποτελέσματα';
            if (!isset($groups[$group])) { $groups[$group] = array(); }
            $groups[$group][] = $res;
        }

        ob_start(); ?>
        <div class="aodd-hz-table-scroll">
            <table class="aodd-hz-table">
                <thead>
                    <tr>
                        <th>Εξέταση</th>
                        <th>Αποτέλεσμα</th>
                        <th>Μονάδα</th>
                        <th>Τιμές Αναφοράς</th>
                        <th>Κατάσταση</th>
                    </tr>
                </thead>
                <tbody>
                    <?php foreach ($groups as $group_name => $items) : ?>
                        <?php if (count($groups) > 1) : ?>
                            <tr>
                                <td colspan="5" style="background:#f0f1f7;font-weight:800;font-size:13px;color:#1f2233;padding:8px 12px;border-bottom:2px solid #dde0ed;">
                                    <?php echo esc_html($group_name); ?>
                                </td>
                            </tr>
                        <?php endif; ?>
                        <?php foreach ($items as $res) :
                            // Value
                            $display_val = '';
                            if (isset($res['value_text']) && $res['value_text'] !== '' && $res['value_text'] !== null) {
                                $display_val = $res['value_text'];
                            } elseif (isset($res['value_numeric']) && $res['value_numeric'] !== null) {
                                $display_val = (string) $res['value_numeric'];
                            }

                            // Unit
                            $unit = isset($res['unit']) ? trim((string) $res['unit']) : '';

                            // Reference range
                            $ref = '';
                            if (!empty($res['reference_text'])) {
                                $ref = $res['reference_text'];
                            } elseif (isset($res['reference_low']) && $res['reference_low'] !== null && isset($res['reference_high']) && $res['reference_high'] !== null) {
                                $ref = $res['reference_low'] . ' – ' . $res['reference_high'];
                            } elseif (isset($res['reference_low']) && $res['reference_low'] !== null) {
                                $ref = '> ' . $res['reference_low'];
                            } elseif (isset($res['reference_high']) && $res['reference_high'] !== null) {
                                $ref = '< ' . $res['reference_high'];
                            }

                            // Abnormal flag
                            $flag = isset($res['abnormal_flag']) ? strtolower(trim((string) $res['abnormal_flag'])) : '';
                            $flag_class = '';
                            $flag_label = '';
                            if ($flag === 'high') {
                                $flag_class = 'aodd-flag-high';
                                $flag_label = '↑ Υψηλό';
                            } elseif ($flag === 'low') {
                                $flag_class = 'aodd-flag-low';
                                $flag_label = '↓ Χαμηλό';
                            } elseif ($flag === 'critical') {
                                $flag_class = 'aodd-flag-critical';
                                $flag_label = '⚠ Κρίσιμο';
                            } elseif ($flag === '' || $flag === 'normal') {
                                $flag_class = 'aodd-flag-normal';
                                $flag_label = 'Κανονικό';
                            } else {
                                $flag_label = $flag;
                            }
                        ?>
                            <tr>
                                <td><?php echo esc_html($res['display_name']); ?></td>
                                <td class="aodd-val-cell <?php echo esc_attr($flag_class); ?>"><?php echo esc_html($display_val); ?></td>
                                <td class="aodd-unit-cell"><?php echo esc_html($unit); ?></td>
                                <td class="aodd-ref-cell"><?php echo esc_html($ref); ?></td>
                                <td><span class="<?php echo esc_attr($flag_class); ?>"><?php echo esc_html($flag_label); ?></span></td>
                            </tr>
                        <?php endforeach; ?>
                    <?php endforeach; ?>
                </tbody>
            </table>
        </div>
        <?php return (string) ob_get_clean();
    }


    private function render_selected_patient($patient_id, $doctor_id) {
        $user = get_userdata($patient_id);
        if (!$user) { return ''; }

        $metrics = $this->get_metrics_summary($patient_id);
        $notes = $this->get_clean_notes($patient_id);
        $reports = $this->get_structured_reports($patient_id);
        $meds = $this->get_medications($patient_id);
        $recent = $this->get_recent_checkins($patient_id, 5);

        ob_start();
        ?>
        <div class="aodd-card">
            <div class="aodd-item-head" style="margin-bottom:16px;">
                <div>
                    <h2 class="aodd-title" style="margin-bottom:6px;">Ασθενής: <?php echo esc_html($user->display_name); ?></h2>
                    <div class="aodd-meta">Τελευταίο check-in: <?php echo esc_html($this->latest_checkin_date($patient_id)); ?></div>
                </div>
                <a class="aodd-btn aodd-btn-blue" href="<?php echo esc_url(admin_url('admin-post.php?action=autoanosis_doctor_download_report&patient_id=' . $patient_id . '&doctor_id=' . $doctor_id . '&_wpnonce=' . wp_create_nonce('aodd_download_report_' . $patient_id))); ?>">Λήψη αναφοράς για γιατρό</a>
            </div>

            <div class="aodd-grid" style="margin-bottom:18px;">
                <div class="aodd-col-3"><div class="aodd-stat"><strong>Πάθηση</strong><span style="font-size:18px;"><?php echo esc_html($this->get_condition($patient_id)); ?></span></div></div>
                <div class="aodd-col-3"><div class="aodd-stat"><strong>Μ. Πόνος (14ημ)</strong><span><?php echo esc_html((string) ($metrics['pain'] ?? '—')); ?>/10</span></div></div>
                <div class="aodd-col-3"><div class="aodd-stat"><strong>Μ. Κόπωση (14ημ)</strong><span><?php echo esc_html((string) ($metrics['fatigue'] ?? '—')); ?>/10</span></div></div>
                <div class="aodd-col-3"><div class="aodd-stat"><strong>Μ. Ενέργεια (14ημ)</strong><span><?php echo esc_html((string) ($metrics['energy'] ?? '—')); ?>/10</span></div></div>
                <div class="aodd-col-3"><div class="aodd-stat"><strong>Μ. Διάθεση (14ημ)</strong><span><?php echo esc_html((string) ($metrics['mood'] ?? '—')); ?>/10</span></div></div>
                <div class="aodd-col-3"><div class="aodd-stat"><strong>Μ. Δυσκαμψία (14ημ)</strong><span><?php echo esc_html((string) ($metrics['stiffness'] ?? '—')); ?>/10</span></div></div>
                <div class="aodd-col-3"><div class="aodd-stat"><strong>Μ. Φλεγμονή (14ημ)</strong><span><?php echo esc_html((string) ($metrics['inflammation'] ?? '—')); ?>/10</span></div></div>
            </div>

            <div class="aodd-grid" style="margin-bottom:16px;">
                <div class="aodd-col-6 aodd-card" style="padding:16px;box-shadow:none;">
                    <h3 class="aodd-section-title" style="font-size:18px;">Θεραπευτικό ιστορικό</h3>
                    <?php if (empty($meds)) : ?>
                        <p class="aodd-empty">Δεν βρέθηκαν καταχωρημένα φάρμακα.</p>
                    <?php else : ?>
                        <ul style="margin:0;padding-left:18px;">
                            <?php foreach ($meds as $med) : ?>
                                <li><?php echo esc_html(trim($med['name'] . ' ' . $med['dose'])); ?></li>
                            <?php endforeach; ?>
                        </ul>
                    <?php endif; ?>
                </div>
                <div class="aodd-col-6 aodd-card" style="padding:16px;box-shadow:none;">
                    <h3 class="aodd-section-title" style="font-size:18px;">Σημειώσεις / κλινικές παρατηρήσεις</h3>
                    <?php if (empty($notes)) : ?>
                        <p class="aodd-empty">Δεν υπάρχουν επιπλέον δομημένες σημειώσεις.</p>
                    <?php else : ?>
                        <ul style="margin:0;padding-left:18px;">
                            <?php foreach ($notes as $note) : ?>
                                <li><?php echo esc_html($note); ?></li>
                            <?php endforeach; ?>
                        </ul>
                    <?php endif; ?>
                </div>
            </div>

            <div class="aodd-card" style="padding:16px;box-shadow:none;margin-bottom:16px;">
                <h3 class="aodd-section-title" style="font-size:18px;">Εργαστηριακές Εξετάσεις</h3>
                <?php if (empty($reports)) : ?>
                    <p class="aodd-empty">Δεν βρέθηκαν αναφορές εξετάσεων με σαφή δομή.</p>
                <?php else : ?>
                    <?php foreach ($reports as $report) : ?>
                        <?php $report_date = $this->extract_report_display_datetime($report); ?>
                        <?php $norm_status = isset($report['normalization_status']) ? $report['normalization_status'] : ''; ?>
                        <?php $conf_score = isset($report['confidence_score']) ? (float) $report['confidence_score'] : null; ?>
                        <div class="aodd-report">
                            <?php if ($norm_status === 'needs_review') : ?>
                                <div class="aodd-review-banner">
                                    <span class="aodd-review-icon">&#9888;</span>
                                    <span>Χρειάζεται Επαλήθευση &mdash; Τα αποτελέσματα αυτής της αναφοράς δεν έχουν επιβεβαιωθεί πλήρως.</span>
                                </div>
                            <?php endif; ?>
                            <div class="aodd-report-head">
                                <h4><?php echo esc_html($report['title']); ?></h4>
                                <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;">
                                    <?php if ($report_date !== '') : ?><span class="aodd-badge aodd-pretty-date">Ημ/νία εξέτασης: <?php echo esc_html($report_date); ?></span><?php endif; ?>
                                    <?php if ($conf_score !== null) :
                                        $conf_pct = round($conf_score * 100);
                                        $conf_class = $conf_pct >= 80 ? 'aodd-conf-high' : ($conf_pct >= 50 ? 'aodd-conf-medium' : 'aodd-conf-low');
                                    ?>
                                        <span class="aodd-confidence-indicator">
                                            Εμπιστοσύνη: <?php echo $conf_pct; ?>%
                                            <span class="aodd-conf-bar"><span class="aodd-conf-fill <?php echo $conf_class; ?>" style="width:<?php echo $conf_pct; ?>%"></span></span>
                                        </span>
                                    <?php endif; ?>
                                    <?php if ($norm_status === 'needs_review') : ?>
                                        <span class="aodd-needs-review">&#9888; Χρειάζεται Επαλήθευση</span>
                                    <?php endif; ?>
                                </div>
                            </div>
                            <?php echo $this->render_report_metadata_grid((array) ($report['metadata'] ?? array())); ?>
                            <?php echo $this->render_report_sections($report); ?>
                        </div>
                    <?php endforeach; ?>
                <?php endif; ?>
            </div>

            <div class="aodd-card" style="padding:16px;box-shadow:none;margin-bottom:16px;">
                <h3 class="aodd-section-title" style="font-size:18px;">My Medications — Επεξεργασία από γιατρό</h3>
                <form method="post" style="margin-bottom:14px;">
                    <?php wp_nonce_field('aodd_add_medication'); ?>
                    <input type="hidden" name="patient_id" value="<?php echo esc_attr((string) $patient_id); ?>">
                    <div class="aodd-grid">
                        <div class="aodd-col-6"><label class="aodd-label">Νέο φάρμακο</label><input class="aodd-input" name="med_name_new"></div>
                        <div class="aodd-col-6"><label class="aodd-label">Δοσολογία</label><input class="aodd-input" name="med_dose_new"></div>
                        <div class="aodd-col-6"><label class="aodd-label">Συχνότητα</label><input class="aodd-input" name="med_frequency_new"></div>
                        <div class="aodd-col-6"><label class="aodd-label">Ώρα</label><input class="aodd-input" name="med_time_new"></div>
                        <div class="aodd-col-12"><label class="aodd-label">Οδηγίες γιατρού</label><textarea class="aodd-textarea" name="med_instructions_new"></textarea></div>
                    </div>
                    <div style="height:12px"></div>
                    <button class="aodd-btn aodd-btn-green" type="submit" name="aodd_add_medication">Προσθήκη φαρμάκου</button>
                </form>

                <?php if (!empty($meds)) : ?>
                    <div class="aodd-meds">
                        <?php foreach ($meds as $index => $med) : ?>
                            <div class="aodd-med">
                                <form method="post">
                                    <?php wp_nonce_field('aodd_save_medication'); ?>
                                    <input type="hidden" name="patient_id" value="<?php echo esc_attr((string) $patient_id); ?>">
                                    <input type="hidden" name="med_index" value="<?php echo esc_attr((string) $index); ?>">
                                    <input type="hidden" name="med_source_key" value="<?php echo esc_attr(($med['source'] ?? 'meta') === 'mm_table' ? 'mm_medications' : 'autoanosis_medications'); ?>">
                                    <input type="hidden" name="med_row_id" value="<?php echo esc_attr((string) ($med['id'] ?? 0)); ?>">
                                    <input type="hidden" name="med_status" value="<?php echo esc_attr((string) ($med['status'] ?? 'active')); ?>">
                                    <div class="aodd-grid">
                                        <div class="aodd-col-6"><label class="aodd-label">Φάρμακο</label><input class="aodd-input" name="med_name" value="<?php echo esc_attr($med['name']); ?>"></div>
                                        <div class="aodd-col-6"><label class="aodd-label">Δοσολογία</label><input class="aodd-input" name="med_dose" value="<?php echo esc_attr($med['dose']); ?>"></div>
                                        <div class="aodd-col-4"><label class="aodd-label">Συχνότητα</label><input class="aodd-input" name="med_frequency" value="<?php echo esc_attr($med['frequency']); ?>"></div>
                                        <div class="aodd-col-4"><label class="aodd-label">Ώρα</label><input class="aodd-input" name="med_time" value="<?php echo esc_attr($med['time']); ?>"></div>
                                        <div class="aodd-col-4"><label class="aodd-label">Κατάσταση</label><input class="aodd-input" value="<?php echo esc_attr(($med['status'] ?? 'active') === 'stopped' ? 'Ανενεργό' : 'Ενεργό'); ?>" readonly></div>
                                        <div class="aodd-col-12"><label class="aodd-label">Οδηγίες / σημείωση γιατρού</label><textarea class="aodd-textarea" name="med_instructions"><?php echo esc_textarea($med['instructions']); ?></textarea></div>
                                    </div>
                                    <div style="height:12px"></div>
                                    <button class="aodd-btn aodd-btn-green" type="submit" name="aodd_save_medication">Αποθήκευση αλλαγών</button>
                                </form>
                            </div>
                        <?php endforeach; ?>
                    </div>
                <?php endif; ?>
            </div>

            <div class="aodd-card" style="padding:16px;box-shadow:none;margin-bottom:16px;">
                <h3 class="aodd-section-title" style="font-size:18px;">Πρόσφατα check-ins</h3>
                <?php if (empty($recent)) : ?>
                    <p class="aodd-empty">Δεν υπάρχουν πρόσφατα check-ins.</p>
                <?php else : ?>
                    <div class="aodd-table-scroll">
                        <table class="aodd-table">
                            <thead>
                                <tr><th>Ημερομηνία</th><th>Πόνος</th><th>Κόπωση</th><th>Ενέργεια</th><th>Διάθεση</th><th>Δυσκαμψία</th><th>Φλεγμονή</th><th>Σημειώσεις</th></tr>
                            </thead>
                            <tbody>
                                <?php foreach ($recent as $row) : ?>
                                    <tr>
                                        <td><?php echo esc_html((string) ($row['checkin_date'] ?? $row['created_at'] ?? $row['date'] ?? '—')); ?></td>
                                        <td><?php echo esc_html((string) ($row['pain'] ?? $row['pain_level'] ?? '—')); ?></td>
                                        <td><?php echo esc_html((string) ($row['fatigue'] ?? $row['fatigue_level'] ?? '—')); ?></td>
                                        <td><?php echo esc_html((string) ($row['energy'] ?? $row['energy_level'] ?? '—')); ?></td>
                                        <td><?php echo esc_html((string) ($row['mood'] ?? $row['mood_level'] ?? '—')); ?></td>
                                        <td><?php echo esc_html((string) ($row['stiffness'] ?? $row['stiffness_level'] ?? '—')); ?></td>
                                        <td><?php echo esc_html((string) ($row['inflammation'] ?? $row['inflammation_level'] ?? '—')); ?></td>
                                        <td><?php echo esc_html((string) ($row['notes'] ?? $row['comment'] ?? '')); ?></td>
                                    </tr>
                                <?php endforeach; ?>
                            </tbody>
                        </table>
                    </div>
                <?php endif; ?>
            </div>

            <!-- REMOVED: Raw archive section (v9.0.0) - Only structured exam data is displayed -->
        </div>
        <?php
        return (string) ob_get_clean();
    }

    public function download_doctor_report() {
        $patient_id = absint($_GET['patient_id'] ?? 0);
        $doctor_id = absint($_GET['doctor_id'] ?? 0);
        $nonce = (string) ($_GET['_wpnonce'] ?? '');

        if (!is_user_logged_in() || get_current_user_id() !== $doctor_id) { wp_die('Access denied'); }
        if (!$this->current_user_can_doctor_access()) { wp_die('Access denied'); }
        if (!wp_verify_nonce($nonce, 'aodd_download_report_' . $patient_id)) { wp_die('Invalid nonce'); }
        if (!$this->assignment_exists($patient_id, $doctor_id)) { wp_die('No active assignment'); }

        $user = get_userdata($patient_id);
        $reports = $this->get_structured_reports($patient_id);
        $notes = $this->get_clean_notes($patient_id);
        $meds = $this->get_medications($patient_id);
        $metrics = $this->get_metrics_summary($patient_id);

        $out = array();
        $out[] = 'AUTOANOSIS DOCTOR REPORT';
        $out[] = 'Generated: ' . current_time('mysql');
        $out[] = 'Patient: ' . ($user ? $user->display_name : ('User #' . $patient_id));
        $out[] = 'Condition: ' . $this->get_condition($patient_id);
        $out[] = 'Latest check-in: ' . $this->latest_checkin_date($patient_id);
        $out[] = '';
        $out[] = '14-day metrics';
        $out[] = 'Pain: ' . ($metrics['pain'] !== null ? $metrics['pain'] : '—');
        $out[] = 'Fatigue: ' . ($metrics['fatigue'] !== null ? $metrics['fatigue'] : '—');
        $out[] = 'Energy: ' . ($metrics['energy'] !== null ? $metrics['energy'] : '—');
        $out[] = 'Mood: ' . ($metrics['mood'] !== null ? $metrics['mood'] : '—');
        $out[] = 'Stiffness: ' . ($metrics['stiffness'] !== null ? $metrics['stiffness'] : '—');
        $out[] = 'Inflammation: ' . ($metrics['inflammation'] !== null ? $metrics['inflammation'] : '—');
        $out[] = '';
        $out[] = 'Medications';
        if (empty($meds)) {
            $out[] = '- none';
        } else {
            foreach ($meds as $med) {
                $out[] = '- ' . trim($med['name'] . ' ' . $med['dose'] . ' | ' . $med['frequency'] . ' | ' . $med['time']);
                if ($med['instructions'] !== '') {
                    $out[] = '  instructions: ' . $med['instructions'];
                }
            }
        }
        $out[] = '';
        $out[] = 'Clinical notes';
        if (empty($notes)) {
            $out[] = '- none';
        } else {
            foreach ($notes as $note) {
                $out[] = '- ' . $note;
            }
        }
        $out[] = '';
        $out[] = 'Structured reports';
        if (empty($reports)) {
            $out[] = '- none';
        } else {
            foreach ($reports as $report) {
                $out[] = '';
                $out[] = '[' . $report['title'] . ']';
                foreach ($report['metadata'] as $label => $value) {
                    $out[] = $label . ': ' . $value;
                }
                $structured_results = isset($report['structured_results']) ? $report['structured_results'] : array();
                if (!empty($structured_results)) {
                    $groups = array();
                    foreach ($structured_results as $res) {
                        $group = isset($res['clinical_group']) ? $res['clinical_group'] : 'Αποτελέσματα';
                        $groups[$group][] = $res;
                    }
                    foreach ($groups as $group_name => $items) {
                        $out[] = $group_name . ':';
                        foreach ($items as $res) {
                            $val = $res['value_text'] !== '' ? $res['value_text'] : (string) ($res['value_numeric'] ?? '');
                            $unit = isset($res['unit']) ? $res['unit'] : '';
                            $ref = isset($res['reference_text']) && $res['reference_text'] !== '' ? $res['reference_text'] : (isset($res['reference_low'], $res['reference_high']) && $res['reference_low'] !== null ? $res['reference_low'] . '-' . $res['reference_high'] : '');
                            $flag = isset($res['abnormal_flag']) && $res['abnormal_flag'] !== '' ? ' [' . strtoupper($res['abnormal_flag']) . ']' : '';
                            $line = '- ' . ($res['display_name'] ?? 'Τιμή') . ': ' . trim($val . ' ' . $unit);
                            if ($ref !== '') { $line .= ' (' . $ref . ')'; }
                            $line .= $flag;
                            $out[] = $line;
                        }
                    }
                }
            }
        }

        $filename = 'autoanosis-doctor-report-' . $patient_id . '-' . date('Ymd-His') . '.txt';
        nocache_headers();
        header('Content-Type: text/plain; charset=UTF-8');
        header('Content-Disposition: attachment; filename=' . $filename);
        echo implode("\n", $out);
        exit;
    }
}

register_activation_hook(__FILE__, array('Autoanosis_Doctor_Dashboard_Rescue_Stable', 'activate'));
register_deactivation_hook(__FILE__, array('Autoanosis_Doctor_Dashboard_Rescue_Stable', 'deactivate'));
Autoanosis_Doctor_Dashboard_Rescue_Stable::instance();
