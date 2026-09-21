# ML-KEM Legacy Modernization

A small edge-cloud system used to study the modernization of a legacy
communication system with post-quantum cryptography and LLM-assisted software development.

## Project Overview

This project is part of the Software Development, Maintenance & Operations course.

The project focuses on modernizing a simulated legacy edge-cloud system.
The original system consists of a legacy device, an edge gateway, and a
cloud service. During the project, the system is gradually improved through
testing, monitoring, CI/CD, deployment, and the integration of ML-KEM for
post-quantum key establishment.

The project also investigates the use of Large Language Models (LLMs) as
development assistants. Generated code and design suggestions are critically
evaluated for correctness, security, maintainability, testability, and
operational suitability.

## Architecture

```text
┌──────────────────┐
│  Legacy Device   │
│  Temperature     │
│     Sensor       │
└────────┬─────────┘
         │ HTTP
         ▼
┌──────────────────┐
│  Edge Gateway    │
│                  │
│  Validation      │
│  Monitoring      │
│  Modernization   │
└────────┬─────────┘
         │
         │ ML-KEM
         │ (later phase)
         ▼
┌──────────────────┐
│  Cloud Service   │
│                  │
│  Data Storage    │
│  API             │
└──────────────────┘
