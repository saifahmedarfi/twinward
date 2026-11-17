FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --uid 10001 --create-home app
WORKDIR /app
COPY services/idmz_gateway/requirements.txt .
RUN pip install -r requirements.txt
COPY services/idmz_gateway/ ./services/idmz_gateway/
COPY research/common/ ./research/common/
RUN touch research/__init__.py services/__init__.py
USER 10001
CMD ["uvicorn", "services.idmz_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
