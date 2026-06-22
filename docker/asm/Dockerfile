# codeviz x86-64 assembly tracer image.
#
# NATIVE arch image (no --platform): we do NOT emulate the whole container.
# Instead we cross-assemble the x86-64 binary and run *just that program* under
# qemu-user, whose built-in gdb stub drives instruction stepping — this avoids
# ptrace (which is unavailable when a whole container is emulated) and keeps the
# container native (fast). gdb-multiarch connects to the qemu stub remotely.
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
        binutils-x86-64-linux-gnu qemu-user gdb-multiarch python3 \
    && rm -rf /var/lib/apt/lists/*

COPY tracer.py /asm/tracer.py
COPY run.sh /asm/run.sh
RUN chmod +x /asm/run.sh

WORKDIR /work
ENTRYPOINT ["/asm/run.sh"]
