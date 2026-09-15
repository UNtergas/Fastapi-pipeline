from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):   
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )

    # default value, to be overwritten in .env
    ollama_url: str = "http://ollama:11434"
 
    # default value, to be overwritten in .env
    ollama_model: str = "qwen3:8b"


settings = Settings()