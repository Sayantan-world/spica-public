from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    logs_dir: Path = Path(".logs")
    user_data_dir: Path = Path("backend/process_user_data/.files")
    # Shared Magpie WAVs for picture-board phrases (6 voices × 12 phrases).
    phrase_audio_dir: Path = Path("data/.phrase_audio")

    database_url: str = "postgresql://spica:spica@127.0.0.1:5432/spica"
    max_text_files_per_user: int = 5
    max_text_file_chars: int = 10000

    user_embed_model: str = "nomic-ai/nomic-embed-text-v1.5"
    user_embed_dim: int = 768
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5.6-luna"
    openai_reasoning_effort: str = "medium"
    openai_max_input_tokens: int = 4096
    openai_chat_max_input_tokens: int = 8192
    openai_timeout_s: float = 90.0
    openai_api_key: str = ""
    openai_key_path: Path = Path("backend/.llm_enpoints/.openai_key")
    max_chat_sessions_per_user: int = 5
    max_chat_turns_per_session: int = 20

    # NVIDIA NIM speech — Riva gRPC on NVCF (not HTTP /v1/audio/*).
    nim_api_key: str = ""
    nim_key_path: Path = Path("backend/.llm_enpoints/.nim_key")
    nim_grpc_server: str = "grpc.nvcf.nvidia.com:443"
    nim_whisper_model: str = "openai/whisper-large-v3"
    nim_whisper_function_id: str = "b702f636-f60c-4a3d-a6f4-f3568c13bd7d"
    # Whisper docs use "en"; BCP-47 also accepted by some builds.
    nim_whisper_language: str = "en"
    # Magpie multilingual (no voice-prompt required). Zeroshot needs a reference clip.
    nim_magpie_model: str = "nvidia/magpie-tts-multilingual"
    nim_magpie_function_id: str = "877104f7-e885-42b9-8de8-f6e4c6303969"
    nim_magpie_language: str = "en-US"
    nim_magpie_voice: str = "Magpie-Multilingual.EN-US.Jason"
    nim_magpie_sample_rate_hz: int = 22050
    max_speech_bytes: int = 8_000_000


settings = Settings()
