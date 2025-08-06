# Dockerfile

# Use a slim, official Python image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy and install dependencies first to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source code into the container
COPY src/ ./src/
COPY main.py .

# Define the command to run the application
ENTRYPOINT ["python", "main.py"]