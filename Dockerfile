# Base image with Python 3.9
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Install required Python packages
RUN pip install --no-cache-dir flask

# Copy the application code to the container
COPY ./mutating_gpu_shm_webhook.py /app

# Expose the port the application will run on
EXPOSE 8443

# Run the application
CMD ["python", "mutating_gpu_shm_webhook.py"]
