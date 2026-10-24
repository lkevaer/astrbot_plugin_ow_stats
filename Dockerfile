FROM soulter/astrbot:v4.29.1

WORKDIR /AstrBot
COPY requirements.txt /opt/ow-stats-plugin/requirements.txt
RUN python -m pip install --no-cache-dir -r /opt/ow-stats-plugin/requirements.txt \
    && python -m playwright install --with-deps chromium \
    && apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY main.py core.py render.py __init__.py metadata.yaml _conf_schema.json README.md LICENSE /opt/ow-stats-plugin/
COPY report_ui /opt/ow-stats-plugin/report_ui/
COPY deploy/start.py /opt/start-ow-bot.py

EXPOSE 6185
CMD ["python", "/opt/start-ow-bot.py"]
