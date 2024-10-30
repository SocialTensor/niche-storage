FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y build-essential libpq-dev && apt-get clean

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app.py ./
COPY utils.py ./

EXPOSE 10000

RUN rm -rf ~/.cache/pip

CMD ["uvicorn", "app:app", "--workers", "10", "--host", "0.0.0.0", "--port", "10000"]
