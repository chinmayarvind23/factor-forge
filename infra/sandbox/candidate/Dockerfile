# Candidate v2 only. Stage the exact APK beside remove_installers.py before building.
# The bounded local feasibility controller executes this same offline recipe in an owned
# container with CPU/memory/PID limits, then commits it; it does not promote a runner pin.
FROM python@sha256:78e98729f8fc4099e53cffb3fe59fd15b18dfa4ace8c914dee0cefa5320068eb
RUN --network=none --mount=type=bind,source=.,target=/candidate-inputs,readonly \
    /usr/local/bin/python -B /candidate-inputs/remove_installers.py
CMD ["python3"]
