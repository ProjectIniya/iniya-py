# Project Iniya

### Local-First Personal AI Assistant Platform

**Status:** NOT BEING DEVELOPED

Iniya is a local-first AI assistant platform designed to combine conversational AI, long-term memory, voice interaction, tool execution, search, coding assistance, and task management into a unified personal AI system.

Unlike traditional chatbots, Iniya is built around a modular architecture that allows new capabilities to be added as independent components while maintaining persistent memory and contextual awareness across conversations.

The long-term goal is to create a personal AI companion that can reason, remember, communicate naturally, execute tasks, and interact with both software and physical systems.

---

# Features

### AI Reasoning

* Powered by Ollama
* Support for local and cloud-hosted models
* Model warm-up and management system
* Centralized LLM abstraction layer

### Multi-Layer Memory

#### Chat Memory

* Persistent conversation history
* Multi-chat support

#### Master Memory

* Cross-conversation knowledge storage
* Embedding-based retrieval
* Semantic similarity search
* Duplicate detection

#### Task Memory

* Persistent task tracking
* Priority management
* Due-date extraction
* Intelligent task retrieval

### Tool System

Built-in tools for:

* File operations
* Code execution
* Shell execution
* Search
* Task management
* Protocol execution

### Search Integration

* Tavily-powered web search
* Search result summarization
* Context-aware information retrieval

### Voice Assistant

#### Speech-to-Text

* Vosk
* Whisper

#### Text-to-Speech

* Piper

#### Audio Features

* Streaming audio infrastructure
* Device-aware configuration
* Offline-capable voice pipeline

### Agent Architecture

* BrainAgent orchestration system
* Skill classification and routing
* Personality framework
* Response processing pipeline
* Tool selection logic

### User Interfaces

#### Console Interface

* Full-featured terminal interface

#### GUI

* Graphical interface under active development
* Multi-chat management
* Voice integration support

---

# Installation

### Requirements

* Python 3.13+
* Ollama
* FFmpeg
* MPV
* Windows 10/11

Optional:

* NVIDIA GPU for accelerated local models

---

### Setup

```bash
git clone https://github.com/project-iniya/project-iniya
cd project-iniya
python setup.py
```

Run:

```bash
python main.example.py
```

---

# Default Model

Current default model:

```text
qwen3-coder-next:cloud
```

Models can be changed inside:

```text
AI_Model/llm_wrapper.py
```

---

# Technology Stack

## Core

* Python
* Ollama
* Multiprocessing
* Shared-state architecture

## Memory

* mxbai-embed-large embeddings
* Vector similarity search
* Persistent storage

## Search

* Tavily Search API

## Voice

* Whisper
* Vosk
* Piper

## GUI

* PyWebView
* Edge WebView2
* Vite
* Vue.js

---

# Project Vision

Iniya is being developed as a long-term AI platform capable of:

* Natural conversation
* Long-term memory
* Voice-first interaction
* Autonomous task execution
* Tool and software control
* Multi-device awareness
* Physical-world integration
* Future robotics and smart-environment support

The objective is to build a practical personal AI system that extends beyond chat and becomes a persistent digital assistant.

---

# License

This repository is protected under the Custom Restricted License (CRL-1.0).

Modification or redistribution is prohibited without explicit permission from the author.

See the LICENSE file for complete terms.
