import os
import logging
import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

logger = logging.getLogger(__name__)

HF_RERANKER_MODEL = os.getenv("HF_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")


class Reranker:
    def __init__(self):
        logger.info("Loading reranker model: %s", HF_RERANKER_MODEL)
        self.tokenizer = AutoTokenizer.from_pretrained(HF_RERANKER_MODEL)
        self.model = AutoModelForSequenceClassification.from_pretrained(HF_RERANKER_MODEL)
        self.model.eval()
        logger.info("Reranker model loaded")

    def rerank(self, query: str, documents: list[str], top_k: int = 5) -> list[tuple[str, float]]:
        pairs = [[query, doc] for doc in documents]
        inputs = self.tokenizer(
            pairs,
            padding=True,
            truncation=True,
            return_tensors="pt",
            max_length=512,
        )
        with torch.no_grad():
            scores = self.model(**inputs).logits.squeeze(-1).tolist()

        if isinstance(scores, (int, float)):
            scores = [scores]

        indexed = list(zip(documents, scores))
        indexed.sort(key=lambda x: x[1], reverse=True)
        return indexed[:top_k]
