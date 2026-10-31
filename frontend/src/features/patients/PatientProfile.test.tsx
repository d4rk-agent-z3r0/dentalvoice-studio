// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  PATIENT_ID,
  appointment,
  clinicInfo,
  makeToken,
  patientDetail,
  scenario,
} from "@/test/fixtures";
import { errorBody, fakeApi, renderWithProviders, signedInStore } from "@/test/render";

import { PatientProfile } from "./PatientProfile";

const scenarios = { status: 200, body: [scenario()] };
const clinicReply = { status: 200, body: clinicInfo() };

describe("PatientProfile", () => {
  it("shows contact details, the latest confirmed intake, linked calls and appointments", async () => {
    const api = fakeApi({
      [`GET /api/v1/patients/${PATIENT_ID}`]: {
        status: 200,
        body: patientDetail({
          appointments: [
            appointment(),
            appointment({
              id: "a-old",
              status: "rescheduled",
              starts_at_local: "2026-11-02T09:00:00+00:00",
              ends_at_local: "2026-11-02T09:30:00+00:00",
            }),
          ],
        }),
      },
      "GET /api/v1/scenarios": scenarios,
      "GET /api/v1/clinic": clinicReply,
    });
    renderWithProviders(<PatientProfile patientId={PATIENT_ID} />, { fetchImpl: api.fetchImpl });

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Ava Lindqvist");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Registered");

    const contact = screen.getByRole("region", { name: "Contact details" });
    expect(contact).toHaveTextContent("ava.lindqvist@example.com");
    expect(contact).toHaveTextContent("+1-555-0101");
    expect(contact).toHaveTextContent("Preferred contactEmail");
    expect(contact).toHaveTextContent("New patient");

    const intake = screen.getByRole("region", { name: "Latest confirmed intake" });
    expect(intake).toHaveTextContent("Routine cleaning");
    expect(intake).toHaveTextContent("hygiene_cleaning");
    // A clinic calendar date and wall-clock time, shown as recorded.
    expect(intake).toHaveTextContent("Tue, 3 Nov 2026, 10:00");
    expect(within(intake).getByRole("link")).toHaveAttribute(
      "href",
      "/conversations/01a191cc-ade4-7197-9e80-ad9477bbf4f2",
    );

    const calls = screen.getByRole("region", { name: "Linked conversations" });
    const callRow = within(calls).getAllByRole("row")[1];
    expect(callRow).toHaveTextContent("A · New patient: routine cleaning");
    expect(callRow).toHaveTextContent("Completed");
    expect(callRow).toHaveTextContent("Confirmed");

    const appointments = within(screen.getByRole("region", { name: "Patient appointments" }))
      .getAllByRole("row")
      .slice(1);
    expect(appointments[0]).toHaveTextContent("Tue, 3 Nov 2026, 10:00–10:30");
    expect(appointments[0]).toHaveTextContent("Confirmed");
    expect(appointments[1]).toHaveTextContent("Mon, 2 Nov 2026, 09:00–09:30");
    expect(appointments[1]).toHaveTextContent("Rescheduled");
    // Type and dentist names come from the clinic reference data.
    expect(appointments[0]).toHaveTextContent("Check-up · Dr. Ada Example");
    expect(screen.getByRole("link", { name: "Book an appointment" })).toHaveAttribute(
      "href",
      `/appointments?patient=${PATIENT_ID}`,
    );
  });

  it("offers no booking link to a viewer", async () => {
    const api = fakeApi({
      [`GET /api/v1/patients/${PATIENT_ID}`]: { status: 200, body: patientDetail() },
      "GET /api/v1/scenarios": scenarios,
      "GET /api/v1/clinic": clinicReply,
    });
    renderWithProviders(<PatientProfile patientId={PATIENT_ID} />, {
      fetchImpl: api.fetchImpl,
      store: signedInStore(makeToken({ role: "viewer" })),
    });
    expect(await screen.findByRole("region", { name: "Patient appointments" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Book an appointment" })).not.toBeInTheDocument();
  });

  it("says so when the patient has no history yet", async () => {
    const api = fakeApi({
      [`GET /api/v1/patients/${PATIENT_ID}`]: {
        status: 200,
        body: patientDetail({ conversations: [], appointments: [], latest_snapshot: null }),
      },
      "GET /api/v1/scenarios": scenarios,
      "GET /api/v1/clinic": clinicReply,
    });
    renderWithProviders(<PatientProfile patientId={PATIENT_ID} />, { fetchImpl: api.fetchImpl });

    expect(await screen.findByText(/No confirmed intake yet/)).toBeInTheDocument();
    expect(screen.getByText("No conversations are linked to this patient.")).toBeInTheDocument();
    expect(screen.getByText("No appointments for this patient.")).toBeInTheDocument();
  });

  it("treats a 404 as not found without leaking whether another clinic has it", async () => {
    const api = fakeApi({
      [`GET /api/v1/patients/${PATIENT_ID}`]: {
        status: 404,
        body: errorBody("NOT_FOUND", "Patient not found."),
      },
      "GET /api/v1/scenarios": scenarios,
      "GET /api/v1/clinic": clinicReply,
    });
    renderWithProviders(<PatientProfile patientId={PATIENT_ID} />, { fetchImpl: api.fetchImpl });

    expect(await screen.findByText("Patient not found")).toBeInTheDocument();
    expect(screen.getByText(/belongs to another clinic/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All patients" })).toHaveAttribute("href", "/patients");
  });

  it("shows other failures with the server's code", async () => {
    const api = fakeApi({
      [`GET /api/v1/patients/${PATIENT_ID}`]: {
        status: 503,
        body: errorBody("PROVIDER_UNAVAILABLE", "Database unavailable.", "rid-x"),
      },
      "GET /api/v1/scenarios": scenarios,
      "GET /api/v1/clinic": clinicReply,
    });
    renderWithProviders(<PatientProfile patientId={PATIENT_ID} />, { fetchImpl: api.fetchImpl });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This patient could not be loaded.");
    expect(alert).toHaveTextContent("PROVIDER_UNAVAILABLE · HTTP 503 · request rid-x");
  });
});
