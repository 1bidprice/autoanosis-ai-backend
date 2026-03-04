-- ============================================================
-- Autoanosis: Δημιουργία πίνακα δομημένων εξετάσεων
-- Εκτέλεση: phpMyAdmin → SQL → Εκτέλεση
-- Ημερομηνία: 2026-03-04
-- ============================================================

CREATE TABLE IF NOT EXISTS `tkc_autoanosis_test_results` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`     BIGINT UNSIGNED NOT NULL,
  `test_date`   DATE NULL,
  `test_name`   VARCHAR(190) NOT NULL,
  `test_value`  VARCHAR(190) NULL,
  `unit`        VARCHAR(50)  NULL,
  `ref_range`   VARCHAR(190) NULL,
  `flag`        VARCHAR(50)  NULL COMMENT 'HIGH, LOW, NORMAL',
  `source`      VARCHAR(190) NULL COMMENT 'PDF upload, manual, etc.',
  `created_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `user_id`   (`user_id`),
  KEY `test_date` (`test_date`),
  KEY `test_name` (`test_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- Migration: Εισαγωγή των ήδη καταχωρημένων εξετάσεων
-- (Αυτές είναι οι εξετάσεις που φαίνονται στο bot από health_info)
-- Αντικατέστησε το user_id = 4 με το δικό σου αν είναι διαφορετικό
-- ============================================================

INSERT INTO `tkc_autoanosis_test_results`
  (`user_id`, `test_date`, `test_name`, `test_value`, `unit`, `ref_range`, `flag`, `source`)
VALUES
  (4, '2025-11-01', 'Φερριτίνη Ορού',      '185.8',  'ng/mL',  '13 - 450',    'NORMAL', 'manual'),
  (4, '2025-11-01', 'Βιταμίνη B12',         '869.6',  'pg/mL',  '189 - 950',   'NORMAL', 'manual'),
  (4, '2025-11-01', 'Ra Test',               'ΑΡΝΗΤΙΚΟ','',      '',            'NORMAL', 'manual'),
  (4, '2025-11-01', 'TKE (ESR)',             '9',      'mm/h',   '< 20',        'NORMAL', 'manual'),
  (4, '2025-11-01', 'C3 Συμπλήρωμα',        '123',    'mg/dL',  '83 - 193',    'NORMAL', 'manual'),
  (4, '2025-11-01', '25-OH Vitamin D3',      '25.30',  'ng/mL',  '8.8 - 46.3',  'NORMAL', 'manual');

-- ============================================================
-- Επαλήθευση: Δες τα δεδομένα που μπήκαν
-- ============================================================
SELECT * FROM `tkc_autoanosis_test_results` WHERE user_id = 4 ORDER BY test_date DESC;
