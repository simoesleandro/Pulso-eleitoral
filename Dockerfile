FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cria diretório de dados
RUN mkdir -p /data

EXPOSE 8080

CMD ["python", "app.py"]
