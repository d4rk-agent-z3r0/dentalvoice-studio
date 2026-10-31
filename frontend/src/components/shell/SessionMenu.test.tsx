// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { act, fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useApiClient } from "@/lib/api/ApiProvider";
import { useApiQuery } from "@/lib/api/useApiQuery";
import { SESSION_STORAGE_KEY } from "@/lib/auth/session-store";
import { readDisplayClaims } from "@/lib/auth/token";
import {
  CLINIC_ID,
  SECOND_CLINIC_ID,
  authMe,
  authTokenResponse,
  clinicInfo,
  makeToken,
} from "@/test/fixtures";
import {
  deferred,
  errorBody,
  fakeApi,
  memoryStorage,
  renderShell,
  type RecordedRequest,
} from "@/test/render";

const navigation = vi.hoisted(() => ({ pathname: "/appointments", replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ replace: navigation.replace }),
}));

beforeEach(() => {
  navigation.pathname = "/appointments";
  navigation.replace.mockReset();
});

/** A clinic-scoped page: shows the name of the clinic the API answers for. */
function ClinicNamePage() {
  const api = useApiClient();
  const clinic = useApiQuery("clinic", (signal) => api.getClinic({ signal }));
  if (clinic.status === "loading") return <p>Loading clinic…</p>;
  if (clinic.status === "error") return <p>Clinic failed</p>;
  return <p data-testid="page-clinic">{clinic.data.name}</p>;
}

const FIRST_PAGE_NAME = "BrightSmile Dental Studio";
const SECOND_PAGE_NAME = "Harbour View Dental Studio";

function clinicOf(request: RecordedRequest): string | null {
  const token = request.headers.get("Authorization")?.replace(/^Bearer /, "") ?? "";
  return readDisplayClaims(token)?.clinicId ?? null;
}

/** Answers `GET /clinic` for whichever clinic the bearer token is for. */
const clinicRoute = (request: RecordedRequest) => ({
  status: 200,
  body: clinicInfo(
    clinicOf(request) === SECOND_CLINIC_ID
      ? { id: SECOND_CLINIC_ID, name: SECOND_PAGE_NAME }
      : { name: FIRST_PAGE_NAME },
  ),
});

const SWITCHED = authTokenResponse({
  clinic: { id: SECOND_CLINIC_ID, name: "Harbour View Dental", timezone: "Europe/London" },
  role: "staff",
});

function signedIn(profile = authMe(), token = makeToken({ role: profile.role })) {
  return { token, profile };
}

function renderSignedIn(
  routes: Parameters<typeof fakeApi>[0],
  { token, profile } = signedIn(),
  page = <ClinicNamePage />,
) {
  const api = fakeApi(routes);
  const view = renderShell(page, { fetchImpl: api.fetchImpl });
  act(() => {
    view.store.setSession(token, "password", profile);
  });
  return { ...view, api, token };
}

const header = () => screen.getByRole("banner");
const openSwitcher = () => fireEvent.click(within(header()).getByRole("button", { name: "Switch clinic" }));

describe("session menu", () => {
  it("shows the user, clinic and role, without a switcher for a single clinic", async () => {
    const single = authMe({ clinics: [{ id: CLINIC_ID, name: "BrightSmile Dental", role: "admin" }] });
    renderSignedIn({ "GET /api/v1/clinic": clinicRoute }, signedIn(single));
    await screen.findByText(FIRST_PAGE_NAME);
    expect(within(header()).getByText("Demo Admin")).toBeInTheDocument();
    expect(within(header()).getByText("BrightSmile Dental")).toBeInTheDocument();
    expect(within(header()).getByText("admin")).toBeInTheDocument();
    expect(within(header()).queryByRole("button", { name: "Switch clinic" })).not.toBeInTheDocument();
    expect(within(header()).getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("switches clinic: replaces the token and refetches, never showing the old clinic's data", async () => {
    const secondPage = deferred<{ status: number; body?: unknown }>();
    const { api, storage, token } = renderSignedIn({
      "GET /api/v1/clinic": (request) =>
        clinicOf(request) === SECOND_CLINIC_ID ? secondPage.promise : clinicRoute(request),
      "POST /api/v1/auth/switch-clinic": { status: 200, body: SWITCHED },
    });
    expect(await screen.findByText(FIRST_PAGE_NAME)).toBeInTheDocument();

    openSwitcher();
    const panel = screen.getByRole("region", { name: "Switch clinic" });
    expect(within(panel).getByText("BrightSmile Dental")).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(within(panel).getByRole("button", { name: /Harbour View Dental/ }));
    });

    const switchRequest = api.requests.find((r) => r.path === "/api/v1/auth/switch-clinic");
    expect(switchRequest?.headers.get("Authorization")).toBe(`Bearer ${token}`);
    expect(switchRequest?.body).toEqual({ clinic_id: SECOND_CLINIC_ID });
    expect(JSON.parse(storage.getItem(SESSION_STORAGE_KEY) ?? "{}")).toEqual({
      token: SWITCHED.access_token,
      method: "password",
    });
    // The new clinic's data is still loading: the previous clinic's must already be gone.
    expect(screen.queryByText(FIRST_PAGE_NAME)).not.toBeInTheDocument();
    expect(screen.getByText("Loading clinic…")).toBeInTheDocument();
    expect(within(header()).getByText("Harbour View Dental")).toBeInTheDocument();
    expect(within(header()).getByText("staff")).toBeInTheDocument();

    await act(async () => secondPage.resolve(clinicRoute(api.requests.at(-1)!)));
    expect(screen.getByTestId("page-clinic")).toHaveTextContent(SECOND_PAGE_NAME);
    const clinicRequests = api.requests.filter((r) => r.path === "/api/v1/clinic");
    expect(clinicRequests.map(clinicOf)).toEqual([CLINIC_ID, SECOND_CLINIC_ID]);
    expect(screen.queryByRole("region", { name: "Switch clinic" })).not.toBeInTheDocument();
    expect(navigation.replace).not.toHaveBeenCalled();
  });

  it("leaves a detail page for its section list after switching", async () => {
    navigation.pathname = "/patients/01a191cd-0b1e-7c3a-9a51-5a7d1e000001";
    renderSignedIn({
      "GET /api/v1/clinic": clinicRoute,
      "POST /api/v1/auth/switch-clinic": { status: 200, body: SWITCHED },
    });
    await screen.findByText(FIRST_PAGE_NAME);
    openSwitcher();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Harbour View Dental/ }));
    });
    expect(navigation.replace).toHaveBeenCalledWith("/patients");
  });

  it("shows a refused switch with the server's message and keeps the session", async () => {
    const { storage, token } = renderSignedIn({
      "GET /api/v1/clinic": clinicRoute,
      "POST /api/v1/auth/switch-clinic": {
        status: 403,
        body: errorBody("FORBIDDEN", "You are not a member of that clinic.", "rid-403"),
      },
    });
    await screen.findByText(FIRST_PAGE_NAME);
    openSwitcher();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Harbour View Dental/ }));
    });
    const alert = within(screen.getByRole("region", { name: "Switch clinic" })).getByRole("alert");
    expect(alert).toHaveTextContent("You are not a member of that clinic.");
    expect(alert).toHaveTextContent("rid-403");
    expect(JSON.parse(storage.getItem(SESSION_STORAGE_KEY) ?? "{}").token).toBe(token);
    expect(screen.getByText(FIRST_PAGE_NAME)).toBeInTheDocument();
  });

  it("closes the switcher with Escape and returns focus to its button", async () => {
    renderSignedIn({ "GET /api/v1/clinic": clinicRoute });
    await screen.findByText(FIRST_PAGE_NAME);
    openSwitcher();
    const toggle = within(header()).getByRole("button", { name: "Switch clinic" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.keyDown(screen.getByRole("button", { name: /Harbour View Dental/ }), { key: "Escape" });
    expect(screen.queryByRole("region", { name: "Switch clinic" })).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
  });

  it("signs out: clears storage and shows the sign-in form", async () => {
    const { storage, store } = renderSignedIn({ "GET /api/v1/clinic": clinicRoute });
    await screen.findByText(FIRST_PAGE_NAME);
    fireEvent.click(within(header()).getByRole("button", { name: "Sign out" }));
    expect(storage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(store.getToken()).toBeNull();
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByText(FIRST_PAGE_NAME)).not.toBeInTheDocument();
  });

  it("ignores a switch that completes after sign-out", async () => {
    const reply = deferred<{ status: number; body?: unknown }>();
    const { storage, store } = renderSignedIn({
      "GET /api/v1/clinic": clinicRoute,
      "POST /api/v1/auth/switch-clinic": () => reply.promise,
    });
    await screen.findByText(FIRST_PAGE_NAME);
    openSwitcher();
    fireEvent.click(screen.getByRole("button", { name: /Harbour View Dental/ }));
    fireEvent.click(within(header()).getByRole("button", { name: "Sign out" }));
    await act(async () => reply.resolve({ status: 200, body: SWITCHED }));
    expect(store.getToken()).toBeNull();
    expect(storage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("restores the user and clinics after a reload with GET /auth/me", async () => {
    const storage = memoryStorage();
    const token = makeToken({ role: "admin" });
    storage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ token, method: "password" }));
    const api = fakeApi({
      "GET /api/v1/auth/me": { status: 200, body: authMe() },
      "GET /api/v1/clinic": clinicRoute,
    });
    renderShell(<ClinicNamePage />, { fetchImpl: api.fetchImpl, storage });

    expect(await within(header()).findByText("Demo Admin")).toBeInTheDocument();
    const me = api.requests.filter((r) => r.path === "/api/v1/auth/me");
    expect(me).toHaveLength(1);
    expect(me[0].headers.get("Authorization")).toBe(`Bearer ${token}`);
    expect(within(header()).getByRole("button", { name: "Switch clinic" })).toBeInTheDocument();
  });
});
