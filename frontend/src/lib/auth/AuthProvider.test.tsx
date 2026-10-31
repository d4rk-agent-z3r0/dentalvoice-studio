// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { act, fireEvent, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";

import { RequireSession } from "@/components/auth/RequireSession";
import { AppHeader } from "@/components/shell/AppHeader";
import { ApiProvider } from "@/lib/api/ApiProvider";
import { ApiError } from "@/lib/api/errors";
import { CLINIC_ID, makeToken } from "@/test/fixtures";
import { errorBody, fakeApi, memoryStorage } from "@/test/render";

import { AuthProvider, useAuth, type AuthContextValue } from "./AuthProvider";
import { createSessionStore, SESSION_STORAGE_KEY } from "./session-store";
import { readDisplayClaims } from "./token";

vi.mock("next/navigation", () => ({
  usePathname: () => "/conversations",
  useRouter: () => ({ replace: vi.fn() }),
}));

const probe: { current: AuthContextValue | null } = { current: null };
function Probe() {
  const value = useAuth();
  useEffect(() => {
    probe.current = value;
  });
  return null;
}

function renderAuth(storage: Storage = memoryStorage(), now = () => Date.UTC(2026, 9, 31)) {
  const store = createSessionStore(() => storage);
  // A backend without `GET /auth/me`: the header falls back to the token's claims.
  const api = fakeApi({
    "GET /api/v1/auth/me": { status: 404, body: errorBody("NOT_FOUND", "Not found.") },
  });
  render(
    <AuthProvider store={store} now={now}>
      <ApiProvider fetchImpl={api.fetchImpl}>
        <Probe />
        <AppHeader />
        <main>
          <RequireSession>
            <p>Protected content</p>
          </RequireSession>
        </main>
      </ApiProvider>
    </AuthProvider>,
  );
  return { store, storage };
}

function signInWith(token: string) {
  if (!screen.queryByLabelText("Access token")) {
    fireEvent.click(screen.getByRole("button", { name: "Use a developer token instead" }));
  }
  fireEvent.change(screen.getByLabelText("Access token"), { target: { value: token } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in with token" }));
}

describe("readDisplayClaims", () => {
  it("reads clinic, role, subject and expiry from the payload", () => {
    expect(readDisplayClaims(makeToken({ role: "viewer", exp: 2_000_000_000 }))).toEqual({
      userId: "01a191cc-3a00-7000-8000-0000000005e7",
      clinicId: CLINIC_ID,
      role: "viewer",
      expiresAt: 2_000_000_000_000,
    });
  });

  it("rejects values that are not JWT-shaped", () => {
    expect(readDisplayClaims("not-a-token")).toBeNull();
    expect(readDisplayClaims("a.b.c")).toBeNull();
    expect(readDisplayClaims(`x.${btoa("[1,2]")}.y`)).toBeNull();
  });
});

describe("AuthProvider with developer sign-in", () => {
  it("shows the sign-in screen, with the developer token as a secondary option, when there is no session", () => {
    renderAuth();
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByText("Development only")).toBeInTheDocument();
    expect(screen.queryByLabelText("Access token")).not.toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
    expect(screen.getByText("Not signed in")).toBeInTheDocument();
  });

  it("signs in with a pasted token, keeps it in sessionStorage and shows clinic and role", () => {
    const { storage } = renderAuth();
    const token = makeToken({ role: "admin" });

    signInWith(`  ${token}\n`);

    expect(screen.getByText("Protected content")).toBeInTheDocument();
    expect(probe.current?.status).toBe("signed_in");
    expect(probe.current?.getToken()).toBe(token);
    expect(JSON.parse(storage.getItem(SESSION_STORAGE_KEY) ?? "{}")).toEqual({
      token,
      method: "developer_token",
    });
    expect(screen.getByText("admin")).toBeInTheDocument();
    expect(screen.getByTitle(CLINIC_ID)).toHaveTextContent(CLINIC_ID.slice(-8));
    expect(screen.getByText("Dev token")).toBeInTheDocument();
  });

  it("restores the session from sessionStorage on load", () => {
    const storage = memoryStorage();
    const token = makeToken();
    storage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ token, method: "developer_token" }));
    renderAuth(storage);
    expect(screen.getByText("Protected content")).toBeInTheDocument();
    expect(probe.current?.getToken()).toBe(token);
  });

  it("ignores corrupt stored sessions", () => {
    const storage = memoryStorage();
    storage.setItem(SESSION_STORAGE_KEY, "{not json");
    renderAuth(storage);
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("refuses a malformed token with an explanation", () => {
    renderAuth();
    signInWith("hello");
    expect(screen.getByRole("alert")).toHaveTextContent("does not look like an access token");
    expect(probe.current?.status).toBe("signed_out");
  });

  it("refuses an expired token", () => {
    renderAuth(memoryStorage(), () => 3_000_000_000_000);
    signInWith(makeToken({ exp: 2_000_000_000 }));
    expect(screen.getByRole("alert")).toHaveTextContent("This token has expired");
    expect(probe.current?.status).toBe("signed_out");
  });

  it("signs out from the header and clears storage", () => {
    const { storage } = renderAuth();
    signInWith(makeToken());
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(storage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(probe.current?.getToken()).toBeNull();
  });

  it("ends the session with the server's reason when the API rejects it", () => {
    renderAuth();
    signInWith(makeToken());
    act(() =>
      probe.current?.rejectSession(
        new ApiError({ status: 401, code: "AUTH_INVALID", message: "The access token has expired." }),
      ),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The API rejected the session (AUTH_INVALID): The access token has expired.",
    );
  });

  it("keeps working in memory when storage throws", () => {
    const broken: Storage = {
      ...memoryStorage(),
      getItem: () => {
        throw new DOMException("blocked", "SecurityError");
      },
      setItem: () => {
        throw new DOMException("blocked", "SecurityError");
      },
      removeItem: () => {
        throw new DOMException("blocked", "SecurityError");
      },
    };
    renderAuth(broken);
    signInWith(makeToken());
    expect(screen.getByText("Protected content")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("renders a neutral checking state on the server snapshot", () => {
    const store = createSessionStore(() => memoryStorage());
    expect(store.getServerSnapshot()).toEqual({ status: "checking" });
  });
});

describe("AppHeader", () => {
  it("shows the product name and the five primary sections, marking the current one", () => {
    renderAuth();
    expect(screen.getByRole("link", { name: "DentalVoice Studio" })).toHaveAttribute("href", "/");
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const links = Array.from(nav.querySelectorAll("a")).map((a) => a.textContent);
    expect(links).toEqual(["Simulator", "Conversations", "Patients", "Appointments", "Analytics"]);
    expect(screen.getByRole("link", { name: "Conversations" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Simulator" })).not.toHaveAttribute("aria-current");
  });
});
