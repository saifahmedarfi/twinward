FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --uid 10001 --create-home app
WORKDIR /app
COPY services/boundary_firewall/requirements.txt .
RUN pip install -r requirements.txt
COPY research/__init__.py ./research/__init__.py
COPY research/common/ ./research/common/
COPY research/evaluation/ ./research/evaluation/
COPY research/telemetry/ ./research/telemetry/
COPY services/__init__.py ./services/__init__.py
COPY services/common/ ./services/common/
COPY services/boundary_firewall/ ./services/boundary_firewall/
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["uvicorn", "services.boundary_firewall.main:app", "--host", "0.0.0.0", "--port", "8000"]
