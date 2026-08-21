"""Compile changed modules without importing runtime-only deployment configuration."""
from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parent
TARGETS = [
    ROOT / "app.py", ROOT / "exams_module/models/exam_models.py", ROOT / "exams_module/api/exams_flask.py",
    ROOT / "exams_module/services/normalizer_ai.py", ROOT / "exams_module/services/exam_service.py",
    ROOT / "exams_module/services/semantic_rules.py", ROOT / "exams_module/services/document_intelligence.py",
    ROOT / "exams_module/services/terminology_service.py", ROOT / "exams_module/services/assistant_context.py",
    ROOT / "exams_module/services/fhir_adapter.py",
]

for target in TARGETS:
    py_compile.compile(str(target), doraise=True)
    print(f"PASS: {target.relative_to(ROOT)}")
