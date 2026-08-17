/**
 * Page-injected interceptor (ESPN / Yahoo only).
 *
 * Injected at `document_start` via the content script. It lives in the page's
 * world so it can:
 *
 *   - monkey-patch `window.fetch` and `XMLHttpRequest` to observe platform
 *     network payloads that carry draft-pick data, and
 *   - run `MutationObserver`s against live draft DOM.
 *
 * Detected picks are normalized and announced to the content script through a
 * CustomEvent bridge on `window` (the only channel page + content scripts
 * share). The background service worker -- not this script -- owns the actual
 * `ws://127.0.0.1:8080` connection.
 */
(() => {
  if (window.__FDA_BRIDGE_INSTALLED__) return;
  window.__FDA_BRIDGE_INSTALLED__ = true;

  const BRIDGE_EVENT = "fantasy-draft-assistant-bridge";

  /** Announce a raw event to the content script. */
  const post = (event) => {
    try {
      window.dispatchEvent(
        new CustomEvent(BRIDGE_EVENT, { detail: JSON.parse(JSON.stringify(event)) }),
      );
    } catch (_) {
      // Ignore unserializable detail; the event is best-effort telemetry only.
    }
  };

  const ready = Promise.resolve({ source: "fantasy-draft-assistant-bridge", state: "connected" });
  window.__FDA_BRIDGE__ = Object.freeze({ post, ready });

  const host = window.location.hostname;
  const platform = host.includes("espn.com")
    ? "espn"
    : host.includes("yahoo.com")
      ? "yahoo"
      : "sleeper";

  // ----------------------------------------------------------------------
  // Deduplication: the same pick may surface via network + DOM + internal
  // APIs. Keep a bounded fingerprint cache so we emit exactly once.
  // ----------------------------------------------------------------------
  const seen = new Set();
  const remember = (key) => {
    if (seen.has(key)) return false;
    seen.add(key);
    if (seen.size > 2000) {
      const oldest = seen.values().next().value;
      seen.delete(oldest);
    }
    return true;
  };
  const fingerprint = (playerId, teamIndex, pickNumber) =>
    `${platform}:${playerId}:${teamIndex}:${pickNumber}`;

  // ----------------------------------------------------------------------
  // Normalization: coerces platform-specific shapes into a generic candidate.
  // ----------------------------------------------------------------------
  const toInt = (v) => {
    const n = parseInt(v, 10);
    return Number.isFinite(n) ? n : undefined;
  };

  /** Dig through common wrapper keys for the first object value. */
  const firstObject = (v, depth = 0) => {
    if (!v || depth > 3) return undefined;
    if (typeof v === "object" && !Array.isArray(v)) return v;
    if (Array.isArray(v)) {
      for (const item of v) {
        const found = firstObject(item, depth + 1);
        if (found) return found;
      }
    }
    return undefined;
  };

  /** Best-effort position normalization from arbitrary strings. */
  const normalizePosition = (v) => {
    if (typeof v !== "string") return undefined;
    const s = v.trim().toUpperCase();
    if (s === "K") return "K";
    if (s === "DST" || s === "DEF" || s === "D/ST" || s === "D") return "DST";
    if (s === "QB" || s === "RB" || s === "WR" || s === "TE") return s;
    return undefined;
  };

  const findKey = (obj, candidates) => {
    for (const key of Object.keys(obj || {})) {
      const lk = key.toLowerCase();
      if (candidates.some((c) => lk === c)) return key;
    }
    return undefined;
  };

  /** Turn an arbitrary object (any nesting) into a normalized pick candidate. */
  function toCandidate(input) {
    const obj = firstObject(input);
    if (!obj) return undefined;

    const name =
      _stringField(obj, ["player_name", "playername", "playerName", "name", "fullName", "display_name"]) ||
      _stringField(obj, ["player"], (v) => typeof v === "string") ||
      _nestedString(obj, ["player"], ["name", "full_name", "fullName", "display_name"]);

    const id =
      _stringField(obj, ["player_id", "playerid", "playerId", "id"]) ||
      _nested(obj, ["player"], ["id", "player_id", "playerId"]) ||
      name;

    const position =
      _stringField(obj, ["position", "pos", "slot", "player_position"]) ||
      _nested(obj, ["player"], ["position", "pos", "default_position"]);

    const teamIndex =
      _intField(obj, ["team_index", "teamindex", "teamIndex", "draft_slot", "draftSlot", "pick_team"]) ??
      _nestedInt(obj, ["team"], ["index", "draft_slot", "draftSlot"]);

    const round =
      _intField(obj, ["round", "rnd"]) ?? _nestedInt(obj, ["round"], ["number", "round_number"]);

    const pickNumber =
      _intField(obj, ["pick_number", "picknumber", "pickNumber", "overall_pick", "overallPick", "pick"]) ??
      _nestedInt(obj, ["pick"], ["number", "pick_number", "overall"]);

    const timestamp =
      _floatField(obj, ["timestamp", "time", "picked_at", "pickedAt"]) ?? Date.now() / 1000;

    return { playerName: name, playerId: id, position, teamIndex, round, pickNumber, timestamp };
  }

  const _stringField = (obj, keys, pred) => {
    for (const key of Object.keys(obj || {})) {
      const lk = key.toLowerCase();
      if (keys.some((k) => lk === k)) {
        const v = obj[key];
        if (typeof v === "string" && (!pred || pred(v))) return v;
      }
    }
    return undefined;
  };

  const _intField = (obj, keys) => {
    for (const key of Object.keys(obj || {})) {
      const lk = key.toLowerCase();
      if (keys.some((k) => lk === k)) {
        const n = toInt(obj[key]);
        if (n !== undefined) return n;
      }
    }
    return undefined;
  };

  const _floatField = (obj, keys) => {
    for (const key of Object.keys(obj || {})) {
      const lk = key.toLowerCase();
      if (keys.some((k) => lk === k)) {
        const n = Number(obj[key]);
        if (Number.isFinite(n)) return n;
      }
    }
    return undefined;
  };

  const _nested = (obj, path, keys) => {
    let node = obj;
    for (const part of path) {
      if (!node || typeof node !== "object") return undefined;
      node = node[part];
    }
    return _stringField(node, keys);
  };

  const _nestedString = (obj, path, keys) => _nested(obj, path, keys);
  const _nestedInt = (obj, path, keys) => {
    let node = obj;
    for (const part of path) {
      if (!node || typeof node !== "object") return undefined;
      node = node[part];
    }
    return _intField(node, keys);
  };

  /** Emit a detected pick if we have enough to unambiguously identify it. */
  function emitPick(candidate) {
    if (!candidate) return;
    const playerId = candidate.playerId ?? candidate.playerName;
    if (!playerId || candidate.teamIndex === undefined || candidate.pickNumber === undefined) {
      // Still announce DOM/network hints for debugging, but not as a pick.
      return;
    }
    if (!remember(fingerprint(playerId, candidate.teamIndex, candidate.pickNumber))) return;

    const payload = {
      platform,
      player_id: String(playerId),
      player_name: candidate.playerName ? String(candidate.playerName) : undefined,
      position: normalizePosition(candidate.position),
      team_index: candidate.teamIndex,
      round: candidate.round ?? 1,
      pick_number: candidate.pickNumber,
      timestamp: candidate.timestamp,
    };
    post({ platform, kind: "pick", payload, ts: Date.now() });
  }

  function inspectPayload(value) {
    const obj = firstObject(value);
    if (!obj) return;
    const candidate = toCandidate(obj);
    if (candidate && candidate.playerId && candidate.teamIndex !== undefined && candidate.pickNumber !== undefined) {
      emitPick(candidate);
    }
    // Announce a copy for the fallback extractor to work on as well.
    post({ platform, kind: "network", payload: obj, ts: Date.now() });
  }

  // ----------------------------------------------------------------------
  // window.fetch monkey-patch
  // ----------------------------------------------------------------------
  if (typeof window.fetch === "function") {
    const originalFetch = window.fetch;
    window.fetch = function (...args) {
      const result = originalFetch.apply(this, args);
      try {
        result.then(async (response) => {
          try {
            if (!response || typeof response.clone !== "function") return;
            const text = await response.clone().text();
            let value;
            try {
              value = JSON.parse(text);
            } catch (_) {
              return;
            }
            inspectPayload(value);
          } catch (_) {
            /* best-effort */
          }
        });
      } catch (_) {
        /* best-effort */
      }
      return result;
    };
  }

  // ----------------------------------------------------------------------
  // XMLHttpRequest monkey-patch (read `responseText`/`response` on settle)
  // ----------------------------------------------------------------------
  if (typeof XMLHttpRequest !== "undefined") {
    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function (...args) {
      this.__fdaUrl = args[1];
      return origOpen.apply(this, args);
    };

    XMLHttpRequest.prototype.send = function (...args) {
      const xhr = this;
      const finish = () => {
        try {
          const raw = xhr.responseText || xhr.response;
          if (typeof raw !== "string") return;
          let value;
          try {
            value = JSON.parse(raw);
          } catch (_) {
            return;
          }
          inspectPayload(value);
        } catch (_) {
          /* best-effort */
        }
      };

      try {
        xhr.addEventListener("loadend", finish);
      } catch (_) {
        /* best-effort */
      }
      return origSend.apply(this, args);
    };
  }

  // ----------------------------------------------------------------------
  // DOM MutationObserver for live draft boards
  // ----------------------------------------------------------------------
  const HEURISTIC_SELECTORS = [
    '[data-testid*="draft" i]',
    '[class*="draft" i]',
    '[id*="draft" i]',
    '[class*="pick" i]',
    // ESPN
    '.draft-pick',
    '[class*="PlayerName"]',
    // Yahoo
    '[class*="DraftPick"]',
    '[data-tst*="picked"]',
  ];

  const walker = () => document.querySelectorAll(HEURISTIC_SELECTORS.join(","));

  const scan = () => {
    walker().forEach((el) => {
      const text = (el.innerText || el.textContent || "").trim().slice(0, 160);
      if (!text) return;
      post({ platform, kind: "dom-candidate", payload: { text, tag: el.tagName }, ts: Date.now() });
    });
  };

  (function startObservers() {
    try {
      const throttle = () => {
        if (startObservers._pending) return;
        startObservers._pending = true;
        requestAnimationFrame(() => {
          startObservers._pending = false;
          scan();
        });
      };
      const observer = new MutationObserver(throttle);
      observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
      window.addEventListener("load", scan);
    } catch (_) {
      /* observer unavailable */
    }
  })();
})();