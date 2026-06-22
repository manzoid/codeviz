# codeviz C/C++ tracer image — modern, native arm64 (and amd64) replacement
# for OPT's legacy Valgrind backend.
#
# Contains gcc/g++, gdb (with its Python API), and our tracer.  The backend
# compiles the user's source with -g -O0 inside a container started from this
# image and drives gdb to single-step the program, emitting an OPT trace.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        gdb \
        python3 \
        libc6-dev \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Our tracer + entrypoint.
WORKDIR /opt/codeviz
COPY tracer.py /opt/codeviz/tracer.py
COPY run.sh /opt/codeviz/run.sh
RUN chmod +x /opt/codeviz/run.sh

# The backend pipes the user's source to stdin and passes "c" or "cpp" as the
# single argument.  run.sh compiles, then drives gdb with tracer.py.
ENTRYPOINT ["/opt/codeviz/run.sh"]
