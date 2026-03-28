from pydantic import BaseModel

class Settings(BaseModel):
    app_name: str = "Autoanosis Exams Master Package"
    schema_version: str = "1.0"
    normalizer_version: str = "exams-master-package"

settings = Settings()
