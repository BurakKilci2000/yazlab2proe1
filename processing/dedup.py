"""
DUPLICATE (TEKRAR) KONTROLÜ (Proje dokümanı Bölüm 3)

İki katman:
1) Link kontrolü: Aynı URL ikinci kez işlenmez (pipeline + MongoDB unique index).
2) İçerik benzerliği: Farklı sitelerde yayınlanan aynı haber.
   - Model: sentence-transformers "paraphrase-multilingual-MiniLM-L12-v2"
     (Türkçe dahil 50+ dili destekler, her metni 384 boyutlu bir vektöre çevirir).
   - Metin: başlık + içeriğin başı (model zaten ilk ~128 parçayı okur).
   - Vektörler birim uzunluğa normalize edilir; bu durumda iki vektörün
     iç çarpımı = kosinüs benzerliği.
   - Benzerlik >= 0.90 (%90) ise iki haber aynı kabul edilir; yeni kayıt açılmaz,
     mevcut haberin `sources` listesine yeni kaynak eklenir.
   - Karşılaştırma yalnızca yayın tarihi ±3 gün içindeki haberlerle yapılır
     (aynı olay farklı sitelerde birkaç gün arayla yayınlanabilir; daha eski
     haberlerle karşılaştırmak hem gereksiz hem yavaştır).
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

import numpy as np

import config

log = logging.getLogger(__name__)


class SentenceEmbedder:
    """Model ilk kullanımda bir kez yüklenir (ilk çalıştırmada internetten indirilir)."""

    def __init__(self, model_name: str = config.EMBEDDING_MODEL_NAME):
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer
                log.info("Embedding modeli yükleniyor: %s", self.model_name)
                self._model = SentenceTransformer(self.model_name)
        return self._model

    def encode(self, text: str) -> list[float]:
        vector = self._load().encode(text, normalize_embeddings=True)
        return np.asarray(vector, dtype=np.float32).tolist()


def embedding_text(title: str, content: str) -> str:
    return f"{title}. {content[:1200]}"


def cosine_similarity_matrix(matrix: np.ndarray, vector: np.ndarray) -> np.ndarray:
    matrix_norm = np.linalg.norm(matrix, axis=1)
    vector_norm = np.linalg.norm(vector)
    denom = np.where(matrix_norm * vector_norm == 0, 1e-12, matrix_norm * vector_norm)
    return (matrix @ vector) / denom


class DuplicateDetector:
    def __init__(self, db, threshold: float = config.SIMILARITY_THRESHOLD,
                 window_days: int = config.DUPLICATE_WINDOW_DAYS):
        self.db = db
        self.threshold = threshold
        self.window = timedelta(days=window_days)

    def find_duplicate(self, embedding: list[float], published_at: datetime):
        """(eşleşen_haber, benzerlik) veya (None, en_yüksek_benzerlik) döndürür."""
        query = {
            "published_at": {"$gte": published_at - self.window, "$lte": published_at + self.window},
            "embedding": {"$exists": True},
        }
        docs = [d for d in self.db.news.find(query, {"embedding": 1, "title": 1, "sources": 1})
                if len(d.get("embedding") or []) == len(embedding)]
        if not docs:
            return None, 0.0

        matrix = np.asarray([d["embedding"] for d in docs], dtype=np.float32)
        sims = cosine_similarity_matrix(matrix, np.asarray(embedding, dtype=np.float32))
        best = int(np.argmax(sims))
        score = float(sims[best])
        if score >= self.threshold:
            return docs[best], score
        return None, score
