---
hide:
  - navigation
  - toc
---

<div class="cv-hero" markdown>

![CtxVault](assets/logo_white_text.svg){ .cv-logo }

# Local memory infrastructure for AI agents { .cv-tagline }

Isolated vaults. Typed memory. Agent-autonomous. Human-observable.

<div class="cv-actions">
  <a class="md-button md-button--primary" href="demo.html">Open the live demo</a>
  <a class="md-button" href="get-started/quick-start/">Quick start</a>
</div>

<div class="cv-install"><span class="cv-prompt">$</span><code>pip install ctxvault</code></div>

</div>

<div class="cv-tour">
  <div class="cv-frame">
    <video preload="metadata" playsinline disablepictureinpicture controlslist="nodownload noplaybackrate" poster="assets/ctxvault-tour-poster.jpg" aria-label="A tour of CtxVault: the three memory types, the vaults and agents, and the memory viewer">
      <source src="assets/ctxvault-tour.mp4" type="video/mp4">
      <track kind="subtitles" srclang="en" label="English" src="assets/ctxvault-tour.en.vtt">
    </video>
    <button class="cv-play" type="button" aria-label="Play the tour"><svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true"><path d="M8.5 5.5v13L19 12z" fill="currentColor"/></svg></button>
  </div>
</div>

<div class="grid cards" markdown>

-   **Typed memory**

    ---

    Semantic vaults for what the agent knows, skill vaults for how it acts, episodic vaults for what was true and when.

    [Memory types](how-it-works/memory-types.md)

-   **Structural isolation**

    ---

    Each vault is its own index. Restricted vaults answer only the agents attached to them, enforced on every request.

    [Access control](how-it-works/access-control.md)

-   **Observable**

    ---

    Plain directories on disk, a CLI, and a memory viewer with a map of every vault and a time cursor on episodic ones.

    [Memory viewer](memory-viewer.md)

-   **Local-first**

    ---

    No cloud, no telemetry. Use it in-process from Python, over HTTP, or give it to any MCP client.

    [Connect an agent](connect/python.md)

</div>
