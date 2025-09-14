FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

# Allow absolute imports like "agent.*"
ENV PYTHONPATH=/app

# Flow agent image (Streamlined flow graph)
FROM base AS flow
EXPOSE 8501
CMD ["streamlit", "run", "streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501"]

# Think agent image (ReAct-style tool-use)
FROM base AS think
EXPOSE 8502
CMD ["streamlit", "run", "streamlit_think_app.py", "--server.address=0.0.0.0", "--server.port=8502"]
