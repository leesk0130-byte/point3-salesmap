FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
EXPOSE 10000
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:10000", "--workers", "2"]
