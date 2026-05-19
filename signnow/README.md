# signNow CLI

A command-line interface for the official [signNow developer platform](https://www.signnow.com/developers).

## Installation

```bash
cd signnow
pip install -e .
```

## Quick Start

```bash
signnow program info
signnow auth status
signnow cache clear
```

## Commands

### Program (`signnow program`)

```bash
signnow program info
signnow program info --table
```

### Authentication (`signnow auth`)

```bash
signnow auth login
signnow auth login --force
signnow auth status
signnow auth test
signnow auth logout
signnow auth profiles list
```

### Cache (`signnow cache`)

```bash
signnow cache clear
signnow cache clear
```

## Notes

- This tool is intentionally minimal for the initial batch.
- It exposes verified metadata for the official signNow developer docs URL.
- It keeps OAuth auth scaffolding available for later API implementation against the verified docs.
