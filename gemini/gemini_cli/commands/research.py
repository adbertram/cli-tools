"""Deep Research commands for Gemini CLI.

Uses the Interactions API "steps" schema introduced in google-genai >= 2.0.0
(legacy Interactions schema removed by the Gemini API on 2026-06-08). See
https://ai.google.dev/gemini-api/docs/interactions-breaking-changes-may-2026

Interactions are accessed via ``client.client.interactions`` where
``client`` is the ``GeminiClient`` wrapper and ``client.client`` is the
underlying ``google.genai.Client``.
"""
import time
import typer
from typing import Optional
from ..client import get_client
from cli_tools_shared.output import print_json, print_success, print_error, print_info, handle_error

app = typer.Typer(help="Deep Research operations using Gemini Deep Research Agent")

DEFAULT_AGENT = "deep-research-pro-preview-12-2025"

# Interaction.status literals (google.genai >= 2.0.0)
_TERMINAL_OK = "completed"
_TERMINAL_FAIL = {"failed", "cancelled", "incomplete", "budget_exceeded"}


def _get_interaction_text(interaction) -> Optional[str]:
    """Return the synthesized research text from a completed interaction.

    The SDK's ``Interaction.output_text`` property collects the trailing run of
    text from the model-output steps (the new "steps" schema). Returns ``None``
    when no text content is present so callers can branch on emptiness.
    """
    text = getattr(interaction, "output_text", None)
    return text or None


def _format_interaction_error(interaction) -> str:
    """Build a human-readable failure message for a non-completed interaction.

    The new ``Interaction`` model has no flat ``error`` field; failures surface
    through ``status``. Status-update/error events carry richer detail and are
    handled separately in the streaming path.
    """
    status = getattr(interaction, "status", None) or "unknown"
    return f"status={status}"


def _render_delta(delta) -> bool:
    """Render a single ``step.delta`` delta to stdout/stderr.

    Returns ``True`` when visible report text was printed (delta type ``text``),
    so streaming callers can track whether any output was produced. Thought
    summaries (``thought_summary``) are printed as progress info and other delta
    types (tool calls/results) are ignored.
    """
    delta_type = getattr(delta, "type", None)
    if delta_type == "text":
        print(delta.text, end="", flush=True)
        return True
    if delta_type == "thought_summary":
        content = getattr(delta, "content", None)
        summary_text = getattr(content, "text", None)
        if summary_text:
            print_info(f"\n[Thinking: {summary_text}]")
    return False


@app.command("start")
def research_start(
    prompt: Optional[str] = typer.Argument(None, help="Research prompt/question"),
    prompt_file: Optional[str] = typer.Option(None, "--prompt-file", "-f", help="Read prompt from file instead of argument"),
    agent: str = typer.Option(DEFAULT_AGENT, "--agent", "-a", help="Deep Research agent to use"),
    stream: bool = typer.Option(True, "--stream/--no-stream", help="Stream results in real-time"),
    timeout: int = typer.Option(3600, "--timeout", "-t", help="Maximum time to wait in seconds (default: 60 min)"),
):
    """
    Start a deep research task using Gemini Deep Research Agent.

    The agent autonomously plans, executes, and synthesizes multi-step research tasks.
    It uses web search and can produce detailed, cited reports.

    Example:
        gemini research start "Research the history of Google TPUs"
        gemini research start "Compare React vs Vue in 2025" --no-stream
        gemini research start "Analyze Cursor AI features" --timeout 1800
        gemini research start --prompt-file /path/to/prompt.txt
    """
    # Handle prompt from file or argument
    if prompt_file:
        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                prompt = f.read().strip()
        except FileNotFoundError:
            print_error(f"Prompt file not found: {prompt_file}")
            raise typer.Exit(1)
        except Exception as e:
            print_error(f"Error reading prompt file: {e}")
            raise typer.Exit(1)

    if not prompt:
        print_error("Either provide a prompt argument or use --prompt-file")
        raise typer.Exit(1)

    try:
        client = get_client()

        print_info(f"Starting deep research with {agent}...")
        print_info("This may take several minutes. The agent will search the web and synthesize findings.\n")

        if stream:
            _run_streaming_research(client, prompt, agent, timeout)
        else:
            _run_polling_research(client, prompt, agent, timeout)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


def _run_streaming_research(client, prompt: str, agent: str, timeout: int):
    """Run research with streaming output and automatic reconnection."""

    # State tracking
    interaction_id = None
    last_event_id = None
    is_complete = False
    start_time = time.time()
    got_text_output = False

    def process_stream(event_stream):
        """Helper to process events from any stream source.

        Event schema (steps schema, google-genai >= 2.0.0). Events are a
        discriminated union keyed on ``event_type``:
          - interaction.created    -> event.interaction.id available
          - step.start             -> a new step began
          - step.delta             -> event.delta is a typed delta union
          - step.stop              -> a step finished
          - interaction.status_update -> event.status (in_progress/failed/...)
          - interaction.completed  -> terminal success
          - error                  -> event.error.{code,message}
        Delta types (event.delta.type): "text" (event.delta.text),
        "thought_summary" (event.delta.content.text), plus tool-call/result
        deltas that are not rendered here.
        """
        nonlocal last_event_id, interaction_id, is_complete, got_text_output

        for chunk in event_stream:
            # Check timeout
            if time.time() - start_time > timeout:
                print_error(f"\nResearch timed out after {timeout} seconds")
                if interaction_id:
                    print_info(f"Interaction ID: {interaction_id} (can resume later)")
                raise typer.Exit(1)

            event_type = getattr(chunk, "event_type", None)

            # Capture interaction ID
            if event_type == "interaction.created":
                interaction_id = chunk.interaction.id
                print_info(f"Research started (ID: {interaction_id})\n")

            # Track event ID for reconnection
            if getattr(chunk, "event_id", None):
                last_event_id = chunk.event_id

            # Handle incremental content
            if event_type == "step.delta":
                if _render_delta(getattr(chunk, "delta", None)):
                    got_text_output = True

            # Progress / status changes
            elif event_type == "interaction.status_update":
                status = getattr(chunk, "status", None)
                if status in _TERMINAL_FAIL:
                    print_error(f"\nResearch {status}")
                    raise typer.Exit(1)

            # Terminal success
            elif event_type == "interaction.completed":
                is_complete = True

            # Terminal error
            elif event_type == "error":
                err = getattr(chunk, "error", None)
                message = getattr(err, "message", None) or "Unknown error"
                print_error(f"\nResearch failed: {message}")
                raise typer.Exit(1)

    # 1. Attempt initial streaming request
    try:
        print_info("Starting research stream...")
        initial_stream = client.client.interactions.create(
            input=prompt,
            agent=agent,
            background=True,
            stream=True,
            agent_config={
                "type": "deep-research",
                "thinking_summaries": "auto"
            }
        )
        process_stream(initial_stream)
    except typer.Exit:
        raise
    except Exception as e:
        print_info(f"\nInitial stream interrupted: {e}")

    # 2. Reconnection loop - keep trying until complete or timeout
    reconnect_attempts = 0
    max_reconnect_attempts = 50  # Allow many reconnects for long research

    while not is_complete and interaction_id and reconnect_attempts < max_reconnect_attempts:
        # Check timeout
        if time.time() - start_time > timeout:
            print_error(f"\nResearch timed out after {timeout} seconds")
            print_info(f"Interaction ID: {interaction_id} (can check status later)")
            raise typer.Exit(1)

        reconnect_attempts += 1
        print_info(f"\nReconnecting to stream (attempt {reconnect_attempts})...")
        time.sleep(2)  # Brief delay before reconnect

        try:
            kwargs = {"stream": True}
            if last_event_id:
                kwargs["last_event_id"] = last_event_id

            resume_stream = client.client.interactions.get(interaction_id, **kwargs)
            process_stream(resume_stream)
        except typer.Exit:
            raise
        except Exception as e:
            print_info(f"Reconnection interrupted: {e}")
            # Continue loop to try again

    # 3. Final status check if we think we're complete but didn't get text
    if is_complete and not got_text_output:
        print_info("\nStream complete but no text received. Fetching final output...")
        try:
            final_interaction = client.client.interactions.get(interaction_id)
            final_text = _get_interaction_text(final_interaction)
            if final_interaction.status == _TERMINAL_OK and final_text:
                print("\n--- Research Output ---\n")
                print(final_text)
                got_text_output = True
        except Exception as e:
            print_error(f"Failed to fetch final output: {e}")

    # 4. If still no output, fall back to polling
    if not got_text_output and interaction_id:
        print_info("\nFalling back to polling for results...")
        poll_interval = 10
        while time.time() - start_time < timeout:
            try:
                interaction = client.client.interactions.get(interaction_id)
                if interaction.status == _TERMINAL_OK:
                    interaction_text = _get_interaction_text(interaction)
                    if interaction_text:
                        print("\n--- Research Output ---\n")
                        print(interaction_text)
                    print("\n")
                    print_success("Research complete!")
                    return
                elif interaction.status in _TERMINAL_FAIL:
                    print_error(f"\nResearch failed: {_format_interaction_error(interaction)}")
                    raise typer.Exit(1)
                else:
                    elapsed = time.time() - start_time
                    mins = int(elapsed // 60)
                    secs = int(elapsed % 60)
                    print(f"\r[{mins:02d}:{secs:02d}] Status: {interaction.status}...", end="", flush=True)
                    time.sleep(poll_interval)
            except typer.Exit:
                raise
            except Exception as e:
                print_error(f"Polling error: {e}")
                time.sleep(poll_interval)

        print_error(f"\nResearch timed out after {timeout} seconds")
        raise typer.Exit(1)

    if is_complete:
        print("\n")
        print_success("Research complete!")


def _run_polling_research(client, prompt: str, agent: str, timeout: int):
    """Run research with polling for results."""
    # Start the research task (background is required for Deep Research agents)
    interaction = client.client.interactions.create(
        input=prompt,
        agent=agent,
        background=True,
        agent_config={"type": "deep-research"},
    )

    interaction_id = interaction.id
    print_info(f"Research started (ID: {interaction_id})")
    print_info("Polling for results...")

    start_time = time.time()
    poll_interval = 10  # seconds

    while True:
        # Check timeout
        elapsed = time.time() - start_time
        if elapsed > timeout:
            print_error(f"\nResearch timed out after {timeout} seconds")
            print_info(f"Interaction ID: {interaction_id} (can check status later)")
            raise typer.Exit(1)

        # Get current status
        interaction = client.client.interactions.get(interaction_id)

        if interaction.status == _TERMINAL_OK:
            print("\n")
            # Get the final output
            interaction_text = _get_interaction_text(interaction)
            if interaction_text:
                print(interaction_text)
            print("\n")
            print_success("Research complete!")
            break
        elif interaction.status in _TERMINAL_FAIL:
            print_error(f"\nResearch failed: {_format_interaction_error(interaction)}")
            raise typer.Exit(1)
        else:
            # Still in progress
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            print(f"\r[{mins:02d}:{secs:02d}] Status: {interaction.status}...", end="", flush=True)
            time.sleep(poll_interval)


@app.command("status")
def research_status(
    interaction_id: str = typer.Argument(..., help="Interaction ID from a previous research task"),
):
    """
    Check the status of a running or completed research task.

    Example:
        gemini research status abc123xyz
    """
    try:
        client = get_client()

        print_info(f"Checking status for interaction: {interaction_id}")

        interaction = client.client.interactions.get(interaction_id)

        print(f"\nStatus: {interaction.status}")

        interaction_text = _get_interaction_text(interaction)
        if interaction.status == _TERMINAL_OK and interaction_text:
            print("\n--- Research Output ---\n")
            print(interaction_text)
            print_success("\nResearch complete!")
        elif interaction.status in _TERMINAL_FAIL:
            print_error(f"Research failed: {_format_interaction_error(interaction)}")
        else:
            print_info("Research still in progress...")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("resume")
def research_resume(
    interaction_id: str = typer.Argument(..., help="Interaction ID to resume streaming"),
    last_event_id: Optional[str] = typer.Option(None, "--from-event", "-e", help="Resume from specific event ID"),
):
    """
    Resume streaming a research task that was interrupted.

    Example:
        gemini research resume abc123xyz
        gemini research resume abc123xyz --from-event evt_456
    """
    try:
        client = get_client()

        print_info(f"Resuming research stream: {interaction_id}")
        if last_event_id:
            print_info(f"From event: {last_event_id}")

        kwargs = {"stream": True}
        if last_event_id:
            kwargs["last_event_id"] = last_event_id

        stream = client.client.interactions.get(interaction_id, **kwargs)

        for chunk in stream:
            event_type = getattr(chunk, "event_type", None)
            if event_type == "step.delta":
                _render_delta(getattr(chunk, "delta", None))
            elif event_type == "interaction.completed":
                print("\n")
                print_success("Research complete!")
                break
            elif event_type == "error":
                err = getattr(chunk, "error", None)
                message = getattr(err, "message", None) or "Unknown error"
                print_error(f"\nError: {message}")
                raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "resume": [
        "custom"
    ],
    "start": [
        "custom"
    ],
    "status": [
        "custom"
    ]
}
