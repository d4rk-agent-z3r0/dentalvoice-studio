// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SESSION_STORAGE_KEY } from "@/lib/auth/session-store";
import { authTokenResponse } from "@/test/fixtures";
import { deferred, errorBody, fakeApi, renderShell } from "@/test/render";

vi.mock("next/navigation", () => ({
  usePathname: () => "/conversations",
  useRouter: () => ({ replace: vi.fn() }),
}));

const EMAIL = "demo.admin@example.com";
/** A throwaway value per test, so no password-like string is committed. */
const freshPassword = () => `pw-${crypto.randomUUID()}`;

const emailInput = () => screen.getByLabelText("Email") as HTMLInputElement;
const passwordInput = () => screen.getByLabelText("Password") as HTMLInputElement;
const submitButton = () => screen.getByRole("button", { name: /^Sign(ing)? in/ });
const form = () => screen.getByRole("form", { name: "Sign in" });

function fillAndSubmit(password = freshPassword(), email = EMAIL) {
  fireEvent.change(emailInput(), { target: { value: email } });
  fireEvent.change(passwordInput(), { target: { value: password } });
  fireEvent.click(submitButton());
  return password;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

describe("password sign-in", () => {
  it("is the default sign-in, with labelled fields and the right autocomplete hints", () => {
    renderShell(<p>Protected content</p>);
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(emailInput()).toHaveAttribute("type", "email");
    expect(emailInput()).toHaveAttribute("autocomplete", "username");
    expect(passwordInput()).toHaveAttribute("type", "password");
    expect(passwordInput()).toHaveAttribute("autocomplete", "current-password");
    expect(form()).toHaveAttribute("method", "post");
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });

  it("signs in, stores only the token and shows who is signed in", async () => {
    const response = authTokenResponse();
    const api = fakeApi({ "POST /api/v1/auth/login": { status: 200, body: response } });
    const { storage } = renderShell(<p>Protected content</p>, { fetchImpl: api.fetchImpl });

    const password = fillAndSubmit(undefined, `  ${EMAIL} `);

    expect(await screen.findByText("Protected content")).toBeInTheDocument();
    expect(api.requests).toHaveLength(1);
    expect(api.requests[0].body).toEqual({ email: EMAIL, password });
    expect(api.requests[0].headers.has("Authorization")).toBe(false);
    const stored = storage.getItem(SESSION_STORAGE_KEY) ?? "";
    expect(JSON.parse(stored)).toEqual({ token: response.access_token, method: "password" });
    expect(stored).not.toContain(password);
    const header = screen.getByRole("banner");
    expect(within(header).getByText("Demo Admin")).toBeInTheDocument();
    expect(within(header).getByText("BrightSmile Dental")).toBeInTheDocument();
    expect(within(header).getByText("admin")).toBeInTheDocument();
    expect(within(header).queryByText("Dev token")).not.toBeInTheDocument();
  });

  it("shows the server's message and request id on failure, clears the password and keeps the email", async () => {
    const api = fakeApi({
      "POST /api/v1/auth/login": {
        status: 401,
        body: errorBody("AUTH_FAILED", "Email or password is incorrect.", "rid-login-401"),
      },
    });
    const { store } = renderShell(<p>Protected content</p>, { fetchImpl: api.fetchImpl });

    fillAndSubmit();

    const alert = await within(form()).findByRole("alert");
    expect(alert).toHaveTextContent("Email or password is incorrect.");
    expect(alert).toHaveTextContent("rid-login-401");
    expect(passwordInput().value).toBe("");
    expect(passwordInput()).toHaveFocus();
    expect(emailInput().value).toBe(EMAIL);
    expect(submitButton()).toBeEnabled();
    // A wrong password is not an expired session: no "rejected" notice, still signed out.
    expect(store.getSnapshot()).toEqual({ status: "signed_out", notice: null });
    expect(screen.queryByText(/rejected the session/)).not.toBeInTheDocument();
  });

  it("disables submit while the request is pending", async () => {
    const reply = deferred<{ status: number; body?: unknown }>();
    const api = fakeApi({ "POST /api/v1/auth/login": () => reply.promise });
    renderShell(<p>Protected content</p>, { fetchImpl: api.fetchImpl });

    fillAndSubmit();
    expect(submitButton()).toBeDisabled();
    expect(submitButton()).toHaveTextContent("Signing in…");
    fireEvent.submit(form());
    expect(api.requests).toHaveLength(1);

    await act(async () => {
      reply.resolve({ status: 401, body: errorBody("AUTH_FAILED", "Email or password is incorrect.") });
    });
    expect(submitButton()).toBeEnabled();
    expect(passwordInput().value).toBe("");
  });

  it("counts down from the server's wait after 429 and keeps submit disabled until zero", async () => {
    vi.useFakeTimers();
    const api = fakeApi({
      "POST /api/v1/auth/login": {
        status: 429,
        body: {
          error: {
            code: "RATE_LIMITED",
            message: "Too many sign-in attempts. Try again later.",
            request_id: "rid-429",
            retry_after_seconds: 3,
          },
        },
      },
    });
    renderShell(<p>Protected content</p>, { fetchImpl: api.fetchImpl });

    fillAndSubmit();
    await act(() => vi.advanceTimersByTimeAsync(0));

    expect(within(form()).getByRole("alert")).toHaveTextContent("Too many sign-in attempts.");
    expect(within(form()).getByRole("alert")).toHaveTextContent("rid-429");
    expect(screen.getByText("You can try again in 3 seconds.")).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
    expect(passwordInput().value).toBe("");

    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(screen.getByText("You can try again in 2 seconds.")).toBeInTheDocument();
    fireEvent.change(passwordInput(), { target: { value: freshPassword() } });
    fireEvent.submit(form());
    expect(api.requests).toHaveLength(1);

    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(screen.getByText("You can try again in 1 second.")).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();

    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(screen.queryByText(/You can try again in/)).not.toBeInTheDocument();
    expect(submitButton()).toBeEnabled();
  });

  it("asks for both fields before sending anything", () => {
    const api = fakeApi({});
    renderShell(<p>Protected content</p>, { fetchImpl: api.fetchImpl });
    fireEvent.change(passwordInput(), { target: { value: freshPassword() } });
    fireEvent.click(submitButton());
    expect(within(form()).getByRole("alert")).toHaveTextContent("Enter your email and password.");
    expect(passwordInput().value).toBe("");
    expect(api.requests).toHaveLength(0);
  });
});

describe("developer token option", () => {
  it("is a secondary, clearly labelled option outside production", () => {
    renderShell(<p>Protected content</p>);
    expect(screen.queryByRole("heading", { name: "Developer sign-in" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use a developer token instead" }));
    expect(screen.getByRole("heading", { name: "Developer sign-in" })).toBeInTheDocument();
    expect(screen.getAllByText("Development only").length).toBeGreaterThan(0);
  });

  it("is not offered in production", () => {
    vi.stubEnv("NODE_ENV", "production");
    renderShell(<p>Protected content</p>);
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /developer token/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Access token")).not.toBeInTheDocument();
    expect(screen.queryByText("Development only")).not.toBeInTheDocument();
  });
});
