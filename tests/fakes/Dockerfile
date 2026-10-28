FROM python:3.12-slim
WORKDIR /fake
RUN pip install --no-cache-dir fastapi uvicorn
COPY documents.py extractor.py ./
ARG FAKE_MODULE=documents
ENV FAKE_MODULE=${FAKE_MODULE}
CMD ["sh", "-c", "uvicorn ${FAKE_MODULE}:app --host 0.0.0.0 --port 8000"]