AGENTS.md: Multi-Agent Architecture and Task Assignment
1. Orchestrator Agent

    Role: Coordinates system build order, verifies IPC messaging channels between Tauri and Python, and enforces state consistency.

    Inputs: System build requests and platform updates.

    Outputs: Module assignments, integration test suites, and application build pipelines.

2. Analytics Engine Agent (Python)

    Role: Builds the statistical pipeline, imports nfl_data_py / nflfastR datasets, computes xFP, WOPR, EPA, and calculates dynamic VORP scores.

    Primary Dependencies: pandas, numpy, scikit-learn, nfl_data_py, espn-api, yfpy.

    Target Modules: engine/projections.py, engine/dvorp.py, engine/probability.py.

3. Platform Integration Agent (Python & TypeScript)

    Role: Implements platform adapters for Sleeper, ESPN, and Yahoo, managing authentication, OAuth flows, and pick event normalization.

    Primary Dependencies: requests, websockets, espn-api, yfpy.

    Target Modules: integrations/sleeper.py, integrations/espn.py, integrations/yahoo.py.

4. Universal Sync Extension Agent (Browser Extension)

    Role: Implements the Manifest v3 extension to intercept DOM mutations and network requests inside live ESPN and Yahoo draft rooms.

    Primary Dependencies: Chrome Extension API, DOM MutationObserver, WebSocket Client.

    Target Modules: extension/manifest.json, extension/content_script.ts, extension/background.ts.

5. UI/UX Frontend Agent (React & Tauri)

    Role: Builds the user interface, real-time draft board, optimal pick recommendations, player search filters, and league format toggles.

    Primary Dependencies: React, TypeScript, Tailwind CSS, Zustand, Tauri IPC API.

    Target Modules: src/components/DraftBoard.tsx, src/components/RecommendationCard.tsx, src/store/useDraftStore.ts.