FROM python:3.11-slim

# Create non-root user (HF Spaces requires UID 1000)
RUN useradd -m -u 1000 potato

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy the application
COPY . .

# Install potato
RUN pip install --no-cache-dir -e .

# Copy the entrypoint script
COPY deployment/huggingface-spaces/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create directories for data and output
RUN mkdir -p /app/data /app/annotation_output && \
    chown -R potato:potato /app

# Switch to non-root user
USER potato

# HuggingFace Spaces expects port 7860
EXPOSE 7860

ENTRYPOINT ["/entrypoint.sh"]
