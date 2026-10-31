// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { patient } from "@/test/fixtures";
import { errorBody, fakeApi, renderWithProviders } from "@/test/render";

import { PATIENT_PAGE_SIZE, PatientsList, type PatientFilters } from "./PatientsList";

const NO_FILTERS: PatientFilters = { q: "", status: null, page: 0 };

function manyPatients(count: number) {
  return Array.from({ length: count }, (_, index) =>
    patient({
      id: `p-${index}`,
      first_name: "Pat",
      last_name: `Number${String(index).padStart(2, "0")}`,
      email: `pat${index}@example.com`,
    }),
  );
}

describe("PatientsList", () => {
  it("shows a loading state, then the empty state for a clinic without patients", async () => {
    let release: (value: { status: number; body: unknown }) => void = () => {};
    const api = fakeApi({
      "GET /api/v1/patients": () => new Promise((resolve) => (release = resolve)),
    });
    renderWithProviders(<PatientsList filters={NO_FILTERS} onFiltersChange={vi.fn()} />, {
      fetchImpl: api.fetchImpl,
    });
    expect(screen.getByRole("status")).toHaveTextContent("Loading patients");
    release({ status: 200, body: [] });
    expect(await screen.findByText("No patients yet")).toBeInTheDocument();
  });

  it("lists patients with contact details, status and a link to the profile", async () => {
    const api = fakeApi({
      "GET /api/v1/patients": {
        status: 200,
        body: [patient(), patient({ id: "p-2", first_name: "Bo", last_name: "Okafor", email: null, status: "prospective" })],
      },
    });
    renderWithProviders(<PatientsList filters={NO_FILTERS} onFiltersChange={vi.fn()} />, {
      fetchImpl: api.fetchImpl,
    });

    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("link", { name: "Ava Lindqvist" })).toHaveAttribute(
      "href",
      "/patients/01a191cd-0b1e-7c3a-9a51-5a7d1e000001",
    );
    expect(rows[0]).toHaveTextContent("ava.lindqvist@example.com");
    expect(rows[0]).toHaveTextContent("+1-555-0101");
    expect(rows[0]).toHaveTextContent("Registered");
    expect(rows[1]).toHaveTextContent("Prospective");
    // One extra row is requested to know whether there is a next page.
    expect(api.requests[0].search).toBe(`?limit=${PATIENT_PAGE_SIZE + 1}&offset=0`);
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  });

  it("sends search and status to the API and reports filter changes", async () => {
    const onFiltersChange = vi.fn();
    const api = fakeApi({ "GET /api/v1/patients": { status: 200, body: [] } });
    renderWithProviders(
      <PatientsList
        filters={{ q: "lind", status: "registered", page: 0 }}
        onFiltersChange={onFiltersChange}
      />,
      { fetchImpl: api.fetchImpl },
    );

    expect(await screen.findByText("No patients match")).toBeInTheDocument();
    expect(api.requests[0].search).toBe("?q=lind&status=registered&limit=26&offset=0");

    const search = screen.getByLabelText("Name or email");
    expect(search).toHaveValue("lind");
    fireEvent.change(search, { target: { value: "  ava@example.com " } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(onFiltersChange).toHaveBeenLastCalledWith({
      q: "ava@example.com",
      status: "registered",
      page: 0,
    });

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "archived" } });
    expect(onFiltersChange).toHaveBeenLastCalledWith({ q: "lind", status: "archived", page: 0 });

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(onFiltersChange).toHaveBeenLastCalledWith({ q: "", status: null, page: 0 });
  });

  it("pages with offsets when the server returns more than a page", async () => {
    const onFiltersChange = vi.fn();
    const api = fakeApi({
      "GET /api/v1/patients": { status: 200, body: manyPatients(PATIENT_PAGE_SIZE + 1) },
    });
    renderWithProviders(
      <PatientsList filters={{ q: "", status: null, page: 1 }} onFiltersChange={onFiltersChange} />,
      { fetchImpl: api.fetchImpl },
    );

    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(PATIENT_PAGE_SIZE + 1);
    expect(api.requests[0].search).toBe(`?limit=26&offset=${PATIENT_PAGE_SIZE}`);
    expect(screen.getByText(`Showing 26–50`)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onFiltersChange).toHaveBeenLastCalledWith({ q: "", status: null, page: 2 });
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(onFiltersChange).toHaveBeenLastCalledWith({ q: "", status: null, page: 0 });
  });

  it("shows the server's error with its request id and retries on demand", async () => {
    let calls = 0;
    const api = fakeApi({
      "GET /api/v1/patients": () =>
        ++calls === 1
          ? { status: 400, body: errorBody("VALIDATION_ERROR", "The request is invalid.", "rid-p") }
          : { status: 200, body: [patient()] },
    });
    renderWithProviders(<PatientsList filters={NO_FILTERS} onFiltersChange={vi.fn()} />, {
      fetchImpl: api.fetchImpl,
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Patients could not be loaded.");
    expect(alert).toHaveTextContent("VALIDATION_ERROR · HTTP 400 · request rid-p");
    fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "Ava Lindqvist" })).toBeInTheDocument();
  });
});
