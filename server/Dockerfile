FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY server/requirements.txt ./requirements.txt

# 国内服务器默认走清华镜像，避免 PyPI 直连超时；海外/直连可 --build-arg PIP_INDEX_URL=... 覆盖
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install -i ${PIP_INDEX_URL} -r requirements.txt

COPY standalone/ ./standalone/
COPY server/app.py ./server/app.py

WORKDIR /app/server

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
