// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  APPOINTMENT_ID,
  CHECKUP_TYPE_ID,
  DENTIST_ID,
  PATIENT_ID,
  SECOND_DENTIST_ID,
  appointment,
  availability,
  clinicInfo,
  makeToken,
  patient,
} from "@/test/fixtures";
import {
  errorBody,
  fakeApi,
  renderWithProviders,
  signedInStore,
  type RecordedRequest,
  type Route,
} from "@/test/render";

import { AppointmentsDashboard } from "./AppointmentsDashboard";

const KEY_PATTERN = /^[A-Za-z0-9_-]{8,128}$/;

function routes(overrides: Record<string, Route | { status: number; body?: unknown }> = {}) {
  return fakeApi({
    "GET /api/v1/clinic": { status: 200, body: clinicInfo() },
    "GET /api/v1/patients": { status: 200, body: [patient()] },
    "GET /api/v1/appointments": { status: 200, body: [appointment()] },
    "GET /api/v1/availability": {
      status: 200,
      body: availability([
        { start: "09:00", end: "09:30" },
        { start: "09:30", end: "10:00" },
        { start: "10:00", end: "10:30", dentist: "bo" },
      ]),
    },
    ...overrides,
  });
}

const requestsTo = (requests: RecordedRequest[], method: string, path: string) =>
  requests.filter((r) => r.method === method && r.path === path);

function renderDashboard(api: ReturnType<typeof fakeApi>, role = "staff") {
  return renderWithProviders(<AppointmentsDashboard initialPatientId={null} />, {
    fetchImpl: api.fetchImpl,
    store: signedInStore(makeToken({ role })),
  });
}

describe("AppointmentsDashboard", () => {
  it("lists the next 14 clinic-local days with names, local times and status", async () => {
    const api = routes({
      "GET /api/v1/appointments": {
        status: 200,
        body: [
          appointment(),
          appointment({ id: "a-2", status: "cancelled", dentist_id: SECOND_DENTIST_ID }),
        ],
      },
    });
    renderDashboard(api);

    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("Tue, 3 Nov 2026");
    expect(rows[0]).toHaveTextContent("10:00–10:30");
    expect(rows[0]).toHaveTextContent("Check-up · Dr. Ada Example");
    expect(within(rows[0]).getByRole("link", { name: "Ava Lindqvist" })).toHaveAttribute(
      "href",
      `/patients/${PATIENT_ID}`,
    );
    expect(rows[0]).toHaveTextContent("Confirmed");
    expect(within(rows[0]).getByRole("button", { name: /^Cancel / })).toBeInTheDocument();
    // Inactive appointments cannot be changed.
    expect(rows[1]).toHaveTextContent("Cancelled");
    expect(within(rows[1]).queryByRole("button")).not.toBeInTheDocument();

    const [list] = requestsTo(api.requests, "GET", "/api/v1/appointments");
    expect(list.search).toBe("?from=2026-11-02&to=2026-11-15&limit=200");
    expect(screen.getByText(/clinic-local \(Europe\/London\)/)).toBeInTheDocument();
  });

  it("sends the date range and status filters", async () => {
    const api = routes({ "GET /api/v1/appointments": { status: 200, body: [] } });
    renderDashboard(api);
    expect(await screen.findByText("No appointments in this range")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-12-01" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-12-07" } });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "cancelled" } });
    await waitFor(() =>
      expect(requestsTo(api.requests, "GET", "/api/v1/appointments").at(-1)?.search).toBe(
        "?from=2026-12-01&to=2026-12-07&status=cancelled&limit=200",
      ),
    );
  });

  it("is read-only for a viewer", async () => {
    const api = routes();
    renderDashboard(api, "viewer");

    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByText("Read-only access")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Book an appointment" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Cancel|Reschedule/ })).not.toBeInTheDocument();
    expect(requestsTo(api.requests, "GET", "/api/v1/availability")).toHaveLength(0);
  });

  it("books the chosen time with an Idempotency-Key and shows what the server returned", async () => {
    let lists = 0;
    const api = routes({
      "GET /api/v1/appointments": () => ({ status: 200, body: ++lists === 1 ? [] : [appointment()] }),
      "POST /api/v1/appointments": {
        status: 201,
        body: appointment({
          starts_at: "2026-11-02T09:30:00Z",
          ends_at: "2026-11-02T10:00:00Z",
          starts_at_local: "2026-11-02T09:30:00+00:00",
          ends_at_local: "2026-11-02T10:00:00+00:00",
        }),
      },
    });
    renderDashboard(api);

    const book = await screen.findByRole("button", { name: "Book appointment" });
    expect(book).toBeDisabled();
    const [lookup] = requestsTo(api.requests, "GET", "/api/v1/availability");
    expect(lookup.search).toBe(`?appointment_type_id=${CHECKUP_TYPE_ID}&date=2026-11-02`);
    expect(await screen.findByText(/Available times on Mon, 2 Nov 2026/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "09:30 to 10:00 with Dr. Ada Example" }));
    fireEvent.click(book);

    const status = await screen.findByText(/Confirmed:/);
    expect(status.parentElement).toHaveTextContent(
      "Confirmed: Check-up with Dr. Ada Example for Ava Lindqvist, Mon, 2 Nov 2026, 09:30–10:00 (Europe/London).",
    );
    const [post] = requestsTo(api.requests, "POST", "/api/v1/appointments");
    expect(post.body).toEqual({
      patient_id: PATIENT_ID,
      appointment_type_id: CHECKUP_TYPE_ID,
      dentist_id: DENTIST_ID,
      starts_at: "2026-11-02T09:30:00Z",
      conversation_id: null,
    });
    expect(post.headers.get("Idempotency-Key")).toMatch(KEY_PATTERN);
    // The list and the availability are both read again after the booking committed.
    await waitFor(() => expect(lists).toBe(2));
    expect(requestsTo(api.requests, "GET", "/api/v1/availability")).toHaveLength(2);
  });

  it("refreshes availability and the list, and says the time was just taken, on 409 BOOKING_SLOT_TAKEN", async () => {
    const api = routes({
      "POST /api/v1/appointments": {
        status: 409,
        body: errorBody("BOOKING_SLOT_TAKEN", "That time is no longer available.", "rid-409"),
      },
    });
    renderDashboard(api);

    fireEvent.click(await screen.findByRole("radio", { name: "09:00 to 09:30 with Dr. Ada Example" }));
    fireEvent.click(screen.getByRole("button", { name: "Book appointment" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That time was just taken by another booking.");
    expect(alert).toHaveTextContent("That time is no longer available.");
    expect(alert).toHaveTextContent("BOOKING_SLOT_TAKEN · HTTP 409 · request rid-409");
    await waitFor(() =>
      expect(requestsTo(api.requests, "GET", "/api/v1/availability")).toHaveLength(2),
    );
    await waitFor(() =>
      expect(requestsTo(api.requests, "GET", "/api/v1/appointments")).toHaveLength(2),
    );
    expect(await screen.findByRole("button", { name: "Book appointment" })).toBeDisabled();
  });

  it("reuses the key when the same booking is retried, and makes a new one for a new choice", async () => {
    let posts = 0;
    const api = routes({
      "POST /api/v1/appointments": () => {
        posts += 1;
        if (posts === 1) throw new TypeError("Failed to fetch");
        return { status: 201, body: appointment() };
      },
    });
    renderDashboard(api);

    fireEvent.click(await screen.findByRole("radio", { name: "09:00 to 09:30 with Dr. Ada Example" }));
    fireEvent.click(screen.getByRole("button", { name: "Book appointment" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Trying again is safe: it reuses the same booking key.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Book appointment" }));
    expect(await screen.findByText(/Confirmed:/)).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("radio", { name: "10:00 to 10:30 with Dr. Bo Example" }));
    fireEvent.click(screen.getByRole("button", { name: "Book appointment" }));
    await waitFor(() => expect(posts).toBe(3));

    const keys = requestsTo(api.requests, "POST", "/api/v1/appointments").map((r) =>
      r.headers.get("Idempotency-Key"),
    );
    expect(keys[0]).toMatch(KEY_PATTERN);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).toMatch(KEY_PATTERN);
    expect(keys[2]).not.toBe(keys[0]);
  });

  it("shows a 403 from the server even when the UI offered the action", async () => {
    const api = routes({
      "POST /api/v1/appointments": {
        status: 403,
        body: errorBody("FORBIDDEN", "Your role does not allow this action."),
      },
    });
    renderDashboard(api);

    fireEvent.click(await screen.findByRole("radio", { name: "09:00 to 09:30 with Dr. Ada Example" }));
    fireEvent.click(screen.getByRole("button", { name: "Book appointment" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Your role does not allow this action.");
    expect(alert).toHaveTextContent("FORBIDDEN · HTTP 403");
  });

  it("cancels after confirmation and reloads the list", async () => {
    let lists = 0;
    const api = routes({
      "GET /api/v1/appointments": () => ({
        status: 200,
        body: [appointment({ status: ++lists === 1 ? "confirmed" : "cancelled" })],
      }),
      [`POST /api/v1/appointments/${APPOINTMENT_ID}/cancel`]: {
        status: 200,
        body: appointment({ status: "cancelled" }),
      },
    });
    renderDashboard(api);

    fireEvent.click(await screen.findByRole("button", { name: /^Cancel Ava Lindqvist/ }));
    expect(requestsTo(api.requests, "POST", `/api/v1/appointments/${APPOINTMENT_ID}/cancel`)).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Confirm cancel" }));

    expect(await screen.findByText(/Cancelled:/)).toHaveTextContent("Cancelled:");
    expect(screen.getByText(/The time is bookable again/)).toBeInTheDocument();
    await waitFor(() => expect(lists).toBe(2));
    expect(within(screen.getByRole("table")).queryByRole("button")).not.toBeInTheDocument();
  });

  it("explains APPOINTMENT_NOT_ACTIVE on cancel and refreshes", async () => {
    let lists = 0;
    const api = routes({
      "GET /api/v1/appointments": () => {
        lists += 1;
        return { status: 200, body: [appointment()] };
      },
      [`POST /api/v1/appointments/${APPOINTMENT_ID}/cancel`]: {
        status: 409,
        body: errorBody("APPOINTMENT_NOT_ACTIVE", "This appointment is no longer active."),
      },
    });
    renderDashboard(api);

    fireEvent.click(await screen.findByRole("button", { name: /^Cancel Ava Lindqvist/ }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm cancel" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This appointment is no longer active, so it cannot be changed.",
    );
    await waitFor(() => expect(lists).toBe(2));
  });

  it("reschedules to a time with the same dentist and reports the new appointment", async () => {
    let attempts = 0;
    const api = routes({
      [`POST /api/v1/appointments/${APPOINTMENT_ID}/reschedule`]: () =>
        ++attempts === 1
          ? { status: 409, body: errorBody("BOOKING_SLOT_TAKEN", "That time is no longer available.") }
          : {
              status: 201,
              body: appointment({
                id: "a-new",
                rescheduled_from_id: APPOINTMENT_ID,
                starts_at_local: "2026-11-03T09:30:00+00:00",
                ends_at_local: "2026-11-03T10:00:00+00:00",
              }),
            },
    });
    renderDashboard(api);

    fireEvent.click(await screen.findByRole("button", { name: /^Reschedule Ava Lindqvist/ }));
    const heading = await screen.findByRole("heading", { name: "Reschedule appointment" });
    expect(heading).toHaveFocus();
    // Starts on the appointment's own day, and only offers the same dentist's times.
    await waitFor(() =>
      expect(requestsTo(api.requests, "GET", "/api/v1/availability").at(-1)?.search).toBe(
        `?appointment_type_id=${CHECKUP_TYPE_ID}&date=2026-11-03`,
      ),
    );
    expect(await screen.findByRole("radio", { name: "09:00 to 09:30 with Dr. Ada Example" })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /Dr. Bo Example/ })).not.toBeInTheDocument();

    const before = requestsTo(api.requests, "GET", "/api/v1/availability").length;
    fireEvent.click(screen.getByRole("radio", { name: "09:30 to 10:00 with Dr. Ada Example" }));
    fireEvent.click(screen.getByRole("button", { name: "Move appointment" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That time was just taken");
    await waitFor(() =>
      expect(requestsTo(api.requests, "GET", "/api/v1/availability").length).toBe(before + 1),
    );

    fireEvent.click(await screen.findByRole("radio", { name: "09:30 to 10:00 with Dr. Ada Example" }));
    fireEvent.click(screen.getByRole("button", { name: "Move appointment" }));
    expect(await screen.findByText(/Rescheduled:/)).toBeInTheDocument();
    expect(screen.getByText(/Tue, 3 Nov 2026, 09:30–10:00/)).toBeInTheDocument();
    const posts = requestsTo(api.requests, "POST", `/api/v1/appointments/${APPOINTMENT_ID}/reschedule`);
    expect(posts.map((p) => p.body)).toEqual([
      { starts_at: "2026-11-02T09:30:00Z" },
      { starts_at: "2026-11-02T09:30:00Z" },
    ]);
    expect(screen.queryByRole("heading", { name: "Reschedule appointment" })).not.toBeInTheDocument();
  });

  it("shows the server's error when the clinic calendar cannot be loaded", async () => {
    const api = routes({
      "GET /api/v1/clinic": { status: 503, body: errorBody("PROVIDER_UNAVAILABLE", "Database unavailable.") },
    });
    renderDashboard(api);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The clinic calendar could not be loaded.");
    expect(alert).toHaveTextContent("PROVIDER_UNAVAILABLE · HTTP 503");
  });
});
