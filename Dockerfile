FROM python:3.12-slim

# System deps: gosu (privilege-drop), curl (Tailwind CLI download), gcc (C extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gosu \
        curl \
        gcc \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Non-root user that owns and runs the application
RUN groupadd -g 1000 appgroup \
 && useradd  -u 1000 -g appgroup -d /app -s /sbin/nologin appuser

WORKDIR /app

# ── Tailwind CSS (standalone CLI, no Node.js required) ───────────────────────
# Download the right binary for the build platform (amd64 or arm64)
RUN arch=$(uname -m | sed 's/x86_64/x64/;s/aarch64/arm64/') \
 && curl -fsSL \
    "https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-linux-${arch}" \
    -o /usr/local/bin/tailwindcss \
 && chmod +x /usr/local/bin/tailwindcss

# Copy templates and Tailwind config so the CLI can scan class names
COPY tailwind.config.js input.css ./
COPY app/templates/ ./app/templates/

# Generate minified production CSS into the static directory
RUN mkdir -p app/static \
 && tailwindcss -c tailwind.config.js -i input.css -o app/static/tailwind.css --minify

# ── Python app ────────────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application (templates already copied above)
COPY app/ ./app/

# Pre-create data dirs; the volume mount will overlay them at runtime
RUN mkdir -p /data/scripts /data/venvs /data/logs /data/db \
 && chown -R appuser:appgroup /data /app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
