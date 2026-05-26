from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/mfe"
    data_input_dir: str = "./data/input"
    data_working_dir: str = "./data/working"
    data_output_dir: str = "./data/output"

    # S3 (opcional)
    aws_region: str = "us-east-1"
    s3_bucket: str | None = None
    s3_prefix: str = "articles/"

    # Pipeline
    use_deepseek_ocr: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
