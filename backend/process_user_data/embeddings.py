from functools import lru_cache

import torch
from sentence_transformers import SentenceTransformer

from backend.config.settings import settings

_DEVICE = (
    "mps"
    if torch.backends.mps.is_available()
    else "cuda"
    if torch.cuda.is_available()
    else "cpu"
)


@lru_cache(maxsize=1)
def get_nomic_embedder() -> SentenceTransformer:
    return SentenceTransformer(
        settings.user_embed_model,
        trust_remote_code=True,
        device=_DEVICE,
    )


def embed_documents(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = get_nomic_embedder()
    prefixed = [f"search_document: {t}" for t in texts]
    vecs = model.encode(
        prefixed,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [v.tolist() for v in vecs]


def embed_query(text: str) -> list[float]:
    model = get_nomic_embedder()
    vec = model.encode(
        [f"search_query: {text}"],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0]
    return vec.tolist()
