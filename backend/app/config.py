from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://temporal:temporal@localhost:5432/orders"
    temporal_address: str = "localhost:7233"
    temporal_task_queue: str = "order-supervisor"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    max_workflow_age_hours: int = 72

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
