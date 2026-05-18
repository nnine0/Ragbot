import os
import logging
from typing import AsyncIterator
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

logger = logging.getLogger(__name__)

HF_GENERATION_MODEL = os.getenv("HF_GENERATION_MODEL", "google/flan-t5-large")


class RAGEngine:
    def __init__(self):
        logger.info("Loading generation model: %s", HF_GENERATION_MODEL)
        self.tokenizer = AutoTokenizer.from_pretrained(HF_GENERATION_MODEL)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(HF_GENERATION_MODEL)
        self.model.eval()
        logger.info("Generation model loaded")

    def generate(self, question: str, context_chunks: list[str]) -> str:
        context = "\n\n".join(context_chunks)
        prompt = (
            "Answer the question based on the provided context.\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {question}\n\n"
            "Answer:"
        )

        inputs = self.tokenizer(prompt, return_tensors="pt", max_length=512, truncation=True)
        outputs = self.model.generate(
            **inputs,
            max_new_tokens=512,
            do_sample=True,
            temperature=0.3,
        )
        return self.tokenizer.decode(outputs[0], skip_special_tokens=True)

    async def astream(self, question: str, context_chunks: list[str]) -> AsyncIterator[str]:
        context = "\n\n".join(context_chunks)
        prompt = (
            "Answer the question based on the provided context.\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {question}\n\n"
            "Answer:"
        )

        inputs = self.tokenizer(prompt, return_tensors="pt", max_length=512, truncation=True)
        outputs = self.model.generate(
            **inputs,
            max_new_tokens=512,
            do_sample=True,
            temperature=0.3,
        )
        full_answer = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        yield full_answer
