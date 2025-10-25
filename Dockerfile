FROM python:3.10-slim

# Set timezone to UTC (system-wide)
ENV TZ=UTC

# Set working directory
WORKDIR /app

# Copy requirements first (for better caching)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Expose port
EXPOSE 3040

# Use non-reload mode for production (use --reload only for local dev)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3040"]
