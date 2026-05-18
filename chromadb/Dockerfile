FROM chromadb/chroma:0.4.22

ENV IS_PERSISTENT=TRUE
ENV ANONYMIZED_TELEMETRY=FALSE
ENV PERSIST_DIRECTORY=/chroma/chroma

VOLUME /chroma/chroma

EXPOSE 8000

CMD ["uvicorn", "chromadb.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
