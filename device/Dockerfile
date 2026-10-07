FROM python:3.12-slim

WORKDIR /app

# Print each line immediately; otherwise `docker compose logs device` stays
# empty because Python buffers output that is not going to a terminal.
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY device.py .

CMD ["python", "device.py"]