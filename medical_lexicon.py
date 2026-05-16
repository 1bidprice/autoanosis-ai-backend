"""
medical_lexicon.py -- Comprehensive Bilingual Greek/English Medical Lexicon Correction Layer
Version: 2.0.0

Post-OCR deterministic correction for known Greek and English medical term errors.
Covers all major medical specialties with hundreds of OCR correction rules.

Architecture:
  Raw OCR text -> apply_lexicon_corrections() -> corrected text + corrections_log

Design principles:
  1. Only correct terms that are in the known error map -- never guess
  2. Log every correction for audit trail
  3. Case-insensitive matching, case-preserving output where possible
  4. More specific patterns first to avoid partial-match conflicts
  5. Greek and English rules are separate sections for maintainability
"""

import re
import logging
import unicodedata
from typing import NamedTuple

logger = logging.getLogger(__name__)


class LexiconRule(NamedTuple):
    pattern: str
    replacement: str
    context: str
    confidence: str  # 'high' | 'medium'
    language: str    # 'el' | 'en'


# ===========================================================================
# GREEK RULES
# ===========================================================================

GREEK_RULES: list[LexiconRule] = [

    # =========================================================================
    # GASTRENTREOLOGIA -- Gastroenterology
    # =========================================================================

    # Gallbladder - ΧΟΛΗΔΟΧΟΣ ΚΥΣΤΗ
    LexiconRule(r'\bΧΟΛΑΔΟΣΟΣ\s+ΚΥΣΤΗΣ?\b', 'ΧΟΛΗΔΟΧΟΣ ΚΥΣΤΗ', 'gallbladder_caps', 'high', 'el'),
    LexiconRule(r'\bΧΟΛΑΔΟΣ\s+ΚΥΣΤΗΣ?\b', 'ΧΟΛΗΔΟΧΟΣ ΚΥΣΤΗ', 'gallbladder_caps', 'high', 'el'),
    LexiconRule(r'\bΧΟΛΑΔΟΧΟΣ\s+ΚΥΣΤΗΣ?\b', 'ΧΟΛΗΔΟΧΟΣ ΚΥΣΤΗ', 'gallbladder_caps', 'high', 'el'),
    LexiconRule(r'\bΧΟΛΑΔΟΧΗ\s+ΚΥΣΤΗΣ?\b', 'ΧΟΛΗΔΟΧΟΣ ΚΥΣΤΗ', 'gallbladder_caps', 'high', 'el'),
    LexiconRule(r'\bΧΟΛΗΔΟΧΟΣ\s+ΚΥΣΤΙΣ\b', 'ΧΟΛΗΔΟΧΟΣ ΚΥΣΤΗ', 'gallbladder_caps_variant', 'high', 'el'),
    LexiconRule(r'\bΧολαδόχος\s+κύστη\b', 'Χοληδόχος κύστη', 'gallbladder_mixed', 'high', 'el'),
    LexiconRule(r'\bΧολάδοχος\s+κύστη\b', 'Χοληδόχος κύστη', 'gallbladder_mixed', 'high', 'el'),
    LexiconRule(r'\bΧολαδόχη\s+κύστη\b', 'Χοληδόχος κύστη', 'gallbladder_mixed', 'high', 'el'),
    LexiconRule(r'\bχολαδόχος\s+κύστη\b', 'χοληδόχος κύστη', 'gallbladder_lower', 'high', 'el'),

    # Bile duct - Χοληδόχος πόρος
    LexiconRule(r'\bΧολήθος\s+πόρος\b', 'Χοληδόχος πόρος', 'bile_duct', 'high', 'el'),
    LexiconRule(r'\bΧολήδοχος\s+πόρος\b', 'Χοληδόχος πόρος', 'bile_duct', 'high', 'el'),
    LexiconRule(r'\bΧολαδόχος\s+πόρος\b', 'Χοληδόχος πόρος', 'bile_duct', 'high', 'el'),
    LexiconRule(r'\bΧΟΛΑΔΟΧΟΣ\s+ΠΟΡΟΣ\b', 'ΧΟΛΗΔΟΧΟΣ ΠΟΡΟΣ', 'bile_duct_caps', 'high', 'el'),
    LexiconRule(r'\bΧΟΛΑΔΟΣΟΣ\s+ΠΟΡΟΣ\b', 'ΧΟΛΗΔΟΧΟΣ ΠΟΡΟΣ', 'bile_duct_caps', 'high', 'el'),

    # Bile ducts - Χολαγγεία
    LexiconRule(r'\bΧολαγγείες\s+φυσιολογικά\b', 'Χολαγγεία φυσιολογικά', 'bile_ducts_normal', 'medium', 'el'),
    LexiconRule(r'\bΧολαγγείες\s+φυσιολογικές\b', 'Χολαγγεία φυσιολογικά', 'bile_ducts_normal', 'medium', 'el'),
    LexiconRule(r'\bΧΟΛΑΓΓΕΙΕΣ\b', 'ΧΟΛΑΓΓΕΙΑ', 'bile_ducts_caps', 'medium', 'el'),

    # No stones - Ανευ λίθων
    LexiconRule(r'\bΑπειλούνται\b', 'Ανευ λίθων', 'no_gallstones', 'high', 'el'),
    LexiconRule(r'\bΑπειλούνταν\b', 'Ανευ λίθων', 'no_gallstones', 'high', 'el'),
    LexiconRule(r'\bΑνεύ\s+λίθων\b', 'Ανευ λίθων', 'no_gallstones_accent', 'high', 'el'),
    LexiconRule(r'\bΑνευ\s+λίθον\b', 'Ανευ λίθων', 'no_gallstones_genitive', 'high', 'el'),
    LexiconRule(r'\bΑνευ\s+λιθων\b', 'Ανευ λίθων', 'no_gallstones_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑνευ\s+λιθον\b', 'Ανευ λίθων', 'no_gallstones_no_accent2', 'high', 'el'),

    # Echogenicity - ηχοδομή
    LexiconRule(r'\bεκδόμη\b', 'ηχοδομή', 'echogenicity', 'high', 'el'),
    LexiconRule(r'\bεκδομή\b', 'ηχοδομή', 'echogenicity', 'high', 'el'),
    LexiconRule(r'\bεκδομη\b', 'ηχοδομή', 'echogenicity', 'high', 'el'),
    LexiconRule(r'\bηχοδομη\b', 'ηχοδομή', 'echogenicity_accent', 'high', 'el'),
    LexiconRule(r'\bηχοδόμη\b', 'ηχοδομή', 'echogenicity_wrong_accent', 'high', 'el'),
    LexiconRule(r'\bΗΧΟΔΟΜΗ\b', 'ΗΧΟΔΟΜΗ', 'echogenicity_caps', 'high', 'el'),

    # Liver - Ήπαρ
    LexiconRule(r'\bΗΠΑΡΑΣ\b', 'ΗΠΑΡ', 'liver_caps_wrong', 'high', 'el'),
    LexiconRule(r'\bήπαρας\b', 'ήπαρ', 'liver_wrong_form', 'high', 'el'),
    LexiconRule(r'\bηπαρ\b', 'ήπαρ', 'liver_no_accent', 'high', 'el'),
    LexiconRule(r'\bΗπαρ\b', 'Ήπαρ', 'liver_cap_no_accent', 'high', 'el'),

    # Spleen - Σπλήνας
    LexiconRule(r'\bΣΠΙΛΝΑΣ\b', 'ΣΠΛΗΝΑΣ', 'spleen_header', 'high', 'el'),
    LexiconRule(r'\bΣπιλνας\b', 'Σπλήνας', 'spleen_misspelled', 'high', 'el'),
    LexiconRule(r'\bσπιλνας\b', 'σπλήνας', 'spleen_lower_misspelled', 'high', 'el'),
    LexiconRule(r'\bσπληνας\b', 'σπλήνας', 'spleen_no_accent', 'high', 'el'),

    # Splenectomy - Σπληνεκτομή
    LexiconRule(r'\bΣπιλνεκτομή\b', 'Σπληνεκτομή', 'splenectomy_misspelled', 'high', 'el'),
    LexiconRule(r'\bΣπληνεκτομη\b', 'Σπληνεκτομή', 'splenectomy_no_accent', 'high', 'el'),
    LexiconRule(r'\bΣΠΛΗΝΕΚΤΟΜΗ\b', 'ΣΠΛΗΝΕΚΤΟΜΗ', 'splenectomy_caps', 'high', 'el'),

    # Pancreas - Πάγκρεας
    LexiconRule(r'\bπαγκρεας\b', 'πάγκρεας', 'pancreas_no_accent', 'high', 'el'),
    LexiconRule(r'\bΠαγκρεας\b', 'Πάγκρεας', 'pancreas_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΠΑΓΚΡΕΑΣ\b', 'ΠΑΓΚΡΕΑΣ', 'pancreas_caps', 'high', 'el'),

    # Cholecystectomy - Χολοκυστεκτομή
    LexiconRule(r'\bΧολοκυστεκτομη\b', 'Χολοκυστεκτομή', 'cholecystectomy_no_accent', 'high', 'el'),
    LexiconRule(r'\bΧολοκυστεκτομία\b', 'Χολοκυστεκτομή', 'cholecystectomy_wrong_ending', 'high', 'el'),
    LexiconRule(r'\bΧΟΛΟΚΥΣΤΕΚΤΟΜΗ\b', 'ΧΟΛΟΚΥΣΤΕΚΤΟΜΗ', 'cholecystectomy_caps', 'high', 'el'),

    # Endoscopy procedures
    LexiconRule(r'\bγαστροσκοπηση\b', 'γαστροσκόπηση', 'gastroscopy_no_accent', 'high', 'el'),
    LexiconRule(r'\bΓαστροσκοπηση\b', 'Γαστροσκόπηση', 'gastroscopy_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bκολονοσκοπηση\b', 'κολονοσκόπηση', 'colonoscopy_no_accent', 'high', 'el'),
    LexiconRule(r'\bΚολονοσκοπηση\b', 'Κολονοσκόπηση', 'colonoscopy_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bενδοσκοπηση\b', 'ενδοσκόπηση', 'endoscopy_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕνδοσκοπηση\b', 'Ενδοσκόπηση', 'endoscopy_cap_no_accent', 'high', 'el'),

    # =========================================================================
    # KARDIOLOGIA -- Cardiology
    # =========================================================================

    LexiconRule(r'\bκαρδια\b', 'καρδιά', 'heart_no_accent', 'high', 'el'),
    LexiconRule(r'\bΚαρδια\b', 'Καρδιά', 'heart_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bηχοκαρδιογραφημα\b', 'ηχοκαρδιογράφημα', 'echo_no_accent', 'high', 'el'),
    LexiconRule(r'\bΗχοκαρδιογραφημα\b', 'Ηχοκαρδιογράφημα', 'echo_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΗΧΟΚΑΡΔΙΟΓΡΑΦΗΜΑ\b', 'ΗΧΟΚΑΡΔΙΟΓΡΑΦΗΜΑ', 'echo_caps', 'high', 'el'),
    LexiconRule(r'\bμαρμαρυγη\b', 'μαρμαρυγή', 'afib_no_accent', 'high', 'el'),
    LexiconRule(r'\bΜαρμαρυγη\b', 'Μαρμαρυγή', 'afib_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bμαρμαρυγι\b', 'μαρμαρυγή', 'afib_wrong_ending', 'high', 'el'),
    LexiconRule(r'\bκολπικη\s+μαρμαρυγη\b', 'κολπική μαρμαρυγή', 'afib_phrase', 'high', 'el'),
    LexiconRule(r'\bΚολπικη\s+μαρμαρυγη\b', 'Κολπική μαρμαρυγή', 'afib_phrase_cap', 'high', 'el'),
    LexiconRule(r'\bαρτηριακη\s+πιεση\b', 'αρτηριακή πίεση', 'bp_no_accents', 'high', 'el'),
    LexiconRule(r'\bΑρτηριακη\s+πιεση\b', 'Αρτηριακή πίεση', 'bp_cap_no_accents', 'high', 'el'),
    LexiconRule(r'\bΑΡΤΗΡΙΑΚΗ\s+ΠΙΕΣΗ\b', 'ΑΡΤΗΡΙΑΚΗ ΠΙΕΣΗ', 'bp_caps', 'high', 'el'),
    LexiconRule(r'\bαορτη\b', 'αορτή', 'aorta_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑορτη\b', 'Αορτή', 'aorta_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑΟΡΤΗ\b', 'ΑΟΡΤΗ', 'aorta_caps', 'high', 'el'),
    LexiconRule(r'\bστεφανιαια\s+νοσος\b', 'στεφανιαία νόσος', 'cad_no_accents', 'high', 'el'),
    LexiconRule(r'\bΣτεφανιαια\s+νοσος\b', 'Στεφανιαία νόσος', 'cad_cap_no_accents', 'high', 'el'),
    LexiconRule(r'\bεμφραγμα\b', 'έμφραγμα', 'mi_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕμφραγμα\b', 'Έμφραγμα', 'mi_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕΜΦΡΑΓΜΑ\b', 'ΕΜΦΡΑΓΜΑ', 'mi_caps', 'high', 'el'),
    LexiconRule(r'\bαρρυθμια\b', 'αρρυθμία', 'arrhythmia_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑρρυθμια\b', 'Αρρυθμία', 'arrhythmia_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bαριθμια\b', 'αρρυθμία', 'arrhythmia_wrong_spelling', 'high', 'el'),
    LexiconRule(r'\bβαλβιδα\b', 'βαλβίδα', 'valve_no_accent', 'high', 'el'),
    LexiconRule(r'\bΒαλβιδα\b', 'Βαλβίδα', 'valve_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bμιτροειδης\s+βαλβιδα\b', 'μιτροειδής βαλβίδα', 'mitral_valve', 'high', 'el'),
    LexiconRule(r'\bΜιτροειδης\s+βαλβιδα\b', 'Μιτροειδής βαλβίδα', 'mitral_valve_cap', 'high', 'el'),
    LexiconRule(r'\bαορτικη\s+βαλβιδα\b', 'αορτική βαλβίδα', 'aortic_valve', 'high', 'el'),
    LexiconRule(r'\bΑορτικη\s+βαλβιδα\b', 'Αορτική βαλβίδα', 'aortic_valve_cap', 'high', 'el'),
    LexiconRule(r'\bτριγλωχινοειδης\s+βαλβιδα\b', 'τριγλωχινοειδής βαλβίδα', 'tricuspid_valve', 'high', 'el'),
    LexiconRule(r'\bκαρδιακη\s+ανεπαρκεια\b', 'καρδιακή ανεπάρκεια', 'heart_failure', 'high', 'el'),
    LexiconRule(r'\bΚαρδιακη\s+ανεπαρκεια\b', 'Καρδιακή ανεπάρκεια', 'heart_failure_cap', 'high', 'el'),
    LexiconRule(r'\bΚΑΡΔΙΑΚΗ\s+ΑΝΕΠΑΡΚΕΙΑ\b', 'ΚΑΡΔΙΑΚΗ ΑΝΕΠΑΡΚΕΙΑ', 'heart_failure_caps', 'high', 'el'),
    LexiconRule(r'\bστεφανιαιο\s+αρτηριο\b', 'στεφανιαίο αρτηρίδιο', 'coronary_artery', 'high', 'el'),
    LexiconRule(r'\bπεριφερικη\s+αρτηριακη\s+νοσος\b', 'περιφερική αρτηριακή νόσος', 'pad', 'high', 'el'),

    # =========================================================================
    # NEFROLOGIA & OUROLOGIA -- Nephrology & Urology
    # =========================================================================

    LexiconRule(r'\bνεφροι\b', 'νεφροί', 'kidneys_no_accent', 'high', 'el'),
    LexiconRule(r'\bΝεφροι\b', 'Νεφροί', 'kidneys_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΝΕΦΡΟΙ\b', 'ΝΕΦΡΟΙ', 'kidneys_caps', 'high', 'el'),
    LexiconRule(r'\bνεφρων\b', 'νεφρών', 'kidneys_genitive_no_accent', 'high', 'el'),
    LexiconRule(r'\bΝΕΦΡΩΝ\b', 'ΝΕΦΡΩΝ', 'kidneys_genitive_caps', 'high', 'el'),
    LexiconRule(r'\bνεφρεκτομη\b', 'νεφρεκτομή', 'nephrectomy_no_accent', 'high', 'el'),
    LexiconRule(r'\bΝεφρεκτομη\b', 'Νεφρεκτομή', 'nephrectomy_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΝΕΦΡΕΚΤΟΜΗ\b', 'ΝΕΦΡΕΚΤΟΜΗ', 'nephrectomy_caps', 'high', 'el'),
    LexiconRule(r'\bουρητηρας\b', 'ουρητήρας', 'ureter_no_accent', 'high', 'el'),
    LexiconRule(r'\bΟυρητηρας\b', 'Ουρητήρας', 'ureter_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΟΥΡΗΤΗΡΑΣ\b', 'ΟΥΡΗΤΗΡΑΣ', 'ureter_caps', 'high', 'el'),
    LexiconRule(r'\bουροδοχος\s+κυστη\b', 'ουροδόχος κύστη', 'bladder_no_accents', 'high', 'el'),
    LexiconRule(r'\bΟυροδοχος\s+κυστη\b', 'Ουροδόχος κύστη', 'bladder_cap_no_accents', 'high', 'el'),
    LexiconRule(r'\bΟΥΡΟΔΟΧΟΣ\s+ΚΥΣΤΗ\b', 'ΟΥΡΟΔΟΧΟΣ ΚΥΣΤΗ', 'bladder_caps', 'high', 'el'),
    LexiconRule(r'\bπροστατης\b', 'προστάτης', 'prostate_no_accent', 'high', 'el'),
    LexiconRule(r'\bΠροστατης\b', 'Προστάτης', 'prostate_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΠΡΟΣΤΑΤΗΣ\b', 'ΠΡΟΣΤΑΤΗΣ', 'prostate_caps', 'high', 'el'),
    LexiconRule(r'\bκρεατινινη\b', 'κρεατινίνη', 'creatinine_no_accent', 'high', 'el'),
    LexiconRule(r'\bΚρεατινινη\b', 'Κρεατινίνη', 'creatinine_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΚΡΕΑΤΙΝΙΝΗ\b', 'ΚΡΕΑΤΙΝΙΝΗ', 'creatinine_caps', 'high', 'el'),
    LexiconRule(r'\bουρια\b', 'ουρία', 'urea_no_accent', 'high', 'el'),
    LexiconRule(r'\bΟυρια\b', 'Ουρία', 'urea_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bλιθιαση\b', 'λιθίαση', 'lithiasis_no_accent', 'high', 'el'),
    LexiconRule(r'\bΛιθιαση\b', 'Λιθίαση', 'lithiasis_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΛΙΘΙΑΣΗ\b', 'ΛΙΘΙΑΣΗ', 'lithiasis_caps', 'high', 'el'),
    LexiconRule(r'\bνεφρολιθιαση\b', 'νεφρολιθίαση', 'nephrolithiasis_no_accent', 'high', 'el'),
    LexiconRule(r'\bΝεφρολιθιαση\b', 'Νεφρολιθίαση', 'nephrolithiasis_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bυδρονεφρωση\b', 'υδρονέφρωση', 'hydronephrosis_no_accent', 'high', 'el'),
    LexiconRule(r'\bΥδρονεφρωση\b', 'Υδρονέφρωση', 'hydronephrosis_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΥΔΡΟΝΕΦΡΩΣΗ\b', 'ΥΔΡΟΝΕΦΡΩΣΗ', 'hydronephrosis_caps', 'high', 'el'),

    # =========================================================================
    # PNEVMONOLOGIA -- Pulmonology
    # =========================================================================

    LexiconRule(r'\bπνευμονες\b', 'πνεύμονες', 'lungs_no_accent', 'high', 'el'),
    LexiconRule(r'\bΠνευμονες\b', 'Πνεύμονες', 'lungs_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΠΝΕΥΜΟΝΕΣ\b', 'ΠΝΕΥΜΟΝΕΣ', 'lungs_caps', 'high', 'el'),
    LexiconRule(r'\bπνευμονων\b', 'πνευμόνων', 'lungs_genitive_no_accent', 'high', 'el'),
    LexiconRule(r'\bπλευρα\b', 'πλευρά', 'pleura_no_accent', 'medium', 'el'),
    LexiconRule(r'\bΠλευρα\b', 'Πλευρά', 'pleura_cap_no_accent', 'medium', 'el'),
    LexiconRule(r'\bΠΛΕΥΡΑ\b', 'ΠΛΕΥΡΑ', 'pleura_caps', 'high', 'el'),
    LexiconRule(r'\bπλευριτιδα\b', 'πλευρίτιδα', 'pleuritis_no_accent', 'high', 'el'),
    LexiconRule(r'\bΠλευριτιδα\b', 'Πλευρίτιδα', 'pleuritis_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bβρογχοι\b', 'βρόγχοι', 'bronchi_no_accent', 'high', 'el'),
    LexiconRule(r'\bΒρογχοι\b', 'Βρόγχοι', 'bronchi_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bβρογχιτιδα\b', 'βρογχίτιδα', 'bronchitis_no_accent', 'high', 'el'),
    LexiconRule(r'\bΒρογχιτιδα\b', 'Βρογχίτιδα', 'bronchitis_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bπνευμονια\b', 'πνευμονία', 'pneumonia_no_accent', 'high', 'el'),
    LexiconRule(r'\bΠνευμονια\b', 'Πνευμονία', 'pneumonia_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΠΝΕΥΜΟΝΙΑ\b', 'ΠΝΕΥΜΟΝΙΑ', 'pneumonia_caps', 'high', 'el'),
    LexiconRule(r'\bσπιρομετρηση\b', 'σπιρομέτρηση', 'spirometry_no_accent', 'high', 'el'),
    LexiconRule(r'\bΣπιρομετρηση\b', 'Σπιρομέτρηση', 'spirometry_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bεμφυσημα\b', 'εμφύσημα', 'emphysema_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕμφυσημα\b', 'Εμφύσημα', 'emphysema_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕΜΦΥΣΗΜΑ\b', 'ΕΜΦΥΣΗΜΑ', 'emphysema_caps', 'high', 'el'),
    LexiconRule(r'\bαποφρακτικη\s+πνευμονοπαθεια\b', 'αποφρακτική πνευμονοπάθεια', 'copd_no_accents', 'high', 'el'),
    LexiconRule(r'\bΑποφρακτικη\s+πνευμονοπαθεια\b', 'Αποφρακτική πνευμονοπάθεια', 'copd_cap', 'high', 'el'),

    # =========================================================================
    # ENDOKRINOLOGIA -- Endocrinology
    # =========================================================================

    LexiconRule(r'\bθυρεοειδης\b', 'θυρεοειδής', 'thyroid_no_accent', 'high', 'el'),
    LexiconRule(r'\bΘυρεοειδης\b', 'Θυρεοειδής', 'thyroid_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΘΥΡΕΟΕΙΔΗΣ\b', 'ΘΥΡΕΟΕΙΔΗΣ', 'thyroid_caps', 'high', 'el'),
    LexiconRule(r'\bθυρεοειδη\b', 'θυρεοειδή', 'thyroid_accusative_no_accent', 'high', 'el'),
    LexiconRule(r'\bΘυρεοειδη\b', 'Θυρεοειδή', 'thyroid_accusative_cap', 'high', 'el'),
    LexiconRule(r'\bυπερθυρεοειδισμος\b', 'υπερθυρεοειδισμός', 'hyperthyroid_no_accent', 'high', 'el'),
    LexiconRule(r'\bΥπερθυρεοειδισμος\b', 'Υπερθυρεοειδισμός', 'hyperthyroid_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bυποθυρεοειδισμος\b', 'υποθυρεοειδισμός', 'hypothyroid_no_accent', 'high', 'el'),
    LexiconRule(r'\bΥποθυρεοειδισμος\b', 'Υποθυρεοειδισμός', 'hypothyroid_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bσακχαρωδης\s+διαβητης\b', 'σακχαρώδης διαβήτης', 'diabetes_no_accents', 'high', 'el'),
    LexiconRule(r'\bΣακχαρωδης\s+διαβητης\b', 'Σακχαρώδης διαβήτης', 'diabetes_cap_no_accents', 'high', 'el'),
    LexiconRule(r'\bΣΑΚΧΑΡΩΔΗΣ\s+ΔΙΑΒΗΤΗΣ\b', 'ΣΑΚΧΑΡΩΔΗΣ ΔΙΑΒΗΤΗΣ', 'diabetes_caps', 'high', 'el'),
    LexiconRule(r'\bδιαβητης\b', 'διαβήτης', 'diabetes_no_accent', 'high', 'el'),
    LexiconRule(r'\bΔιαβητης\b', 'Διαβήτης', 'diabetes_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bινσουλινη\b', 'ινσουλίνη', 'insulin_no_accent', 'high', 'el'),
    LexiconRule(r'\bΙνσουλινη\b', 'Ινσουλίνη', 'insulin_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bεπινεφριδια\b', 'επινεφρίδια', 'adrenal_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕπινεφριδια\b', 'Επινεφρίδια', 'adrenal_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕΠΙΝΕΦΡΙΔΙΑ\b', 'ΕΠΙΝΕΦΡΙΔΙΑ', 'adrenal_caps', 'high', 'el'),
    LexiconRule(r'\bυπογλυκαιμια\b', 'υπογλυκαιμία', 'hypoglycemia_no_accent', 'high', 'el'),
    LexiconRule(r'\bΥπογλυκαιμια\b', 'Υπογλυκαιμία', 'hypoglycemia_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bυπεργλυκαιμια\b', 'υπεργλυκαιμία', 'hyperglycemia_no_accent', 'high', 'el'),
    LexiconRule(r'\bΥπεργλυκαιμια\b', 'Υπεργλυκαιμία', 'hyperglycemia_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bθυρεοτοξικωση\b', 'θυρεοτοξίκωση', 'thyrotoxicosis_no_accent', 'high', 'el'),
    LexiconRule(r'\bΘυρεοτοξικωση\b', 'Θυρεοτοξίκωση', 'thyrotoxicosis_cap_no_accent', 'high', 'el'),

    # =========================================================================
    # NEVROLOGIA -- Neurology
    # =========================================================================

    LexiconRule(r'\bεγκεφαλος\b', 'εγκέφαλος', 'brain_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕγκεφαλος\b', 'Εγκέφαλος', 'brain_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕΓΚΕΦΑΛΟΣ\b', 'ΕΓΚΕΦΑΛΟΣ', 'brain_caps', 'high', 'el'),
    LexiconRule(r'\bεγκεφαλου\b', 'εγκεφάλου', 'brain_genitive_no_accent', 'high', 'el'),
    LexiconRule(r'\bσπονδυλικη\s+στηλη\b', 'σπονδυλική στήλη', 'spine_no_accents', 'high', 'el'),
    LexiconRule(r'\bΣπονδυλικη\s+στηλη\b', 'Σπονδυλική στήλη', 'spine_cap_no_accents', 'high', 'el'),
    LexiconRule(r'\bΣΠΟΝΔΥΛΙΚΗ\s+ΣΤΗΛΗ\b', 'ΣΠΟΝΔΥΛΙΚΗ ΣΤΗΛΗ', 'spine_caps', 'high', 'el'),
    LexiconRule(r'\bεγκεφαλικο\s+επεισοδιο\b', 'εγκεφαλικό επεισόδιο', 'stroke_no_accents', 'high', 'el'),
    LexiconRule(r'\bΕγκεφαλικο\s+επεισοδιο\b', 'Εγκεφαλικό επεισόδιο', 'stroke_cap_no_accents', 'high', 'el'),
    LexiconRule(r'\bμαγνητικη\s+τομογραφια\b', 'μαγνητική τομογραφία', 'mri_no_accents', 'high', 'el'),
    LexiconRule(r'\bΜαγνητικη\s+τομογραφια\b', 'Μαγνητική τομογραφία', 'mri_cap_no_accents', 'high', 'el'),
    LexiconRule(r'\bΜΑΓΝΗΤΙΚΗ\s+ΤΟΜΟΓΡΑΦΙΑ\b', 'ΜΑΓΝΗΤΙΚΗ ΤΟΜΟΓΡΑΦΙΑ', 'mri_caps', 'high', 'el'),
    LexiconRule(r'\bνευρολογικη\s+εξεταση\b', 'νευρολογική εξέταση', 'neuro_exam', 'high', 'el'),
    LexiconRule(r'\bΝευρολογικη\s+εξεταση\b', 'Νευρολογική εξέταση', 'neuro_exam_cap', 'high', 'el'),
    LexiconRule(r'\bεπιληψια\b', 'επιληψία', 'epilepsy_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕπιληψια\b', 'Επιληψία', 'epilepsy_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕΠΙΛΗΨΙΑ\b', 'ΕΠΙΛΗΨΙΑ', 'epilepsy_caps', 'high', 'el'),
    LexiconRule(r'\bημικρανια\b', 'ημικρανία', 'migraine_no_accent', 'high', 'el'),
    LexiconRule(r'\bΗμικρανια\b', 'Ημικρανία', 'migraine_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΗΜΙΚΡΑΝΙΑ\b', 'ΗΜΙΚΡΑΝΙΑ', 'migraine_caps', 'high', 'el'),

    # =========================================================================
    # ORTHOPEDIKI & REVMATOLOGIA -- Orthopedics & Rheumatology
    # =========================================================================

    LexiconRule(r'\bκαταγμα\b', 'κάταγμα', 'fracture_no_accent', 'high', 'el'),
    LexiconRule(r'\bΚαταγμα\b', 'Κάταγμα', 'fracture_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΚΑΤΑΓΜΑ\b', 'ΚΑΤΑΓΜΑ', 'fracture_caps', 'high', 'el'),
    LexiconRule(r'\bαρθριτιδα\b', 'αρθρίτιδα', 'arthritis_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑρθριτιδα\b', 'Αρθρίτιδα', 'arthritis_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑΡΘΡΙΤΙΔΑ\b', 'ΑΡΘΡΙΤΙΔΑ', 'arthritis_caps', 'high', 'el'),
    LexiconRule(r'\bρευματοειδης\s+αρθριτιδα\b', 'ρευματοειδής αρθρίτιδα', 'ra_no_accents', 'high', 'el'),
    LexiconRule(r'\bΡευματοειδης\s+αρθριτιδα\b', 'Ρευματοειδής αρθρίτιδα', 'ra_cap_no_accents', 'high', 'el'),
    LexiconRule(r'\bοστεοπορωση\b', 'οστεοπόρωση', 'osteoporosis_no_accent', 'high', 'el'),
    LexiconRule(r'\bΟστεοπορωση\b', 'Οστεοπόρωση', 'osteoporosis_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΟΣΤΕΟΠΟΡΩΣΗ\b', 'ΟΣΤΕΟΠΟΡΟΣΗ', 'osteoporosis_caps', 'high', 'el'),
    LexiconRule(r'\bμηνισκος\b', 'μηνίσκος', 'meniscus_no_accent', 'high', 'el'),
    LexiconRule(r'\bΜηνισκος\b', 'Μηνίσκος', 'meniscus_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΜΗΝΙΣΚΟΣ\b', 'ΜΗΝΙΣΚΟΣ', 'meniscus_caps', 'high', 'el'),
    LexiconRule(r'\bοστεοαρθριτιδα\b', 'οστεοαρθρίτιδα', 'osteoarthritis_no_accent', 'high', 'el'),
    LexiconRule(r'\bΟστεοαρθριτιδα\b', 'Οστεοαρθρίτιδα', 'osteoarthritis_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bδισκοπαθεια\b', 'δισκοπάθεια', 'disc_disease_no_accent', 'high', 'el'),
    LexiconRule(r'\bΔισκοπαθεια\b', 'Δισκοπάθεια', 'disc_disease_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΔΙΣΚΟΠΑΘΕΙΑ\b', 'ΔΙΣΚΟΠΑΘΕΙΑ', 'disc_disease_caps', 'high', 'el'),
    LexiconRule(r'\bσπονδυλαρθριτιδα\b', 'σπονδυλαρθρίτιδα', 'spondylarthritis_no_accent', 'high', 'el'),
    LexiconRule(r'\bΣπονδυλαρθριτιδα\b', 'Σπονδυλαρθρίτιδα', 'spondylarthritis_cap_no_accent', 'high', 'el'),

    # =========================================================================
    # GYNAIKOLOGIA & MAIEFTIKI -- Gynecology & Obstetrics
    # =========================================================================

    LexiconRule(r'\bμητρα\b', 'μήτρα', 'uterus_no_accent', 'high', 'el'),
    LexiconRule(r'\bΜητρα\b', 'Μήτρα', 'uterus_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΜΗΤΡΑ\b', 'ΜΗΤΡΑ', 'uterus_caps', 'high', 'el'),
    LexiconRule(r'\bωοθηκες\b', 'ωοθήκες', 'ovaries_no_accent', 'high', 'el'),
    LexiconRule(r'\bΩοθηκες\b', 'Ωοθήκες', 'ovaries_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΩΟΘΗΚΕΣ\b', 'ΩΟΘΗΚΕΣ', 'ovaries_caps', 'high', 'el'),
    LexiconRule(r'\bωοθηκη\b', 'ωοθήκη', 'ovary_no_accent', 'high', 'el'),
    LexiconRule(r'\bΩοθηκη\b', 'Ωοθήκη', 'ovary_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bκυηση\b', 'κύηση', 'pregnancy_no_accent', 'high', 'el'),
    LexiconRule(r'\bΚυηση\b', 'Κύηση', 'pregnancy_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΚΥΗΣΗ\b', 'ΚΥΗΣΗ', 'pregnancy_caps', 'high', 'el'),
    LexiconRule(r'\bτραχηλος\b', 'τράχηλος', 'cervix_no_accent', 'high', 'el'),
    LexiconRule(r'\bΤραχηλος\b', 'Τράχηλος', 'cervix_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΤΡΑΧΗΛΟΣ\b', 'ΤΡΑΧΗΛΟΣ', 'cervix_caps', 'high', 'el'),
    LexiconRule(r'\bμαστος\b', 'μαστός', 'breast_no_accent', 'high', 'el'),
    LexiconRule(r'\bΜαστος\b', 'Μαστός', 'breast_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΜΑΣΤΟΣ\b', 'ΜΑΣΤΟΣ', 'breast_caps', 'high', 'el'),
    LexiconRule(r'\bμαστογραφια\b', 'μαστογραφία', 'mammography_no_accent', 'high', 'el'),
    LexiconRule(r'\bΜαστογραφια\b', 'Μαστογραφία', 'mammography_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bεμμηνοπαυση\b', 'εμμηνόπαυση', 'menopause_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕμμηνοπαυση\b', 'Εμμηνόπαυση', 'menopause_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕΜΜΗΝΟΠΑΥΣΗ\b', 'ΕΜΜΗΝΟΠΑΥΣΗ', 'menopause_caps', 'high', 'el'),
    LexiconRule(r'\bκολπος\b', 'κόλπος', 'vagina_no_accent', 'medium', 'el'),
    LexiconRule(r'\bΚολπος\b', 'Κόλπος', 'vagina_cap_no_accent', 'medium', 'el'),
    LexiconRule(r'\bΚΟΛΠΟΣ\b', 'ΚΟΛΠΟΣ', 'vagina_caps', 'high', 'el'),

    # =========================================================================
    # EMATOLOGIA -- Hematology
    # =========================================================================

    LexiconRule(r'\bαιμοσφαιρια\b', 'αιμοσφαίρια', 'blood_cells_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑιμοσφαιρια\b', 'Αιμοσφαίρια', 'blood_cells_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑΙΜΟΣΦΑΙΡΙΑ\b', 'ΑΙΜΟΣΦΑΙΡΙΑ', 'blood_cells_caps', 'high', 'el'),
    LexiconRule(r'\bαιμοσφαιρινη\b', 'αιμοσφαιρίνη', 'haemoglobin_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑιμοσφαιρινη\b', 'Αιμοσφαιρίνη', 'haemoglobin_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑΙΜΟΣΦΑΙΡΙΝΗ\b', 'ΑΙΜΟΣΦΑΙΡΙΝΗ', 'haemoglobin_caps', 'high', 'el'),
    LexiconRule(r'\bαιματοκριτης\b', 'αιματοκρίτης', 'haematocrit_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑιματοκριτης\b', 'Αιματοκρίτης', 'haematocrit_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑΙΜΑΤΟΚΡΙΤΗΣ\b', 'ΑΙΜΑΤΟΚΡΙΤΗΣ', 'haematocrit_caps', 'high', 'el'),
    LexiconRule(r'\bλευκοκυτταρα\b', 'λευκοκύτταρα', 'wbc_no_accent', 'high', 'el'),
    LexiconRule(r'\bΛευκοκυτταρα\b', 'Λευκοκύτταρα', 'wbc_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΛΕΥΚΟΚΥΤΤΑΡΑ\b', 'ΛΕΥΚΟΚΥΤΤΑΡΑ', 'wbc_caps', 'high', 'el'),
    LexiconRule(r'\bαιμοπεταλια\b', 'αιμοπετάλια', 'platelets_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑιμοπεταλια\b', 'Αιμοπετάλια', 'platelets_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑΙΜΟΠΕΤΑΛΙΑ\b', 'ΑΙΜΟΠΕΤΑΛΙΑ', 'platelets_caps', 'high', 'el'),
    LexiconRule(r'\bαναιμια\b', 'αναιμία', 'anaemia_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑναιμια\b', 'Αναιμία', 'anaemia_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑΝΑΙΜΙΑ\b', 'ΑΝΑΙΜΙΑ', 'anaemia_caps', 'high', 'el'),
    LexiconRule(r'\bθρομβοπενια\b', 'θρομβοπενία', 'thrombocytopenia_no_accent', 'high', 'el'),
    LexiconRule(r'\bΘρομβοπενια\b', 'Θρομβοπενία', 'thrombocytopenia_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bλευχαιμια\b', 'λευχαιμία', 'leukaemia_no_accent', 'high', 'el'),
    LexiconRule(r'\bΛευχαιμια\b', 'Λευχαιμία', 'leukaemia_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΛΕΥΧΑΙΜΙΑ\b', 'ΛΕΥΧΑΙΜΙΑ', 'leukaemia_caps', 'high', 'el'),

    # =========================================================================
    # OGKOLOGIA & PATHOLOGOANATOMIA -- Oncology & Pathology
    # =========================================================================

    LexiconRule(r'\bνεοπλασμα\b', 'νεόπλασμα', 'neoplasm_no_accent', 'high', 'el'),
    LexiconRule(r'\bΝεοπλασμα\b', 'Νεόπλασμα', 'neoplasm_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΝΕΟΠΛΑΣΜΑ\b', 'ΝΕΟΠΛΑΣΜΑ', 'neoplasm_caps', 'high', 'el'),
    LexiconRule(r'\bβιοψια\b', 'βιοψία', 'biopsy_no_accent', 'high', 'el'),
    LexiconRule(r'\bΒιοψια\b', 'Βιοψία', 'biopsy_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΒΙΟΨΙΑ\b', 'ΒΙΟΨΙΑ', 'biopsy_caps', 'high', 'el'),
    LexiconRule(r'\bμεταστασεις\b', 'μεταστάσεις', 'metastases_no_accent', 'high', 'el'),
    LexiconRule(r'\bΜεταστασεις\b', 'Μεταστάσεις', 'metastases_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΜΕΤΑΣΤΑΣΕΙΣ\b', 'ΜΕΤΑΣΤΑΣΕΙΣ', 'metastases_caps', 'high', 'el'),
    LexiconRule(r'\bκακοηθεια\b', 'κακοήθεια', 'malignancy_no_accent', 'high', 'el'),
    LexiconRule(r'\bΚακοηθεια\b', 'Κακοήθεια', 'malignancy_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΚΑΚΟΗΘΕΙΑ\b', 'ΚΑΚΟΗΘΕΙΑ', 'malignancy_caps', 'high', 'el'),
    LexiconRule(r'\bκαλοηθης\b', 'καλοήθης', 'benign_no_accent', 'high', 'el'),
    LexiconRule(r'\bΚαλοηθης\b', 'Καλοήθης', 'benign_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΚΑΛΟΗΘΗΣ\b', 'ΚΑΛΟΗΘΗΣ', 'benign_caps', 'high', 'el'),
    LexiconRule(r'\bκαρκινωμα\b', 'καρκίνωμα', 'carcinoma_no_accent', 'high', 'el'),
    LexiconRule(r'\bΚαρκινωμα\b', 'Καρκίνωμα', 'carcinoma_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΚΑΡΚΙΝΩΜΑ\b', 'ΚΑΡΚΙΝΩΜΑ', 'carcinoma_caps', 'high', 'el'),
    LexiconRule(r'\bαδενωμα\b', 'αδένωμα', 'adenoma_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑδενωμα\b', 'Αδένωμα', 'adenoma_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑΔΕΝΩΜΑ\b', 'ΑΔΕΝΩΜΑ', 'adenoma_caps', 'high', 'el'),

    # =========================================================================
    # AKTINOLOGIA & APEIKONISEI -- Radiology & Imaging
    # =========================================================================

    LexiconRule(r'\bυπερηχογραφημα\b', 'υπερηχογράφημα', 'ultrasound_no_accent', 'high', 'el'),
    LexiconRule(r'\bΥπερηχογραφημα\b', 'Υπερηχογράφημα', 'ultrasound_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΥΠΕΡΗΧΟΓΡΑΦΗΜΑ\b', 'ΥΠΕΡΗΧΟΓΡΑΦΗΜΑ', 'ultrasound_caps', 'high', 'el'),
    LexiconRule(r'\bαξονικη\s+τομογραφια\b', 'αξονική τομογραφία', 'ct_no_accents', 'high', 'el'),
    LexiconRule(r'\bΑξονικη\s+τομογραφια\b', 'Αξονική τομογραφία', 'ct_cap_no_accents', 'high', 'el'),
    LexiconRule(r'\bΑΞΟΝΙΚΗ\s+ΤΟΜΟΓΡΑΦΙΑ\b', 'ΑΞΟΝΙΚΗ ΤΟΜΟΓΡΑΦΙΑ', 'ct_caps', 'high', 'el'),
    LexiconRule(r'\bακτινογραφια\b', 'ακτινογραφία', 'xray_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑκτινογραφια\b', 'Ακτινογραφία', 'xray_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑΚΤΙΝΟΓΡΑΦΙΑ\b', 'ΑΚΤΙΝΟΓΡΑΦΙΑ', 'xray_caps', 'high', 'el'),
    LexiconRule(r'\bσπινθηρογραφημα\b', 'σπινθηρογράφημα', 'scintigraphy_no_accent', 'high', 'el'),
    LexiconRule(r'\bΣπινθηρογραφημα\b', 'Σπινθηρογράφημα', 'scintigraphy_cap_no_accent', 'high', 'el'),

    # =========================================================================
    # GENIKI IATRIKI -- General Medical Terms
    # =========================================================================

    LexiconRule(r'\bφυσιολογικος\b', 'φυσιολογικός', 'normal_masc_no_accent', 'high', 'el'),
    LexiconRule(r'\bΦυσιολογικος\b', 'Φυσιολογικός', 'normal_masc_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bφυσιολογικη\b', 'φυσιολογική', 'normal_fem_no_accent', 'high', 'el'),
    LexiconRule(r'\bΦυσιολογικη\b', 'Φυσιολογική', 'normal_fem_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bφυσιολογικα\b', 'φυσιολογικά', 'normal_neut_no_accent', 'high', 'el'),
    LexiconRule(r'\bΦυσιολογικα\b', 'Φυσιολογικά', 'normal_neut_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΦΥΣΙΟΛΟΓΙΚΑ\b', 'ΦΥΣΙΟΛΟΓΙΚΑ', 'normal_caps', 'high', 'el'),
    LexiconRule(r'\bπαθολογικος\b', 'παθολογικός', 'pathological_masc_no_accent', 'high', 'el'),
    LexiconRule(r'\bΠαθολογικος\b', 'Παθολογικός', 'pathological_masc_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bπαθολογικη\b', 'παθολογική', 'pathological_fem_no_accent', 'high', 'el'),
    LexiconRule(r'\bΠαθολογικη\b', 'Παθολογική', 'pathological_fem_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bπαθολογικα\b', 'παθολογικά', 'pathological_neut_no_accent', 'high', 'el'),
    LexiconRule(r'\bΠαθολογικα\b', 'Παθολογικά', 'pathological_neut_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bαρνητικο\b', 'αρνητικό', 'negative_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑρνητικο\b', 'Αρνητικό', 'negative_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑΡΝΗΤΙΚΟ\b', 'ΑΡΝΗΤΙΚΟ', 'negative_caps', 'high', 'el'),
    LexiconRule(r'\bθετικο\b', 'θετικό', 'positive_no_accent', 'high', 'el'),
    LexiconRule(r'\bΘετικο\b', 'Θετικό', 'positive_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΘΕΤΙΚΟ\b', 'ΘΕΤΙΚΟ', 'positive_caps', 'high', 'el'),
    LexiconRule(r'\bδιαστασεις\b', 'διαστάσεις', 'dimensions_no_accent', 'high', 'el'),
    LexiconRule(r'\bΔιαστασεις\b', 'Διαστάσεις', 'dimensions_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΔΙΑΣΤΑΣΕΙΣ\b', 'ΔΙΑΣΤΑΣΕΙΣ', 'dimensions_caps', 'high', 'el'),
    LexiconRule(r'\bμεγεθος\b', 'μέγεθος', 'size_no_accent', 'high', 'el'),
    LexiconRule(r'\bΜεγεθος\b', 'Μέγεθος', 'size_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΜΕΓΕΘΟΣ\b', 'ΜΕΓΕΘΟΣ', 'size_caps', 'high', 'el'),
    LexiconRule(r'\bομοιογενης\b', 'ομοιογενής', 'homogeneous_no_accent', 'high', 'el'),
    LexiconRule(r'\bΟμοιογενης\b', 'Ομοιογενής', 'homogeneous_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΟΜΟΙΟΓΕΝΗΣ\b', 'ΟΜΟΙΟΓΕΝΗΣ', 'homogeneous_caps', 'high', 'el'),
    LexiconRule(r'\bανομοιογενης\b', 'ανομοιογενής', 'heterogeneous_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑνομοιογενης\b', 'Ανομοιογενής', 'heterogeneous_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑΝΟΜΟΙΟΓΕΝΗΣ\b', 'ΑΝΟΜΟΙΟΓΕΝΗΣ', 'heterogeneous_caps', 'high', 'el'),
    LexiconRule(r'\bσυμπερασμα\b', 'συμπέρασμα', 'conclusion_no_accent', 'high', 'el'),
    LexiconRule(r'\bΣυμπερασμα\b', 'Συμπέρασμα', 'conclusion_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΣΥΜΠΕΡΑΣΜΑ\b', 'ΣΥΜΠΕΡΑΣΜΑ', 'conclusion_caps', 'high', 'el'),
    LexiconRule(r'\bγνωματευση\b', 'γνωμάτευση', 'opinion_no_accent', 'high', 'el'),
    LexiconRule(r'\bΓνωματευση\b', 'Γνωμάτευση', 'opinion_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΓΝΩΜΑΤΕΥΣΗ\b', 'ΓΝΩΜΑΤΕΥΣΗ', 'opinion_caps', 'high', 'el'),
    LexiconRule(r'\bεξεταση\b', 'εξέταση', 'exam_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕξεταση\b', 'Εξέταση', 'exam_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕΞΕΤΑΣΗ\b', 'ΕΞΕΤΑΣΗ', 'exam_caps', 'high', 'el'),
    LexiconRule(r'\bαποτελεσμα\b', 'αποτέλεσμα', 'result_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑποτελεσμα\b', 'Αποτέλεσμα', 'result_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑΠΟΤΕΛΕΣΜΑ\b', 'ΑΠΟΤΕΛΕΣΜΑ', 'result_caps', 'high', 'el'),
    LexiconRule(r'\bασθενης\b', 'ασθενής', 'patient_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑσθενης\b', 'Ασθενής', 'patient_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑΣΘΕΝΗΣ\b', 'ΑΣΘΕΝΗΣ', 'patient_caps', 'high', 'el'),
    LexiconRule(r'\bνοσοκομειο\b', 'νοσοκομείο', 'hospital_no_accent', 'high', 'el'),
    LexiconRule(r'\bΝοσοκομειο\b', 'Νοσοκομείο', 'hospital_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΝΟΣΟΚΟΜΕΙΟ\b', 'ΝΟΣΟΚΟΜΕΙΟ', 'hospital_caps', 'high', 'el'),
    LexiconRule(r'\bιατρειο\b', 'ιατρείο', 'clinic_no_accent', 'high', 'el'),
    LexiconRule(r'\bΙατρειο\b', 'Ιατρείο', 'clinic_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΙΑΤΡΕΙΟ\b', 'ΙΑΤΡΕΙΟ', 'clinic_caps', 'high', 'el'),
    LexiconRule(r'\bθεραπεια\b', 'θεραπεία', 'treatment_no_accent', 'high', 'el'),
    LexiconRule(r'\bΘεραπεια\b', 'Θεραπεία', 'treatment_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΘΕΡΑΠΕΙΑ\b', 'ΘΕΡΑΠΕΙΑ', 'treatment_caps', 'high', 'el'),
    LexiconRule(r'\bφαρμακο\b', 'φάρμακο', 'drug_no_accent', 'medium', 'el'),
    LexiconRule(r'\bΦαρμακο\b', 'Φάρμακο', 'drug_cap_no_accent', 'medium', 'el'),
    LexiconRule(r'\bΦΑΡΜΑΚΟ\b', 'ΦΑΡΜΑΚΟ', 'drug_caps', 'high', 'el'),
    LexiconRule(r'\bδιαγνωση\b', 'διάγνωση', 'diagnosis_no_accent', 'high', 'el'),
    LexiconRule(r'\bΔιαγνωση\b', 'Διάγνωση', 'diagnosis_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΔΙΑΓΝΩΣΗ\b', 'ΔΙΑΓΝΩΣΗ', 'diagnosis_caps', 'high', 'el'),
    LexiconRule(r'\bπρογνωση\b', 'πρόγνωση', 'prognosis_no_accent', 'high', 'el'),
    LexiconRule(r'\bΠρογνωση\b', 'Πρόγνωση', 'prognosis_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΠΡΟΓΝΩΣΗ\b', 'ΠΡΟΓΝΩΣΗ', 'prognosis_caps', 'high', 'el'),
    LexiconRule(r'\bεπεμβαση\b', 'επέμβαση', 'surgery_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕπεμβαση\b', 'Επέμβαση', 'surgery_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕΠΕΜΒΑΣΗ\b', 'ΕΠΕΜΒΑΣΗ', 'surgery_caps', 'high', 'el'),
    LexiconRule(r'\bχειρουργειο\b', 'χειρουργείο', 'operating_room_no_accent', 'high', 'el'),
    LexiconRule(r'\bΧειρουργειο\b', 'Χειρουργείο', 'operating_room_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΧΕΙΡΟΥΡΓΕΙΟ\b', 'ΧΕΙΡΟΥΡΓΕΙΟ', 'operating_room_caps', 'high', 'el'),
    LexiconRule(r'\bεξιτηριο\b', 'εξιτήριο', 'discharge_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕξιτηριο\b', 'Εξιτήριο', 'discharge_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕΞΙΤΗΡΙΟ\b', 'ΕΞΙΤΗΡΙΟ', 'discharge_caps', 'high', 'el'),
    LexiconRule(r'\bεισαγωγη\b', 'εισαγωγή', 'admission_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕισαγωγη\b', 'Εισαγωγή', 'admission_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΕΙΣΑΓΩΓΗ\b', 'ΕΙΣΑΓΩΓΗ', 'admission_caps', 'high', 'el'),
    LexiconRule(r'\bαλλεργια\b', 'αλλεργία', 'allergy_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑλλεργια\b', 'Αλλεργία', 'allergy_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΑΛΛΕΡΓΙΑ\b', 'ΑΛΛΕΡΓΙΑ', 'allergy_caps', 'high', 'el'),
    LexiconRule(r'\bυπερταση\b', 'υπέρταση', 'hypertension_no_accent', 'high', 'el'),
    LexiconRule(r'\bΥπερταση\b', 'Υπέρταση', 'hypertension_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΥΠΕΡΤΑΣΗ\b', 'ΥΠΕΡΤΑΣΗ', 'hypertension_caps', 'high', 'el'),
    LexiconRule(r'\bυποταση\b', 'υπόταση', 'hypotension_no_accent', 'high', 'el'),
    LexiconRule(r'\bΥποταση\b', 'Υπόταση', 'hypotension_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΥΠΟΤΑΣΗ\b', 'ΥΠΟΤΑΣΗ', 'hypotension_caps', 'high', 'el'),
    LexiconRule(r'\bλοιμωξη\b', 'λοίμωξη', 'infection_no_accent', 'high', 'el'),
    LexiconRule(r'\bΛοιμωξη\b', 'Λοίμωξη', 'infection_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΛΟΙΜΩΞΗ\b', 'ΛΟΙΜΩΞΗ', 'infection_caps', 'high', 'el'),
    LexiconRule(r'\bφλεγμονη\b', 'φλεγμονή', 'inflammation_no_accent', 'high', 'el'),
    LexiconRule(r'\bΦλεγμονη\b', 'Φλεγμονή', 'inflammation_cap_no_accent', 'high', 'el'),
    LexiconRule(r'\bΦΛΕΓΜΟΝΗ\b', 'ΦΛΕΓΜΟΝΗ', 'inflammation_caps', 'high', 'el'),

]  # end GREEK_RULES


# ===========================================================================
# ENGLISH RULES
# ===========================================================================

ENGLISH_RULES: list[LexiconRule] = [

    # =========================================================================
    # BIOCHEMISTRY / LAB RESULTS -- OCR character substitution errors
    # Common OCR errors: 1->l, l->1, 0->O, O->0, I->l, rn->m, etc.
    # =========================================================================

    LexiconRule(r'\bHaemog1obin\b', 'Haemoglobin', 'haemoglobin_1_l', 'high', 'en'),
    LexiconRule(r'\bHemog1obin\b', 'Hemoglobin', 'hemoglobin_1_l', 'high', 'en'),
    LexiconRule(r'\bHaemoglob1n\b', 'Haemoglobin', 'haemoglobin_i_1', 'high', 'en'),
    LexiconRule(r'\bHemoglob1n\b', 'Hemoglobin', 'hemoglobin_i_1', 'high', 'en'),
    LexiconRule(r'\bHaemog0bin\b', 'Haemoglobin', 'haemoglobin_0', 'high', 'en'),
    LexiconRule(r'\bCreatinlne\b', 'Creatinine', 'creatinine_l', 'high', 'en'),
    LexiconRule(r'\bCreatin1ne\b', 'Creatinine', 'creatinine_1', 'high', 'en'),
    LexiconRule(r'\bGluc0se\b', 'Glucose', 'glucose_0', 'high', 'en'),
    LexiconRule(r'\bGluc05e\b', 'Glucose', 'glucose_05', 'high', 'en'),
    LexiconRule(r'\bCh0lesterol\b', 'Cholesterol', 'cholesterol_0', 'high', 'en'),
    LexiconRule(r'\bCholester0l\b', 'Cholesterol', 'cholesterol_0_end', 'high', 'en'),
    LexiconRule(r'\bCholestero1\b', 'Cholesterol', 'cholesterol_1', 'high', 'en'),
    LexiconRule(r'\bTrig1ycerides\b', 'Triglycerides', 'triglycerides_1', 'high', 'en'),
    LexiconRule(r'\bTriglycerldes\b', 'Triglycerides', 'triglycerides_l', 'high', 'en'),
    LexiconRule(r'\bUr1a\b', 'Urea', 'urea_1', 'high', 'en'),
    LexiconRule(r'\bUr0a\b', 'Urea', 'urea_0', 'high', 'en'),
    LexiconRule(r'\bA1bumin\b', 'Albumin', 'albumin_1', 'high', 'en'),
    LexiconRule(r'\bAlbum1n\b', 'Albumin', 'albumin_i_1', 'high', 'en'),
    LexiconRule(r'\bBi1irubin\b', 'Bilirubin', 'bilirubin_1', 'high', 'en'),
    LexiconRule(r'\bBilirub1n\b', 'Bilirubin', 'bilirubin_i_1', 'high', 'en'),
    LexiconRule(r'\bBi1irub1n\b', 'Bilirubin', 'bilirubin_double', 'high', 'en'),
    LexiconRule(r'\bAlka1ine\s+Ph0sphatase\b', 'Alkaline Phosphatase', 'alp_double', 'high', 'en'),
    LexiconRule(r'\bAlkaline\s+Ph0sphatase\b', 'Alkaline Phosphatase', 'alp_0', 'high', 'en'),
    LexiconRule(r'\bAlka1ine\s+Phosphatase\b', 'Alkaline Phosphatase', 'alp_1', 'high', 'en'),
    LexiconRule(r'\bA1anine\s+Aminotransferase\b', 'Alanine Aminotransferase', 'alt_1', 'high', 'en'),
    LexiconRule(r'\bAlanine\s+Aminotransf0rase\b', 'Alanine Aminotransferase', 'alt_0', 'high', 'en'),
    LexiconRule(r'\bAspartate\s+Aminotransf0rase\b', 'Aspartate Aminotransferase', 'ast_0', 'high', 'en'),
    LexiconRule(r'\bGamma\s+GT\b', 'Gamma-GT', 'ggt_space', 'high', 'en'),
    LexiconRule(r'\bS0dium\b', 'Sodium', 'sodium_0', 'high', 'en'),
    LexiconRule(r'\bP0tassium\b', 'Potassium', 'potassium_0', 'high', 'en'),
    LexiconRule(r'\bCa1cium\b', 'Calcium', 'calcium_1', 'high', 'en'),
    LexiconRule(r'\bMagnes1um\b', 'Magnesium', 'magnesium_1', 'high', 'en'),
    LexiconRule(r'\bPh0sphorus\b', 'Phosphorus', 'phosphorus_0', 'high', 'en'),
    LexiconRule(r'\bT5H\b', 'TSH', 'tsh_5', 'high', 'en'),
    LexiconRule(r'\bT3H\b', 'TSH', 'tsh_3', 'high', 'en'),
    LexiconRule(r'\bFT4\b', 'FT4', 'ft4_ok', 'high', 'en'),
    LexiconRule(r'\bFT3\b', 'FT3', 'ft3_ok', 'high', 'en'),
    LexiconRule(r'\bP5A\b', 'PSA', 'psa_5', 'high', 'en'),
    LexiconRule(r'\bHbAlc\b', 'HbA1c', 'hba1c_l', 'high', 'en'),
    LexiconRule(r'\bHbA1C\b', 'HbA1c', 'hba1c_caps', 'high', 'en'),
    LexiconRule(r'\bHBA1C\b', 'HbA1c', 'hba1c_all_caps', 'high', 'en'),
    LexiconRule(r'\bC-React1ve\s+Prote1n\b', 'C-Reactive Protein', 'crp_double', 'high', 'en'),
    LexiconRule(r'\bC-Reactive\s+Prote1n\b', 'C-Reactive Protein', 'crp_1', 'high', 'en'),
    LexiconRule(r'\bE5R\b', 'ESR', 'esr_5', 'high', 'en'),
    LexiconRule(r'\bErythrocyte\s+Sed1mentation\b', 'Erythrocyte Sedimentation', 'esr_full', 'high', 'en'),
    LexiconRule(r'\bWh1te\s+B1ood\s+Ce1ls\b', 'White Blood Cells', 'wbc_triple', 'high', 'en'),
    LexiconRule(r'\bP1atelets\b', 'Platelets', 'platelets_1', 'high', 'en'),
    LexiconRule(r'\bFerr1tin\b', 'Ferritin', 'ferritin_1', 'high', 'en'),
    LexiconRule(r'\bFerrit1n\b', 'Ferritin', 'ferritin_i_1', 'high', 'en'),
    LexiconRule(r'\blron\b', 'Iron', 'iron_l', 'high', 'en'),
    LexiconRule(r'\bIr0n\b', 'Iron', 'iron_0', 'high', 'en'),
    LexiconRule(r'\bV1tamin\s+D\b', 'Vitamin D', 'vitd_1', 'high', 'en'),
    LexiconRule(r'\bV1tamin\s+B12\b', 'Vitamin B12', 'vitb12_1', 'high', 'en'),
    LexiconRule(r'\bVitam1n\s+D\b', 'Vitamin D', 'vitd_i_1', 'high', 'en'),
    LexiconRule(r'\bVitam1n\s+B12\b', 'Vitamin B12', 'vitb12_i_1', 'high', 'en'),
    LexiconRule(r'\bFo1ic\s+Ac1d\b', 'Folic Acid', 'folic_acid_double', 'high', 'en'),
    LexiconRule(r'\bFo1ate\b', 'Folate', 'folate_1', 'high', 'en'),
    LexiconRule(r'\bUr1c\s+Ac1d\b', 'Uric Acid', 'uric_acid_double', 'high', 'en'),
    LexiconRule(r'\bUric\s+Ac1d\b', 'Uric Acid', 'uric_acid_1', 'high', 'en'),
    LexiconRule(r'\bAmy1ase\b', 'Amylase', 'amylase_1', 'high', 'en'),
    LexiconRule(r'\bL1pase\b', 'Lipase', 'lipase_1', 'high', 'en'),
    LexiconRule(r'\bPr0thrombin\s+T1me\b', 'Prothrombin Time', 'pt_double', 'high', 'en'),
    LexiconRule(r'\bNT-pr0BNP\b', 'NT-proBNP', 'ntprobnp_0', 'high', 'en'),
    LexiconRule(r'\bTrop0nin\b', 'Troponin', 'troponin_0', 'high', 'en'),
    LexiconRule(r'\bTropon1n\b', 'Troponin', 'troponin_1', 'high', 'en'),
    LexiconRule(r'\bCort1sol\b', 'Cortisol', 'cortisol_1', 'high', 'en'),
    LexiconRule(r'\bC0rtisol\b', 'Cortisol', 'cortisol_0', 'high', 'en'),
    LexiconRule(r'\bInsu1in\b', 'Insulin', 'insulin_1', 'high', 'en'),
    LexiconRule(r'\bInsul1n\b', 'Insulin', 'insulin_i_1', 'high', 'en'),
    LexiconRule(r'\bTestoster0ne\b', 'Testosterone', 'testosterone_0', 'high', 'en'),
    LexiconRule(r'\bEstradiOl\b', 'Estradiol', 'estradiol_O', 'high', 'en'),
    LexiconRule(r'\bEstradiO1\b', 'Estradiol', 'estradiol_O1', 'high', 'en'),
    LexiconRule(r'\bProgesteron\b', 'Progesterone', 'progesterone_truncated', 'high', 'en'),
    LexiconRule(r'\bF5H\b', 'FSH', 'fsh_5', 'high', 'en'),
    LexiconRule(r'\bPro1actin\b', 'Prolactin', 'prolactin_1', 'high', 'en'),
    LexiconRule(r'\bProlact1n\b', 'Prolactin', 'prolactin_i_1', 'high', 'en'),
    LexiconRule(r'\bCA-l25\b', 'CA-125', 'ca125_l', 'high', 'en'),
    LexiconRule(r'\bCA\s+l9-9\b', 'CA 19-9', 'ca199_l', 'high', 'en'),
    LexiconRule(r'\beGFl\b', 'eGFR', 'egfr_l', 'high', 'en'),
    LexiconRule(r'\bFEVl\b', 'FEV1', 'fev1_l', 'high', 'en'),
    LexiconRule(r'\bFEVl/FVC\b', 'FEV1/FVC', 'fev1_fvc_l', 'high', 'en'),
    LexiconRule(r'\bRef\s+lnterval\b', 'Reference Interval', 'ref_interval_l', 'high', 'en'),
    LexiconRule(r'\bNorma1\s+Range\b', 'Normal Range', 'normal_range_1', 'high', 'en'),
    LexiconRule(r'\bH1GH\b', 'HIGH', 'high_1', 'high', 'en'),
    LexiconRule(r'\bL0W\b', 'LOW', 'low_0', 'high', 'en'),
    LexiconRule(r'\bCR1T1CAL\b', 'CRITICAL', 'critical_double', 'high', 'en'),
    LexiconRule(r'\bABN0RMAL\b', 'ABNORMAL', 'abnormal_0', 'high', 'en'),
    LexiconRule(r'\bPOS1TIVE\b', 'POSITIVE', 'positive_1', 'high', 'en'),
    LexiconRule(r'\bNEGAT1VE\b', 'NEGATIVE', 'negative_1', 'high', 'en'),
    LexiconRule(r'\bDETECTED\b', 'DETECTED', 'detected_ok', 'high', 'en'),
    LexiconRule(r'\bDETECT1D\b', 'DETECTED', 'detected_1', 'high', 'en'),
    LexiconRule(r'\bNOT\s+DETECTlD\b', 'NOT DETECTED', 'not_detected_l', 'high', 'en'),
    LexiconRule(r'\bNOT\s+DETECT1D\b', 'NOT DETECTED', 'not_detected_1', 'high', 'en'),

]  # end ENGLISH_RULES


# ---------------------------------------------------------------------------
# Suspicious patterns: if these remain after correction, flag for review
# ---------------------------------------------------------------------------

SUSPICIOUS_AFTER_CORRECTION = [
    # Greek suspicious patterns
    r'\bψευδό\b',
    r'\bηχύ\b',
    r'\bεκδόμη\b',
    r'\bεκδομή\b',
    r'\bΧΟΛΑΔΟΣ',
    r'\bΑπειλούνται\b',
    r'\bΣπληνική\b(?!\s+αρτηρία)',
    r'\bΣΠΙΛΝΑΣ\b',
    r'\bΧολήθος\b',
    r'\bΧολαδόχος\b',
    # English suspicious patterns
    r'\bHaemog1obin\b',
    r'\bCreatinlne\b',
    r'\bGluc0se\b',
    r'\bCh0lesterol\b',
    r'\bT5H\b',
    r'\bP5A\b',
]


# All rules combined (Greek first, then English)
LEXICON_RULES: list[LexiconRule] = GREEK_RULES + ENGLISH_RULES


class CorrectionResult:
    def __init__(self, original: str, corrected: str, corrections: list[dict], needs_review: bool):
        self.original = original
        self.corrected = corrected
        self.corrections = corrections
        self.needs_review = needs_review
        self.correction_count = len(corrections)


def apply_lexicon_corrections(raw_text: str) -> CorrectionResult:
    """
    Apply deterministic bilingual medical lexicon corrections to raw OCR text.

    Returns CorrectionResult with:
    - corrected: the corrected text
    - corrections: list of corrections applied (for audit log)
    - needs_review: True if suspicious patterns remain after correction
    """
    text = raw_text
    corrections = []

    for rule in LEXICON_RULES:
        matches = list(re.finditer(rule.pattern, text, re.IGNORECASE))
        if matches:
            # Process in reverse order to preserve string positions
            for match in reversed(matches):
                original_match = match.group(0)
                # If the original is ALL-CAPS, use the replacement in ALL-CAPS
                # For Greek all-caps text, also strip accent marks (tonos/dialytika)
                # because Greek uppercase conventionally omits accents
                if original_match.isupper():
                    upper_rep = rule.replacement.upper()
                    # Strip combining accent marks (tonos = 0x0301, dialytika = 0x0308)
                    nfd = unicodedata.normalize('NFD', upper_rep)
                    replacement = ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')
                else:
                    replacement = rule.replacement
                text = text[:match.start()] + replacement + text[match.end():]
                corrections.append({
                    'rule_context': rule.context,
                    'original': original_match,
                    'replacement': replacement,
                    'confidence': rule.confidence,
                    'language': rule.language,
                })
                logger.info(
                    "[LEXICON] Corrected '%s' -> '%s' (rule: %s, lang: %s)",
                    original_match, replacement, rule.context, rule.language
                )

    # Check for suspicious patterns remaining after correction
    remaining_suspicious = []
    for pattern in SUSPICIOUS_AFTER_CORRECTION:
        if re.search(pattern, text, re.IGNORECASE):
            remaining_suspicious.append(pattern)

    needs_review = len(remaining_suspicious) > 0
    if needs_review:
        logger.warning(
            "[LEXICON] Suspicious patterns remain after correction: %s",
            remaining_suspicious
        )

    if corrections:
        logger.info("[LEXICON] Applied %d corrections (%d Greek, %d English)",
            len(corrections),
            sum(1 for c in corrections if c['language'] == 'el'),
            sum(1 for c in corrections if c['language'] == 'en'),
        )
    else:
        logger.debug("[LEXICON] No corrections needed")

    return CorrectionResult(
        original=raw_text,
        corrected=text,
        corrections=corrections,
        needs_review=needs_review,
    )


def get_correction_summary(result: CorrectionResult) -> dict:
    """Return a summary dict suitable for API response or logging."""
    return {
        'corrections_applied': result.correction_count,
        'needs_review': result.needs_review,
        'corrections': result.corrections,
    }
