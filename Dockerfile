# Use official Python runtime as a parent image
FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose port
EXPOSE 5000

# Define environment variable for Flask
ENV FLASK_APP=grok3.py
ENV FLASK_RUN_HOST=0.0.0.0

# Runtime entrypoint
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "grok3:app"]
