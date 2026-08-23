# ADR-005: Docker first, EKS for the experiment worker plane

## Context

Generated research code needs isolation. Later, multiple experiments need parallel scheduling and resource limits.

## Decision

Implement the sandbox contract in Docker locally and map the same contract onto EKS Jobs for cloud productionization.

## Tradeoff

Two runtime adapters must stay behaviorally aligned.

## Why Kubernetes

The requirement is worker isolation and burst scaling, not API traffic.

## Switch condition

If managed batch/serverless compute provides equivalent isolation, reproducibility, and learning value with less operational cost, benchmark it against EKS.
