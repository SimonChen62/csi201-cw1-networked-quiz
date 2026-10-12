FROM python:3.12-slim

WORKDIR /app
COPY protocol.py server.py questions.json ./
COPY tests ./tests

CMD ["python3", "server.py", "--host", "0.0.0.0", "--port", "5000", "--questions", "questions.json"]
