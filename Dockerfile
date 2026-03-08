# Use an official lightweight Python image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/app/data

# Set the working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
RUN pip install uv

# Copy the project lockfiles
COPY pyproject.toml uv.lock ./

# Install dependencies using uv deterministically
RUN uv sync --frozen --no-dev

# Copy the rest of the application
COPY . .

# Add the virtual environment to the PATH
ENV PATH="/app/.venv/bin:$PATH"

# Expose the Streamlit port
EXPOSE 8501

# Run the Streamlit app natively from the venv
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
