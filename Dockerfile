FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN groupadd -r groups && useradd -r -g groups -m notroot

WORKDIR /app

RUN python -m pip install --no-cache-dir --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R notroot:groups /app

USER notroot
ENV PATH="/home/notroot/.local/bin:${PATH}"


CMD python src/download.py && python -m your_actual_start_command