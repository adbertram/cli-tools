"""Regression tests for Cloudflare-challenge detection in ``_page_info``.

Mercari embeds its OWN invisible reCAPTCHA Enterprise badge on every page;
that site-owned badge must NOT count as a human-verification challenge,
while the real evidence -- Cloudflare interstitial selectors, hCaptcha
iframes, and the challenge title/body text -- still must.
"""

import json
import os
import shutil
import subprocess

import pytest

from mercari_cli.client import MercariChallengeError, MercariClient


class _Page:
    """Fake browser page returning a canned ``_page_info`` payload."""

    def __init__(self, info):
        self.info = info
        self.calls = 0

    def evaluate(self, _script):
        self.calls += 1
        return self.info


class _ScriptCapturePage:
    """Fake page that records the JS handed to ``evaluate``."""

    def __init__(self):
        self.script = None

    def evaluate(self, script):
        self.script = script
        return {}


def _page_info_script() -> str:
    """Return the exact JS arrow function ``_page_info`` evaluates."""
    page = _ScriptCapturePage()
    MercariClient._page_info(page)
    assert page.script is not None
    return page.script


def _page_info_code() -> str:
    """Return ``_page_info``'s JS with line comments removed so assertions
    target executable code rather than prose."""
    return "\n".join(
        line.split("//", 1)[0] for line in _page_info_script().splitlines()
    )


# Invisible reCAPTCHA Enterprise anchor iframe exactly as Mercari mounts it
# on every healthy page (site chrome, verified live).
_RECAPTCHA_ANCHOR_IFRAME = {
    "tag": "iframe",
    "src": (
        "https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6LeIZ4glAAAAADq"
        "&co=aHR0cHM6Ly93d3cubWVyY2FyaS5jb206NDQz&hl=en&type=image&size=invisible"
    ),
}

# Each real challenge marker must still flip ``challenged`` to True. The
# element-based ones go through querySelector; the text ones through the
# title/body regex.
_REAL_CHALLENGE_SCENARIOS = {
    "cf-challenge-running element": {"elements": [{"id": "cf-challenge-running"}]},
    "cf-browser-verification element": {
        "elements": [{"classes": ["cf-browser-verification"]}]
    },
    "cloudflare challenges iframe": {
        "elements": [
            {"tag": "iframe", "src": "https://challenges.cloudflare.com/turnstile/v0/g/4c19/api.js"}
        ]
    },
    "hcaptcha iframe": {
        "elements": [
            {"tag": "iframe", "src": "https://newassets.hcaptcha.com/captcha/v1/hl/en/static/hcaptcha.html#frame=challenge"}
        ]
    },
    "'just a moment' title": {"title": "just a moment..."},
    "'verify you are human' body": {
        "body_text": "Please verify you are human to continue."
    },
    "'ray id' body": {"body_text": "Error 1020 Ray ID: 8f3a9b2c7d1e."},
}

_NODE_HARNESS = r"""
const scenario = JSON.parse(process.env.SCENARIO);
const elements = scenario.elements.map((e) => ({
  tag: e.tag || "div",
  id: e.id || "",
  classes: e.classes || [],
  src: e.src || "",
}));

function elementMatches(el, selector) {
  const idMatch = selector.match(/^#([A-Za-z0-9_-]+)$/);
  if (idMatch) return el.id === idMatch[1];
  const classMatch = selector.match(/^\.([A-Za-z0-9_-]+)$/);
  if (classMatch) return el.classes.includes(classMatch[1]);
  const srcMatch = selector.match(/^iframe\[src\*="([^"]+)"\]$/);
  if (srcMatch) return el.tag === "iframe" && el.src.includes(srcMatch[1]);
  throw new Error("unsupported selector in test harness: " + selector);
}

globalThis.document = {
  title: scenario.title,
  body: { innerText: scenario.bodyText },
  querySelector(selectors) {
    for (const raw of selectors.split(",")) {
      const selector = raw.trim();
      for (const el of elements) {
        if (elementMatches(el, selector)) return el;
      }
    }
    return null;
  },
};
globalThis.window = {};

const info = eval(process.env.PAGE_INFO_SCRIPT)();
process.stdout.write(JSON.stringify(info));
"""


def _run_page_info_js(elements=None, title="", body_text=""):
    """Evaluate the real ``_page_info`` JS against a stubbed DOM via node."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available to execute the real _page_info JS")
    env = dict(
        os.environ,
        PAGE_INFO_SCRIPT=_page_info_script(),
        SCENARIO=json.dumps(
            {
                "elements": elements or [],
                "title": title,
                "bodyText": body_text,
            }
        ),
    )
    proc = subprocess.run(
        [node, "-e", _NODE_HARNESS],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_recaptcha_badge_alone_is_not_a_challenge():
    """A page whose only marker is Mercari's own invisible recaptcha
    enterprise anchor iframe must pass readiness without raising."""
    info = _run_page_info_js(
        elements=[_RECAPTCHA_ANCHOR_IFRAME],
        title="your go-to marketplace | mercari",
        body_text="Mercari — The Marketplace",
    )
    assert info["challenged"] is False

    # The _page_info payload shape must be accepted by the gate.
    MercariClient._raise_on_challenge(info)  # does not raise

    ready_page = _Page({**info, "routerReady": True})
    MercariClient._wait_ready(ready_page)
    assert ready_page.calls == 1


@pytest.mark.parametrize("name", sorted(_REAL_CHALLENGE_SCENARIOS))
def test_real_challenge_markers_still_raise(name):
    """Every kept real-world marker still raises MercariChallengeError."""
    info = _run_page_info_js(**_REAL_CHALLENGE_SCENARIOS[name])
    assert info["challenged"] is True
    with pytest.raises(MercariChallengeError, match="human verification challenge"):
        MercariClient._raise_on_challenge(info)


def test_page_info_js_keeps_real_markers_and_drops_recaptcha():
    """Guard against reintroducing the false-positive selector."""
    code = _page_info_code()
    assert 'iframe[src*="recaptcha"]' not in code
    for marker in (
        "#cf-challenge-running",
        ".cf-browser-verification",
        'iframe[src*="challenges.cloudflare.com"]',
        'iframe[src*="hcaptcha"]',
    ):
        assert marker in code
