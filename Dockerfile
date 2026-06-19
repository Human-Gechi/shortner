FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN groupadd -r groups && useradd -r -g groups -m notroot

USER notroot

WORKDIR /app

RUN python -m pip install --no-cache-dir --upgrade pip

COPY requirements.txt .

COPY . .

RUN pip install --no-cache-dir -r requirements.txt
