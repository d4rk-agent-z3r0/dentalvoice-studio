// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { useId, useRef, useState, type KeyboardEvent } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/ui/StateViews";
import { useApiClient } from "@/lib/api/ApiProvider";
import { useApiQuery } from "@/lib/api/useApiQuery";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { ClipOutput, VoiceEnvironment } from "@/lib/voice/call";

import { TextSimulator } from "./TextSimulator";
import { VoiceSimulator } from "./VoiceSimulator";

type Mode = "voice" | "text";

const TAB_LABEL: Record<Mode, string> = {
  voice: "Voice call",
  text: "Text mode (development)",
};

/**
 * Voice is the simulator. Typed turns stay available as a secondary development tab for roles
 * that may drive calls; the tab asks the backend whether it accepts typed turns when it is first
 * opened (the backend refuses them in production) and only then offers the text form. Probing
 * lazily keeps the voice page free of a failed request on every load, since the backend has no
 * capability endpoint. Both panels stay mounted while switching, so a live call is never dropped
 * by looking at the other tab.
 */
export function SimulatorWorkspace({
  environment,
  clipOutput,
}: {
  environment?: VoiceEnvironment;
  clipOutput?: ClipOutput;
}) {
  const { session } = useAuth();
  const textAvailable = session !== null && session.claims.role !== "viewer";
  const [selected, setSelected] = useState<Mode>("voice");
  const [textOpened, setTextOpened] = useState(false);
  const mode: Mode = textAvailable ? selected : "voice";
  const modes: Mode[] = textAvailable ? ["voice", "text"] : ["voice"];
  const baseId = useId();
  const tabRefs = useRef<Partial<Record<Mode, HTMLButtonElement | null>>>({});

  function choose(next: Mode) {
    setSelected(next);
    if (next === "text") setTextOpened(true);
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const index = modes.indexOf(mode);
    let next: number | null = null;
    if (event.key === "ArrowRight") next = (index + 1) % modes.length;
    if (event.key === "ArrowLeft") next = (index - 1 + modes.length) % modes.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = modes.length - 1;
    if (next === null) return;
    event.preventDefault();
    choose(modes[next]);
    tabRefs.current[modes[next]]?.focus();
  }

  return (
    <div className="space-y-4">
      {modes.length > 1 ? (
        <div
          role="tablist"
          aria-label="Simulator mode"
          className="flex flex-wrap gap-1 border-b border-slate-200"
          onKeyDown={onKeyDown}
        >
          {modes.map((item) => {
            const active = item === mode;
            return (
              <button
                key={item}
                ref={(element) => {
                  tabRefs.current[item] = element;
                }}
                type="button"
                role="tab"
                id={`${baseId}-tab-${item}`}
                aria-selected={active}
                aria-controls={`${baseId}-panel-${item}`}
                tabIndex={active ? 0 : -1}
                onClick={() => choose(item)}
                className={`-mb-px rounded-t-md border-b-2 px-3 py-2 text-sm font-medium ${
                  active
                    ? "border-teal-700 text-teal-900"
                    : "border-transparent text-slate-700 hover:text-slate-900"
                }`}
              >
                {TAB_LABEL[item]}
              </button>
            );
          })}
        </div>
      ) : null}
      <div
        role={modes.length > 1 ? "tabpanel" : undefined}
        id={`${baseId}-panel-voice`}
        aria-labelledby={modes.length > 1 ? `${baseId}-tab-voice` : undefined}
        hidden={mode !== "voice"}
      >
        <VoiceSimulator environment={environment} clipOutput={clipOutput} />
      </div>
      {textAvailable ? (
        <div
          role="tabpanel"
          id={`${baseId}-panel-text`}
          aria-labelledby={`${baseId}-tab-text`}
          hidden={mode !== "text"}
        >
          {textOpened ? <TextModePanel /> : null}
        </div>
      ) : null}
    </div>
  );
}

function TextModePanel() {
  const api = useApiClient();
  const enabled = useApiQuery("text-turns-enabled", (signal) => api.textTurnsEnabled({ signal }));
  if (enabled.status === "loading") {
    return <LoadingState label="Checking whether this backend accepts typed turns…" />;
  }
  if (enabled.status === "error") {
    return (
      <ErrorState
        title="Could not check whether typed turns are available."
        error={enabled.error}
        onRetry={enabled.reload}
      />
    );
  }
  if (!enabled.data) {
    return (
      <EmptyState title="Text mode is not available on this backend">
        <p>
          The backend refuses typed caller turns here (they are disabled in production). Use the
          voice call: caller speech comes only from the scenario&apos;s synthetic clips.
        </p>
      </EmptyState>
    );
  }
  return <TextSimulator />;
}
