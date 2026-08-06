// 404 — a client route that matched nothing.
//
// The server hands every unmatched HTML navigation to the SPA (see app.py's
// spa_fallback_handler), so this is where a genuinely wrong URL lands.

import type { JSX } from "react";
import { Link } from "react-router";
import { Crumbs, Masthead, Module } from "../components/Page";

export function NotFound(): JSX.Element {
  return (
    <>
      <Crumbs here="Not found" />

      <Masthead
        eyebrow="404"
        title="Not Found"
        tagline="That page doesn't exist."
        spec={[
          { k: "Status", v: "404" },
          { k: "Route", v: "unmatched" },
        ]}
        specLabel="Error detail"
      />

      <Module index="01" title="Where To Go" meta="Working routes">
        <ul className="channel-grid" role="list">
          <li><Link className="channel" to="/">Overview</Link></li>
          <li><Link className="channel" to="/methodology">Methodology</Link></li>
          <li><Link className="channel" to="/benchmarks">Benchmarks</Link></li>
          <li><Link className="channel" to="/changelog">Changelog</Link></li>
          <li><Link className="channel" to="/studio">Studio</Link></li>
          <li><Link className="channel" to="/guide">Docs</Link></li>
        </ul>
      </Module>
    </>
  );
}
