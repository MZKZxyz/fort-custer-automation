ARG BASE
ARG WORKER_BASE
FROM ${WORKER_BASE} AS coding
COPY --chmod=0444 infra/worker_entry.py infra/probe.py /opt/
WORKDIR /workspace
USER 65532:65532
ENTRYPOINT ["python3", "-I", "/opt/worker_entry.py"]

FROM ${WORKER_BASE} AS qa
COPY --chmod=0444 infra/worker_entry.py infra/probe.py /opt/
WORKDIR /workspace
USER 65531:65531
ENTRYPOINT ["python3", "-I", "/opt/worker_entry.py"]

FROM ${BASE} AS controller
COPY --chmod=0555 src/ /opt/controller/
COPY --chmod=0555 config/ /opt/config/
WORKDIR /workspace
USER 65530:65530
ENTRYPOINT ["python3", "/opt/controller/rehearsal.py"]
