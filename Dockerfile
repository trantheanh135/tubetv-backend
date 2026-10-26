FROM denoland/deno:bin AS deno

FROM python:3.12-slim
# Deno runs yt-dlp's YouTube challenge solver. ffmpeg is not needed: the TV merges the streams.
COPY --from=deno /deno /usr/local/bin/deno
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd -r -u 10001 app && mkdir -p /home/app && chown app /home/app
ENV HOME=/home/app DENO_DIR=/home/app/.deno
USER app
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
