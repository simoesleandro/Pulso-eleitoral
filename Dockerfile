FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN pip install playwright
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . .

# Cria diretório de dados
RUN mkdir -p /data

EXPOSE 8080

CMD ["python", "app.py"]
