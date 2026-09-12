# Packaging-only context: verified patched runtime, original algorithm and retained notices.
FROM mcr.microsoft.com/dotnet/runtime@sha256:f9a9cef68c1ddd440de58c0c8ebe911a780210b831b39f2b84751922f7b27c42
LABEL org.factorforge.lean.build="lean-8ee075a-factorforge-dependencies-v1" \
      org.factorforge.lean.patch.sha256="21537ba9a29a2a3a5843e6bcc6c427674ea0cf6f9911d06e71f776687e99d50b" \
      org.factorforge.lean.profile="original-long-short-execution-v1"
ENV DOTNET_EnableDiagnostics=0 DOTNET_CLI_TELEMETRY_OPTOUT=1
WORKDIR /app
COPY --chown=1654:1654 runtime/ /app/
COPY --chown=1654:1654 algorithm/FactorForge.LeanSpike.dll /app/
COPY --chown=1654:1654 notices/ /app/notices/
USER 1654:1654
ENTRYPOINT ["dotnet", "/app/QuantConnect.Lean.Launcher.dll", "--config", "/input/config.json"]

