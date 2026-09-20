FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --system --uid 1001 harbour && chown -R harbour:harbour /app
USER 1001

EXPOSE 8080

CMD ["python", "app.py"]
