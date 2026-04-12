FROM python:3.10-slim

# Create standard man directories before installing openjdk, then install openjdk-17
RUN mkdir -p /usr/share/man/man1 /usr/share/man/man2 && \
    apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    curl \
    gnupg \
    apt-transport-https \
    ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/default-java
ENV PATH="$JAVA_HOME/bin:$PATH"

COPY . /app/

WORKDIR /app

RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1 \
    PORT=8000

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
