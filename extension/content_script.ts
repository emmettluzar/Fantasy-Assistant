/// <reference path="./shared.d.ts" />

/**
 * Content script (ESPN / Yahoo / Sleeper).
 *
 * Responsibilities:
 *  1. Inject the page-world `interceptor.js` early so fetch/XHR/DOM hooks are
 *     installed before the platform scripts run.
 *  2. Listen on the window CustomEvent bridge for events announced by the
 *     interceptor and forward them to the service worker.
 *  3. (Sleeper only) perform its own lightweight polling/monitoring fallback,
 *     since Sleeper is a SPA without a stable ESPN/Yahoo-style DOM.
 *
 * The service worker owns the ws://127.0.0.1:8080 connection and deduplicates.
 */

(() => {
  const BRIDGE_EVENT = "fantasy-draft-assistant-bridge";
  const host = window.location.hostname;
  const platform = host.includes("espn.com")
    ? "espn"
    : host.includes("yahoo.com")
      ? "yahoo"
      : host.includes("sleeper.app")
        ? "sleeper"
        : undefined;

  if (!platform) return;

  /** Inject a page-world script synchronously — must run before page code. */
  const injectScript = (src: string): void => {
    try {
      const script = document.createElement("script");
      script.src = chrome.runtime.getURL(src);
      script.async = false;
      (document.head || document.documentElement).appendChild(script);
      script.remove();
    } catch (_) {
      /* injection unavailable */
    }
  };

  // Interceptor is only useful on ESPN / Yahoo (Sleeper is handled below).
  if (platform === "espn" || platform === "yahoo") {
    injectScript("interceptor.js");
  }

  /** Forward a raw event from the page to the service worker. */
  const forward = (event: Record<string, unknown>): void => {
    try {
      (chrome.runtime.sendMessage(event) as Promise<unknown>).catch(() => {});
    } catch (_) {
      /* service worker may be waking; message is best-effort */
    }
  };

  // ----------------------------------------------------------------------
  // Listen for the page bridge events.
  // ----------------------------------------------------------------------
  window.addEventListener(BRIDGE_EVENT, (event) => {
    const detail = (event as CustomEvent).detail as Partial<RawDraftEvent> | undefined;
    if (!detail || typeof detail !== "object") return;
    detail.platform = platform;
    forward({ kind: "raw-event", event: detail });
  });

  // ----------------------------------------------------------------------
  // Sleeper: poll a small set of internal endpoints and DOM. Sleeper exposes a
  // public API (https://api.sleeper.app/v1); its SPA also stores picks in the
  // DOM / window state. This mirrors the extension's job: observe + forward
  // normalized picks to the background worker.
  // ----------------------------------------------------------------------
  if (platform === "sleeper") {
    const seenPicks = new Set<string>();

    const sleeperScan = (): void => {
      // Best-effort DOM scan for rosters/picks rendered in the draft room.
      const nodes = document.querySelectorAll(
        '[class*="pick"], [class*="Pick"], [data-testid*="pick"]',
      );
      nodes.forEach((el) => {
        const htmlEl = el as HTMLElement;
        const text = (htmlEl.innerText || htmlEl.textContent || "").trim().slice(0, 200);
        if (!text) return;
        forward({
          kind: "raw-event",
          event: {
            platform: "sleeper",
            kind: "dom-candidate",
            payload: { text, tag: el.tagName },
            ts: Date.now(),
          },
        });
      });

      // Report any window-held draft state if available.
      const s = window.__SLEEPER_DRAFT_STATE__ as
        | { picks?: Array<Record<string, any>> }
        | undefined;
      if (s && Array.isArray(s.picks)) {
        s.picks.forEach((p) => {
          const key = `${p.player_id}:${p.pick_no}:${p.roster_id}`;
          if (seenPicks.has(key)) return;
          seenPicks.add(key);
          forward({
            kind: "raw-event",
            event: {
              platform: "sleeper",
              kind: "pick",
              payload: {
                platform: "sleeper",
                player_id: p.player_id,
                player_name:
                  p.player && p.player.first_name
                    ? `${p.player.first_name} ${p.player.last_name}`
                    : p.player_id,
                position: p.player ? p.player.position : undefined,
                team_index: p.roster_id ?? p.team_index ?? 0,
                round: p.round ?? 1,
                pick_number: p.pick_no ?? p.pick_number ?? seenPicks.size + 1,
                timestamp: p.timestamp ?? Date.now() / 1000,
              },
              ts: Date.now(),
            },
          });
        });
      }
    };

    setInterval(sleeperScan, 1500);
    window.addEventListener("load", sleeperScan);
  }

  // Initiate the bridge readiness handshake (status message for debugging).
  forward({ kind: "content-ready", platform, ts: Date.now() });
})();