FROM python:3.12-slim

WORKDIR /srv
RUN pip install --no-cache-dir pypdf python-docx

COPY app app
COPY web web
COPY eval eval
COPY sample_docs sample_docs

# data/ holds SQLite DB, uploads, reports — mount a volume here in production:
#   docker run -p 8000:8000 -v faqai-data:/srv/data --env-file .env shanai-faq-ai
VOLUME /srv/data
EXPOSE 8000

CMD ["python3", "-m", "app", "serve", "--host", "0.0.0.0", "--port", "8000"]
