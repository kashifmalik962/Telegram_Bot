FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port
EXPOSE 3039

# Run the app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3039", "--reload"]
