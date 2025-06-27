# Use official Python runtime as a parent image
FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Copy and make entrypoint script executable
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Expose port
EXPOSE 5000

# Define environment variable for Flask
ENV FLASK_APP=grok3.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_ENV=production
# Default to production

# Set entrypoint
ENTRYPOINT ["./docker-entrypoint.sh"]
