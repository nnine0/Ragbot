import os
import tempfile
import logging
from typing import Iterator
from unstructured.partition.auto import partition
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


def process_document(file_path: str, filename: str) -> Iterator[str]:
    ext = os.path.splitext(filename)[1].lower()

    elements = partition(
        filename=file_path,
        strategy="auto",
        ocr_mode="auto",
        languages=["eng"],
    )

    full_text = "\n\n".join([str(el) for el in elements])

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=100,
        separators=["\n\n", "\n", ".", " ", ""],
        length_function=len,
    )

    chunks = text_splitter.split_text(full_text)
    logger.info("Split document into %d chunks", len(chunks))
    return iter(chunks)
