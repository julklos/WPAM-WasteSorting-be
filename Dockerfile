
FROM python:3.7

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY run.py .
COPY credentials.json .

COPY docker-entrypoint.sh .
CMD ["/bin/bash", "docker-entrypoint.sh"]