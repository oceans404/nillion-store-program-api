FROM python:3.11
ARG NIL_SDK_VERSION=latest
ENV PATH="/app/sdk:$PATH"
WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    git \
    gzip \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip setuptools wheel

RUN curl -L https://nilup.nilogy.xyz/install.sh | bash -ex && \
    /root/.nilup/bin/nilup init && \
    /root/.nilup/bin/nilup install --nada-dsl --python-client ${NIL_SDK_VERSION} && \
    /root/.nilup/bin/nilup use ${NIL_SDK_VERSION} && \
    mkdir -p /app/sdk && \
    cp -r "/root/.nilup/sdks/${NIL_VERSION}" /app/sdk

COPY . .
RUN pip install -r requirements.txt

EXPOSE 8000

CMD nilup --version && nillion --version && python main.py