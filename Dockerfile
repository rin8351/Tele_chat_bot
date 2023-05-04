# Use the official Python image as the base image
FROM python:3.8-slim

# Set the working directory
WORKDIR /app

# Copy the requirements.txt file into the container
COPY requirements.txt .

# Install the required packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
# COPY . .
# copy telebot_funk.py into the container
COPY telebot_funk.py .
# copy request_to_chatgpt.py into the container
COPY request_to_chatgpt.py .

# Expose the port the app will run on
EXPOSE 8080

# Run the application
CMD ["python", "telebot_funk.py"]
# infinity run
# CMD ["tail", "-f", "/dev/null"]
