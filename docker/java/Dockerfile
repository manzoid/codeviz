# codeviz Java backend — a self-contained JDI tracer in a slim JDK image.
#
# This image bakes in our OWN JDI-based tracer (Tracer.java, MIT-clean; it uses
# only the standard com.sun.jdi debugging API).  It does NOT vendor OPT's
# AGPL java_jail / traceprinter.
#
# Built natively for the host architecture (arm64 on Apple Silicon, amd64 on
# x86_64) — eclipse-temurin ships native arm64, so no emulation is needed.
FROM eclipse-temurin:17-jdk

# bash for the entrypoint heredoc-style logic; python3 to emit the compile-error
# fallback trace.  (Temurin's Ubuntu base provides apt.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/codeviz

# Compile the tracer once at build time so runs are fast.
COPY Tracer.java /opt/codeviz/Tracer.java
RUN javac /opt/codeviz/Tracer.java

COPY entrypoint.sh /opt/codeviz/entrypoint.sh
RUN chmod +x /opt/codeviz/entrypoint.sh

ENTRYPOINT ["/opt/codeviz/entrypoint.sh"]
