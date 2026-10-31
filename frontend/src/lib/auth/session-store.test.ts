// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { describe, expect, it } from "vitest";

import { SECOND_CLINIC_ID, authMe, makeToken } from "@/test/fixtures";
import { memoryStorage } from "@/test/render";

import { createSessionStore, SESSION_STORAGE_KEY } from "./session-store";

describe("session store", () => {
  it("mirrors only the token and method to storage; the profile stays in memory", () => {
    const storage = memoryStorage();
    const store = createSessionStore(() => storage);
    const token = makeToken({ role: "admin" });

    const session = store.setSession(token, "password", authMe());

    expect(session.profile?.user.display_name).toBe("Demo Admin");
    expect(JSON.parse(storage.getItem(SESSION_STORAGE_KEY) ?? "{}")).toEqual({
      token,
      method: "password",
    });
    expect(storage.getItem(SESSION_STORAGE_KEY)).not.toContain("example.com");

    const reloaded = createSessionStore(() => storage).getSnapshot();
    expect(reloaded).toMatchObject({
      status: "signed_in",
      session: { token, method: "password", profile: null },
    });
  });

  it("adds the profile only to the session it was fetched for", () => {
    const store = createSessionStore(() => memoryStorage());
    const first = makeToken();
    store.setSession(first, "password");
    const second = makeToken({ clinic_id: SECOND_CLINIC_ID });
    store.setSession(second, "password");

    store.setProfile(first, authMe());
    expect(store.getSnapshot()).toMatchObject({ session: { token: second, profile: null } });

    store.setProfile(second, authMe());
    expect(store.getSnapshot()).toMatchObject({
      session: { token: second, profile: { role: "admin" } },
    });

    store.clear();
    store.setProfile(second, authMe());
    expect(store.getSnapshot()).toEqual({ status: "signed_out", notice: null });
  });

  it("ignores a stored session with an unknown method", () => {
    const storage = memoryStorage();
    storage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ token: makeToken(), method: "sso" }));
    expect(createSessionStore(() => storage).getSnapshot()).toEqual({
      status: "signed_out",
      notice: null,
    });
  });
});
