# --- Dockerfile Content ---
# Base image with Python 3.10
FROM python:3.10-slim

# Set working directory inside the container
WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Flask app
COPY app.py .

# Expose the port (Cloud Run will use the $PORT variable)
EXPOSE 8080

# Start the application using Gunicorn (production server)
# Assumes your Flask app is named 'app'
CMD exec gunicorn --bind 0.0.0.0:$PORT app:app