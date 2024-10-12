FROM python:3.12-slim

ENV PYTHONUNBUFFERED 1

ARG WHEEL_FILE=my_wheel.wh

# Copy only the wheel file
COPY dist/${WHEEL_FILE} /tmp/${WHEEL_FILE}

RUN apt-get update && apt-get install -y git

# Install the package
RUN pip install /tmp/${WHEEL_FILE} && \
    rm /tmp/${WHEEL_FILE}

RUN groupadd -r pythonuser && useradd -r -m -g pythonuser pythonuser

WORKDIR /home/pythonuser

USER pythonuser

ENV PRIVATE_ASSISTANT_CONFIG_PATH=template.yaml

ENTRYPOINT ["private-assistant-spotify-skill"]
