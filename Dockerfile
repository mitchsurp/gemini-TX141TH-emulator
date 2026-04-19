
FROM python:3.9-slim

WORKDIR /app

COPY webapp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY webapp/ .
COPY LaCrosse-TX141TH-BV2-raw.sub .

EXPOSE 5000

CMD ["python", "app.py"]
